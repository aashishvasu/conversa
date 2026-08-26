import asyncio
import json
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
    CLIENTS, CONFIG_ERRORS, DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE,
    DEFAULT_UTILITY_MODEL, EFFORT_VALUES, MODELS, PROVIDERS, WEB_FETCH_BETA, WEB_FETCH_TOOL,
    WEB_SEARCH_TOOL, apply_thinking, chat_completions_kwargs, field, join_system, split_model,
    takes_reasoning,
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


@app.post("/api/research/clarify")
async def research_clarify(req: ClarifyRequest, _=Depends(require_auth)):
    runs.evict()
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


async def anthropic_stream(provider, model, messages, system, max_tokens, effort, temperature):
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
        async with CLIENTS[provider].messages.stream(**kwargs) as stream:
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


async def responses_stream(provider, model, messages, system, max_tokens, effort, temperature):
    """Emits the same SSE frames as anthropic_stream, so api.js handles both alike.

    Serves OpenAI and every provider that implements the Responses API, DeepSeek included.
    """
    kwargs = dict(model=model, input=messages, max_output_tokens=max_tokens, stream=True)
    if system:
        # The Responses API's system-prompt slot takes one string, and the server caches long prefixes on its own.
        kwargs["instructions"] = join_system(system)
    if takes_reasoning(provider, model):
        if effort:
            # summary="auto" mirrors Anthropic's display="summarized": it is what makes reasoning text stream at all.
            # The trace can still come out empty, because effort is a hint.
            # Verified against the API: at "low" with a short system prompt, gpt-5.6 often returns no reasoning item, while "high" reasons reliably.
            # An empty trace on an easy turn is the model's call.
            kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
    else:
        kwargs["temperature"] = temperature  # reasoning models reject it
    search_tool = PROVIDERS[provider].get("search_tool")
    if search_tool:
        kwargs["tools"] = [{"type": search_tool}]
    try:
        stream = await CLIENTS[provider].responses.create(**kwargs)
        async for event in stream:
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                yield sse(text=event.delta)
            # OpenAI streams a summary of its reasoning; DeepSeek streams the chain itself and generates no summary.
            elif etype in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
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


async def chat_completions_stream(provider, model, messages, system, max_tokens, effort, temperature):
    """Emits the same SSE frames as anthropic_stream, for a provider that serves chat.completions only.

    No hosted tools and no thinking lever on this dialect: `search`, `fetch` and `results` frames never
    appear, and thinking depth is whatever the model id implies.
    """
    kwargs = chat_completions_kwargs(model, messages, system, max_tokens, temperature)
    try:
        stream = await CLIENTS[provider].chat.completions.create(stream=True, **kwargs)
        async for chunk in stream:
            if not chunk.choices:  # a usage-only final chunk carries no choices
                continue
            delta = chunk.choices[0].delta
            # DeepSeek and Moonshot both stream thinking on reasoning_content, beside the standard content field.
            think = field(delta, "reasoning_content")
            if think:
                yield sse(think=think)
            text = field(delta, "content")
            if text:
                yield sse(text=text)
        yield sse(done=True)
    except Exception as e:
        yield sse(error=str(e))


# One generator per wire protocol, which is the whole of what a dialect is.
DIALECT_STREAMS = {
    "anthropic": anthropic_stream,
    "responses": responses_stream,
    "chat_completions": chat_completions_stream,
}


@app.post("/api/chat")
async def chat(req: ChatRequest, _=Depends(require_auth)):
    provider, model = split_model(req.model or DEFAULT_MODEL)
    max_tokens = req.max_tokens or DEFAULT_MAX_TOKENS
    effort = req.effort if req.effort is not None else DEFAULT_EFFORT
    if effort and effort not in EFFORT_VALUES:
        raise HTTPException(400, f"unknown effort level: {effort}")
    entry = PROVIDERS.get(provider)
    if entry is None:
        raise HTTPException(400, f"unknown provider: {provider}")
    if CLIENTS[provider] is None:
        raise HTTPException(503, f"server {entry['key_env']} not configured")
    gen = DIALECT_STREAMS[entry["dialect"]](
        provider,
        model,
        [m.model_dump() for m in req.messages],
        req.system,
        max_tokens,
        effort,
        req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE,
    )
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

    print("selfcheck OK")
