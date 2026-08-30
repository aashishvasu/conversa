"""The research preparation and run endpoints."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from api.auth import require_auth
from api.chat import Msg
from api.sse import sse
from providers import DEFAULT_MODEL, complete_messages
from research import runs

router = APIRouter()

PREPARE_SYSTEM = """Decide how to handle the latest user request in this conversation.

Research capability is enabled for every request. That alone is not a reason to research. Default to `answer` and reserve `research` for requests that explicitly ask for investigation or whose answer genuinely requires gathering multiple external sources. Greetings, ordinary conversation, advice, explanations, writing, coding help that can be answered from the supplied context, and follow-up discussion are `answer`. Choose `clarify` only when neither an answer nor useful research can proceed without user input.

Return JSON only, with exactly these keys: action, goal, questions.
`action` is one of `answer`, `clarify`, or `research`.
`goal` is a standalone, specific restatement of the user's intended outcome. It must retain the subject and constraints from the conversation; never use context-dependent wording such as "research this".
`questions` is an array of zero to five concise questions. It is normally empty unless action is `clarify`."""


class PrepareRequest(BaseModel):
    messages: list[Msg]
    system: str | list[str] | None = None
    model: str | None = None


class PrepareResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["answer", "clarify", "research"]
    goal: str
    questions: list[str]

    @field_validator("goal")
    @classmethod
    def standalone_goal(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("goal must not be empty")
        return value

    @field_validator("questions")
    @classmethod
    def valid_questions(cls, value):
        if len(value) > 5 or any(not question.strip() for question in value):
            raise ValueError("questions must contain at most five non-empty strings")
        return [question.strip() for question in value]


def parse_prepare_response(text):
    """Accept only the JSON object that the browser contract understands."""
    try:
        return PrepareResponse.model_validate_json(text)
    except (ValidationError, ValueError) as error:
        raise ValueError("preparation model returned an invalid decision") from error


def prepare_system(system):
    if isinstance(system, list):
        return [*system, PREPARE_SYSTEM]
    return f"{system}\n\n{PREPARE_SYSTEM}" if system else PREPARE_SYSTEM


@router.post("/api/research/prepare", response_model=PrepareResponse)
async def research_prepare(req: PrepareRequest, _=Depends(require_auth)):
    try:
        text = await complete_messages(
            req.model or DEFAULT_MODEL,
            prepare_system(req.system),
            [message.model_dump() for message in req.messages],
            max_tokens=1024,
        )
        return parse_prepare_response(text)
    except ValueError as error:
        raise HTTPException(502, {"code": "research_prepare_failed", "message": str(error)}) from error
    except Exception as error:
        raise HTTPException(502, {"code": "research_prepare_failed", "message": "research preparation failed"}) from error


class ResearchRequest(BaseModel):
    id: str
    goal: str
    title: str | None = None
    models: dict[str, str]  # search | note | report -> model id
    depth: int = 6  # sources per subquestion
    prompts: dict[str, str] | None = None


@router.post("/api/research")
async def research_start(req: ResearchRequest, _=Depends(require_auth)):
    run, resumed = runs.start(req.goal, req.models, depth=max(1, min(req.depth, 12)), title=req.title, prompts=req.prompts, run_id=req.id)
    return {"id": run.id, "resumed": resumed, "status": run.status, "phase": run.phase}


@router.get("/api/research/{run_id}")
async def research_state(run_id: str, after: int = 0, _=Depends(require_auth)):
    runs.evict()
    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, {"code": "no_such_run", "message": "no such run, or it ended before you came back"})
    return run.state(after)


@router.get("/api/research/{run_id}/stream")
async def research_stream(run_id: str, after: int = 0, _=Depends(require_auth)):
    """Replay this run's events from `after`, then tail it live until it finishes.

    Reconnecting with the last seq you saw is lossless, because the events are a list rather than a broadcast.
    """

    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, {"code": "no_such_run", "message": "no such run, or it ended before you came back"})

    async def tail():
        seen = after
        while True:
            if len(run.events) > seen:
                for event in run.events[seen:]:
                    yield sse(**event, spend=run.spend.as_dict())
                seen = len(run.events)
            if run.status != "running":
                yield sse(kind="final", **run.state(len(run.events)))
                return
            # Gather and report each run for a minute or more without emitting an event.
            # A connection silent that long is one a proxy closes, and the client cannot tell that from a finished run.
            # The tick carries no seq, so it never counts toward the caller's replay position.
            yield sse(kind="tick", phase=run.phase, spend=run.spend.as_dict())
            await asyncio.sleep(1)

    return StreamingResponse(tail(), media_type="text/event-stream")


@router.delete("/api/research/{run_id}")
async def research_discard(run_id: str, _=Depends(require_auth)):
    """Done with this run.

    Running means cancel, and the run stays so the stream can deliver its final frame.
    Finished means forget, which is what the client calls once it has stored the payload.
    """
    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, {"code": "no_such_run", "message": "no such run"})
    if run.status == "running":
        if run.task:
            run.task.cancel()
        return {"status": "cancelling"}
    runs.forget(run_id)
    return {"status": "forgotten"}
