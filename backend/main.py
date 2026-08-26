import asyncio
import json
from collections.abc import AsyncIterable, AsyncIterator
import logging
import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import fetcher
import research
import runs
from auth import require_auth, router as auth_router
from providers import (
    CONFIG_ERRORS, DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE,
    DEFAULT_UTILITY_MODEL, EFFORT_VALUES, MODELS, resolve_model, stream_chat,
)

load_dotenv()

DEFAULT_NUM_MESSAGES = int(os.environ.get("DEFAULT_NUM_MESSAGES", "20"))
DEFAULT_SEND_SYSTEM = os.environ.get("DEFAULT_SEND_SYSTEM_PROMPT", "true").lower() == "true"
DEFAULT_USE_MEMORY = os.environ.get("DEFAULT_USE_MEMORY", "false").lower() == "true"
DEFAULT_SUMMARIZE_N = int(os.environ.get("DEFAULT_SUMMARIZE_N", "20"))
DEFAULT_USE_RECALL = os.environ.get("DEFAULT_USE_RECALL", "false").lower() == "true"
# Prompt caching, off by default.
# A write costs 1.25x and the entry expires in minutes, so it pays back only in a conversation you keep sending to.
# It also needs a workspace prompt or docs large enough to clear the ~1024-token minimum.
DEFAULT_USE_CACHE = os.environ.get("DEFAULT_USE_CACHE", "false").lower() == "true"
app = FastAPI(title="conversa")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)


class Msg(BaseModel):
    role: str  # user | assistant (system goes in the top-level `system` field)
    content: str


class ChatRequest(BaseModel):
    messages: list[Msg]
    # A list is [stable, volatile] from buildPayload: the stable half gets cached.
    system: str | list[str] | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    effort: str | None = None  # "" | low | medium | high; empty/None = thinking off


@app.get("/api/settings")
def settings(_=Depends(require_auth)):
    return {
        "model": DEFAULT_MODEL,
        "temperature": DEFAULT_TEMPERATURE,
        "num_messages_to_send": DEFAULT_NUM_MESSAGES,
        "send_system_prompt": DEFAULT_SEND_SYSTEM,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "effort": DEFAULT_EFFORT,
        "utility_model": DEFAULT_UTILITY_MODEL,
        "use_memory": DEFAULT_USE_MEMORY,
        "summarize_n": DEFAULT_SUMMARIZE_N,
        "use_recall": DEFAULT_USE_RECALL,
        "use_cache": DEFAULT_USE_CACHE,
        "research_search_model": os.environ.get("DEFAULT_RESEARCH_SEARCH_MODEL", DEFAULT_MODEL),
        "research_note_model": os.environ.get("DEFAULT_RESEARCH_NOTE_MODEL", DEFAULT_UTILITY_MODEL),
        "research_report_model": os.environ.get("DEFAULT_RESEARCH_REPORT_MODEL", DEFAULT_MODEL),
        "research_depth": int(os.environ.get("DEFAULT_RESEARCH_DEPTH", "5")),
        # Not a setting: server-side config problems for the UI to surface.
        # App.vue strips this before the rest is merged into globalSettings.
        "config_errors": CONFIG_ERRORS,
    }


@app.get("/api/models")
def models(_=Depends(require_auth)):
    return MODELS


class FetchRequest(BaseModel):
    url: str
    topic: str | None = None  # returns the sections answering it, not the page head


class ClarifyRequest(BaseModel):
    brief: str
    model: str | None = None
    context: str | None = None  # bounded conversation excerpt; resolves pronouns and prior decisions


@app.post("/api/research/clarify")
async def research_clarify(req: ClarifyRequest, _=Depends(require_auth)):
    runs.evict()
    return {"questions": await research.clarify(req.brief, req.model or DEFAULT_MODEL, context=req.context)}


class ResearchRequest(BaseModel):
    brief: str
    title: str | None = None  # the question as asked, without the clarifying exchange
    models: dict[str, str]  # search | note | report -> model id
    depth: int = 6  # sources per subquestion
    prompts: dict[str, str] | None = None  # per-run overrides of research.PROMPTS


@app.post("/api/research")
async def research_start(req: ResearchRequest, _=Depends(require_auth)):

    if req.prompts:
        research.PROMPTS.update({k: v for k, v in req.prompts.items() if k in research.PROMPTS})
    run = runs.start(req.brief, req.models, depth=max(1, min(req.depth, 12)), title=req.title)
    return {"id": run.id}


@app.get("/api/research/{run_id}")
async def research_state(run_id: str, after: int = 0, _=Depends(require_auth)):
    runs.evict()
    run = runs.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "no such run, or it ended before you came back")
    return run.state(after)


@app.get("/api/research/{run_id}/stream")
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


@app.delete("/api/research/{run_id}")
async def research_discard(run_id: str, _=Depends(require_auth)):
    """Done with this run.

    Running means cancel, and the run stays so the stream can deliver its final frame.
    Finished means forget, which is what the client calls once it has saved the payload into a workspace.
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


@app.post("/api/fetch")
async def fetch_url(req: FetchRequest, _=Depends(require_auth)):
    # Every FetchError is about the URL the caller supplied, blocked targets included, so it maps to 400 with the reason.
    try:
        return await fetcher.fetch(req.url, req.topic)
    except fetcher.FetchError as e:
        raise HTTPException(400, str(e))


def sse(**payload: object) -> str:
    # json-encode each chunk so newlines/special chars can't break SSE framing.
    return f"data: {json.dumps(payload)}\n\n"


async def sse_stream(events: AsyncIterable[dict]) -> AsyncIterator[str]:
    async for payload in events:
        yield sse(**payload)


@app.post("/api/chat")
async def chat(req: ChatRequest, _=Depends(require_auth)):
    max_tokens = req.max_tokens or DEFAULT_MAX_TOKENS
    effort = req.effort if req.effort is not None else DEFAULT_EFFORT
    if effort and effort not in EFFORT_VALUES:
        raise HTTPException(400, f"unknown effort level: {effort}")
    try:
        provider, model = resolve_model(req.model or DEFAULT_MODEL)
    except LookupError as error:
        raise HTTPException(400, str(error))
    except RuntimeError as error:
        raise HTTPException(503, str(error))
    events = stream_chat(
        provider,
        model,
        [message.model_dump() for message in req.messages],
        req.system,
        max_tokens,
        effort,
        req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE,
    )
    return StreamingResponse(sse_stream(events), media_type="text/event-stream")


# Serve the built SPA in production (same origin, so no CORS needed).
# API lives under /api.
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":  # self-check: python main.py (uvicorn imports app, never runs this)
    assert sse(text="a\nb") == 'data: {"text": "a\\nb"}\n\n'
    print("selfcheck OK")
