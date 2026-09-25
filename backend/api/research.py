"""Research preparation and run endpoints."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from api.auth import require_auth
from api.chat import Msg
from api.sse import sse
from providers import DEFAULT_MODEL, complete_messages
from research import runs
from research.parsing import object_from_text
from research.state import validate_checkpoint
from research.prompts import PREPARE_SYSTEM

router = APIRouter()


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str
    reason: str
    default: str

    @field_validator("question", "reason", "default")
    @classmethod
    def non_empty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("brief fields must not be empty")
        return value


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    objective: str
    deliverable: str
    scope: list[str]
    constraints: list[str]
    questions: list[Clarification] = Field(default_factory=list)

    @field_validator("objective", "deliverable")
    @classmethod
    def non_empty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("brief fields must not be empty")
        return value

    @field_validator("scope", "constraints")
    @classmethod
    def non_empty_list(cls, value):
        if not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("brief list fields must contain non-empty strings")
        return [item.strip() for item in value]

    @field_validator("questions")
    @classmethod
    def limited_questions(cls, value):
        if len(value) > 3:
            raise ValueError("brief has at most three clarification questions")
        return value


class PrepareResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["answer", "research"]
    brief: ResearchBrief | None

    @model_validator(mode="after")
    def matching_brief(self):
        if self.action == "research" and self.brief is None:
            raise ValueError("research requires a brief")
        if self.action == "answer" and self.brief is not None:
            raise ValueError("answer must not include a brief")
        return self


def parse_prepare_response(text):
    try:
        return PrepareResponse.model_validate(object_from_text(text))
    except (ValidationError, ValueError, TypeError) as error:
        raise ValueError("preparation model returned an invalid decision") from error


def prepare_system(system):
    if isinstance(system, list):
        return [*system, PREPARE_SYSTEM]
    return f"{system}\n\n{PREPARE_SYSTEM}" if system else PREPARE_SYSTEM


@router.post("/api/research/prepare", response_model=PrepareResponse)
async def research_prepare(req: "PrepareRequest", _=Depends(require_auth)):
    try:
        text = await complete_messages(req.model or DEFAULT_MODEL, prepare_system(req.system), [message.model_dump() for message in req.messages], max_tokens=1400)
        return parse_prepare_response(text)
    except ValueError as error:
        raise HTTPException(502, {"code": "research_prepare_failed", "message": str(error)}) from error
    except Exception as error:
        # Provider messages include actionable auth, quota, and model details.
        raise HTTPException(502, {"code": "research_prepare_failed", "message": str(error)}) from error


class PrepareRequest(BaseModel):
    messages: list[Msg]
    system: str | list[str] | None = None
    model: str | None = None


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    brief: ResearchBrief | None = None
    goal: str | None = None
    title: str | None = None
    models: dict[str, str]
    answers: dict[str, str]
    depth: int = runs.DEFAULT_RESEARCH_DEPTH
    min_sources: int = runs.DEFAULT_MIN_SOURCES
    max_sources: int = runs.DEFAULT_MAX_SOURCES
    prompts: dict[str, str] | None = None
    checkpoint: dict | None = None
    restart_failed: bool = False

    @field_validator("models")
    @classmethod
    def research_models(cls, value):
        if set(value) != {"search", "note", "report"} or any(not isinstance(model, str) or not model.strip() for model in value.values()):
            raise ValueError("models must contain non-empty search, note, and report IDs")
        return {role: model.strip() for role, model in value.items()}

    @field_validator("answers")
    @classmethod
    def non_empty_answers(cls, value):
        if any(not isinstance(key, str) or not key.strip() or not isinstance(answer, str) or not answer.strip() for key, answer in value.items()):
            raise ValueError("answers must have non-empty string keys and values")
        return {key.strip(): answer.strip() for key, answer in value.items()}

    @model_validator(mode="after")
    def require_brief(self):
        if self.brief is None and not self.goal:
            raise ValueError("brief is required")
        return self


@router.post("/api/research")
async def research_start(req: ResearchRequest, _=Depends(require_auth)):
    try:
        checkpoint_data = validate_checkpoint(req.checkpoint) if req.checkpoint is not None else None
        brief = req.brief.model_dump() if req.brief else {"objective": req.goal, "deliverable": "A sourced research brief", "scope": ["The requested subject"], "constraints": ["Use current public sources"], "questions": []}
        brief["answers"] = req.answers
        min_sources = max(8, min(req.min_sources, 300))
        max_sources = max(min_sources, min(req.max_sources, 300))
        run, outcome = runs.start(
            brief,
            req.models,
            depth=max(1, min(req.depth, 12)),
            title=req.title,
            prompts=req.prompts,
            run_id=req.id,
            checkpoint_data=checkpoint_data,
            restart_failed=req.restart_failed,
            min_sources=min_sources,
            max_sources=max_sources,
        )
    except runs.RunLimitError as error:
        raise HTTPException(429, {"code": "too_many_runs", "message": str(error)}) from error
    except ValueError as error:
        raise HTTPException(400, {"code": "invalid_checkpoint", "message": str(error)}) from error
    return {"id": run.id, "outcome": outcome, "resumed": outcome != "created", "status": run.status, "phase": run.phase, "revision": run.data.get("revision", 0), "checkpoint": run.data, "payload": run.payload}


@router.get("/api/research/{run_id}")
async def research_state(run_id: str, after: int = 0, _=Depends(require_auth)):
    runs.evict()
    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, {"code": "no_such_run", "message": "no such run, or it ended before you came back"})
    return run.state(after)


@router.get("/api/research/{run_id}/stream")
async def research_stream(run_id: str, after: int = 0, _=Depends(require_auth)):
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
            yield sse(kind="tick", phase=run.phase, revision=run.data.get("revision", 0), spend=run.spend.as_dict())
            await asyncio.sleep(1)

    return StreamingResponse(tail(), media_type="text/event-stream")


@router.delete("/api/research/{run_id}")
async def research_discard(run_id: str, _=Depends(require_auth)):
    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, {"code": "no_such_run", "message": "no such run"})
    if run.status == "running":
        if run.task:
            run.task.cancel()
        return {"status": "cancelling"}
    runs.forget(run_id)
    return {"status": "forgotten"}


@router.post("/api/research/{run_id}/ack")
async def research_ack(run_id: str, _=Depends(require_auth)):
    run = runs.RUNS.get(run_id)
    if not run:
        return {"status": "already_removed"}
    if run.status == "running":
        raise HTTPException(400, {"code": "run_still_active", "message": "cannot ack an active run"})
    runs.forget(run_id)
    return {"status": "acknowledged"}

