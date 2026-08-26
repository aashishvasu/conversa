"""The research run endpoints: clarify, start, state, stream, discard."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import require_auth
from api.sse import sse
from providers import DEFAULT_MODEL
from research import gather, runs

router = APIRouter()


class ClarifyRequest(BaseModel):
    brief: str
    model: str | None = None
    context: str | None = None  # bounded conversation excerpt; resolves pronouns and prior decisions


@router.post("/api/research/clarify")
async def research_clarify(req: ClarifyRequest, _=Depends(require_auth)):
    runs.evict()
    return {"questions": await gather.clarify(req.brief, req.model or DEFAULT_MODEL, context=req.context)}


class ResearchRequest(BaseModel):
    brief: str
    title: str | None = None  # the question as asked, without the clarifying exchange
    models: dict[str, str]  # search | note | report -> model id
    depth: int = 6  # sources per subquestion
    prompts: dict[str, str] | None = None  # per-run overrides of gather.PROMPTS


@router.post("/api/research")
async def research_start(req: ResearchRequest, _=Depends(require_auth)):
    if req.prompts:
        gather.PROMPTS.update({k: v for k, v in req.prompts.items() if k in gather.PROMPTS})
    run = runs.start(req.brief, req.models, depth=max(1, min(req.depth, 12)), title=req.title)
    return {"id": run.id}


@router.get("/api/research/{run_id}")
async def research_state(run_id: str, after: int = 0, _=Depends(require_auth)):
    runs.evict()
    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "no such run, or it ended before you came back")
    return run.state(after)


@router.get("/api/research/{run_id}/stream")
async def research_stream(run_id: str, after: int = 0, _=Depends(require_auth)):
    """Replay this run's events from `after`, then tail it live until it finishes.

    Reconnecting with the last seq you saw is lossless, because the events are a list rather than a broadcast.
    """

    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "no such run, or it ended before you came back")

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
        raise HTTPException(404, "no such run")
    if run.status == "running":
        if run.task:
            run.task.cancel()
        return {"status": "cancelling"}
    runs.forget(run_id)
    return {"status": "forgotten"}
