import asyncio
import hmac
import json
import logging
import os
import secrets
import time

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import fetcher
import research
from llm import (
    CONFIG_ERRORS, DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE,
    DEFAULT_UTILITY_MODEL, EFFORT_VALUES, MODELS, OPENAI_REASONING_PREFIXES, OPENAI_WEB_SEARCH,
    WEB_FETCH_BETA, WEB_FETCH_TOOL, WEB_SEARCH_TOOL, apply_thinking, client, field, openai_client,
    split_model,
)

load_dotenv()

APP_PASSWORD = os.environ.get("APP_PASSWORD")
# Signing key for session tokens.
# If unset, generate a random one per process: secure by default, though restarting logs everyone out.
# Set it to persist sessions.
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
TOKEN_TTL = int(os.environ.get("TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))

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


def mint_token():
    # iat lets the client compute the half-life for sliding renewal.
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + TOKEN_TTL}, JWT_SECRET, algorithm="HS256")


def require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    try:
        jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:  # covers expired and tampered tokens
        raise HTTPException(401, "invalid or expired token")


class LoginBody(BaseModel):
    password: str


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


@app.post("/api/login")
def login(body: LoginBody):
    # Single shared secret, constant-time compare.
    # Add a per-IP attempt limiter here if brute force becomes a concern.
    if not APP_PASSWORD:
        raise HTTPException(503, "server password not configured")
    if not hmac.compare_digest(body.password, APP_PASSWORD):  # constant-time
        raise HTTPException(401, "bad password")
    return {"token": mint_token()}


@app.post("/api/refresh")
def refresh(_=Depends(require_auth)):
    # Sliding session: any still-valid token can be traded for a fresh full-TTL one.
    return {"token": mint_token()}


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


@app.post("/api/research/clarify")
async def research_clarify(req: ClarifyRequest, _=Depends(require_auth)):
    research.evict()
    return {"questions": await research.clarify(req.brief, req.model or DEFAULT_MODEL)}


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
    run = research.start(req.brief, req.models, depth=max(1, min(req.depth, 12)), title=req.title)
    return {"id": run.id}


@app.get("/api/research/{run_id}")
async def research_state(run_id: str, after: int = 0, _=Depends(require_auth)):
    research.evict()
    run = research.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "no such run, or it ended before you came back")
    return run.state(after)


@app.get("/api/research/{run_id}/stream")
async def research_stream(run_id: str, after: int = 0, _=Depends(require_auth)):
    """Replay this run's events from `after`, then tail it live until it finishes.

    Reconnecting with the last seq you saw is lossless, because the events are a list rather than a broadcast.
    """

    run = research.RUNS.get(run_id)
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
    run = research.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    if run.status == "running":
        if run.task:
            run.task.cancel()
        return {"status": "cancelling"}
    research.forget(run_id)
    return {"status": "forgotten"}


@app.post("/api/fetch")
async def fetch_url(req: FetchRequest, _=Depends(require_auth)):
    # Every FetchError is about the URL the caller supplied, blocked targets included, so it maps to 400 with the reason.
    try:
        return await fetcher.fetch(req.url, req.topic)
    except fetcher.FetchError as e:
        raise HTTPException(400, str(e))


def sse(**payload):
    # json-encode each chunk so newlines/special chars can't break SSE framing.
    return f"data: {json.dumps(payload)}\n\n"


def system_param(system):
    """Anthropic `system` field, as a string or as cached blocks.

    A list is [stable, volatile]: the workspace prompt and docs, then memory, recall and cards.
    Marking the first block ephemeral caches it, so a large workspace is billed once per cache window rather than per turn.
    A block under the API's ~1024-token minimum stays uncached, silently and at list price.
    """
    if isinstance(system, list):
        return [
            {"type": "text", "text": s, **({"cache_control": {"type": "ephemeral"}} if i == 0 else {})}
            for i, s in enumerate(system)
            if s
        ]
    return system


async def anthropic_stream(model, messages, system, max_tokens, effort, temperature):
    kwargs = dict(model=model, max_tokens=max_tokens, temperature=temperature, messages=messages)
    apply_thinking(kwargs, effort, max_tokens)
    if system:
        kwargs["system"] = system_param(system)
    tools = []
    if WEB_SEARCH_TOOL:
        tools.append({"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": 5})
    if WEB_FETCH_TOOL:
        tools.append({"type": WEB_FETCH_TOOL, "name": "web_fetch", "max_uses": 5})
        kwargs["extra_headers"] = {"anthropic-beta": WEB_FETCH_BETA}
    if tools:
        kwargs["tools"] = tools
    try:
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    d = event.delta
                    if d.type == "text_delta":
                        yield sse(text=d.text)
                    elif d.type == "thinking_delta":  # extended-thinking models
                        yield sse(think=d.thinking)
                # server-side web search: content_block_stop carries the finalized block
                elif event.type == "content_block_stop":
                    block = event.content_block
                    if getattr(block, "type", "") == "server_tool_use":
                        if getattr(block, "name", "") == "web_fetch":
                            yield sse(fetch=block.input.get("url"))
                        else:
                            yield sse(search=block.input.get("query"))
                    elif getattr(block, "type", "") == "web_search_tool_result" and isinstance(block.content, list):
                        links = [{"title": getattr(r, "title", None), "url": getattr(r, "url", None)}
                                 for r in block.content if getattr(r, "type", "") == "web_search_result"]
                        if links:
                            yield sse(results=links)
        yield sse(done=True)
    except Exception as e:  # surface API errors to the client instead of a dead stream
        yield sse(error=str(e))


async def openai_stream(model, messages, system, max_tokens, effort, temperature):
    """Emits the same SSE frames as anthropic_stream, so api.js handles both alike."""
    kwargs = dict(model=model, input=messages, max_output_tokens=max_tokens, stream=True)
    if system:
        # The Responses API's system-prompt slot takes one string, and OpenAI caches long prefixes on its own.
        kwargs["instructions"] = "\n\n".join(system) if isinstance(system, list) else system
    if model.startswith(OPENAI_REASONING_PREFIXES):
        if effort:
            # summary="auto" mirrors Anthropic's display="summarized": it is what makes reasoning text stream at all.
            # The trace can still come out empty, because effort is a hint.
            # Verified against the API: at "low" with a short system prompt, gpt-5.6 often returns no reasoning item, while "high" reasons reliably.
            # An empty trace on an easy turn is the model's call.
            kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
    else:
        kwargs["temperature"] = temperature  # reasoning models reject it
    if OPENAI_WEB_SEARCH:
        kwargs["tools"] = [{"type": OPENAI_WEB_SEARCH}]
    try:
        stream = await openai_client.responses.create(**kwargs)
        async for event in stream:
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                yield sse(text=event.delta)
            elif etype == "response.reasoning_summary_text.delta":
                yield sse(think=event.delta)
            elif etype == "response.output_item.done":
                action = field(event.item, "action") if field(event.item, "type") == "web_search_call" else None
                if action is not None:
                    if field(action, "type") == "open_page":
                        yield sse(fetch=field(action, "url"))
                    elif field(action, "query"):
                        yield sse(search=field(action, "query"))
            elif etype == "response.output_text.annotation.added":
                a = field(event, "annotation")
                if field(a, "type") == "url_citation":
                    # One citation per frame, where Anthropic batches them, so the trace shows more and smaller groups.
                    # Buffer here if that reads noisy.
                    yield sse(results=[{"title": field(a, "title"), "url": field(a, "url")}])
            elif etype == "error":
                yield sse(error=str(field(event, "message") or event))
        yield sse(done=True)
    except Exception as e:
        yield sse(error=str(e))


@app.post("/api/chat")
async def chat(req: ChatRequest, _=Depends(require_auth)):
    provider, model = split_model(req.model or DEFAULT_MODEL)
    max_tokens = req.max_tokens or DEFAULT_MAX_TOKENS
    effort = req.effort if req.effort is not None else DEFAULT_EFFORT
    if effort and effort not in EFFORT_VALUES:
        raise HTTPException(400, f"unknown effort level: {effort}")
    args = (
        model,
        [m.model_dump() for m in req.messages],
        req.system,
        max_tokens,
        effort,
        req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE,
    )
    if provider == "anthropic":
        if client is None:
            raise HTTPException(503, "server ANTHROPIC_API_KEY not configured")
        gen = anthropic_stream(*args)
    elif provider == "openai":
        if openai_client is None:
            raise HTTPException(503, "server OPENAI_API_KEY not configured")
        gen = openai_stream(*args)
    else:
        raise HTTPException(400, f"unknown provider: {provider}")
    return StreamingResponse(gen, media_type="text/event-stream")


# Serve the built SPA in production (same origin, so no CORS needed).
# API lives under /api.
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":  # self-check: python main.py (uvicorn imports app, never runs this)
    # system_param: a plain string passes through.
    # [stable, volatile] becomes blocks carrying cache_control on the first only, and an empty half is dropped.
    assert system_param("just a string") == "just a string"
    _b = system_param(["stable", "volatile"])
    assert _b[0] == {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}}, _b
    assert _b[1] == {"type": "text", "text": "volatile"}, _b
    assert [b["text"] for b in system_param(["stable", ""])] == ["stable"], "empty half dropped"

    # field() reads SDK objects and plain dicts alike, and returns None on a shape it doesn't recognise instead of raising mid-stream.
    class _Obj:
        type = "url_citation"
    assert field({"type": "url_citation"}, "type") == "url_citation"
    assert field(_Obj(), "type") == "url_citation"
    assert field({"a": 1}, "missing") is None and field(_Obj(), "missing") is None

    print("selfcheck OK")
