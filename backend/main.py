import hmac
import json
import logging
import os
import secrets
import time

import jwt
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
# Signing key for session tokens. If unset, generate a random one per process: secure
# by default, though restarting logs everyone out. Set it to persist sessions.
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
TOKEN_TTL = int(os.environ.get("TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-sonnet-5")
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "1.0"))
DEFAULT_NUM_MESSAGES = int(os.environ.get("DEFAULT_NUM_MESSAGES", "20"))
DEFAULT_SEND_SYSTEM = os.environ.get("DEFAULT_SEND_SYSTEM_PROMPT", "true").lower() == "true"
DEFAULT_MAX_TOKENS = int(os.environ.get("DEFAULT_MAX_TOKENS", "4096"))
# Thinking effort: "" (off), "low", "medium", "high". See apply_thinking() for how it
# reaches the API. The wire format differs between model generations.
DEFAULT_EFFORT = os.environ.get("DEFAULT_EFFORT", "")
# Cheap model for auxiliary tasks: title generation and history compression.
DEFAULT_UTILITY_MODEL = os.environ.get("DEFAULT_UTILITY_MODEL", "claude-haiku-4-5")
DEFAULT_USE_MEMORY = os.environ.get("DEFAULT_USE_MEMORY", "false").lower() == "true"
DEFAULT_SUMMARIZE_N = int(os.environ.get("DEFAULT_SUMMARIZE_N", "20"))
DEFAULT_USE_RECALL = os.environ.get("DEFAULT_USE_RECALL", "false").lower() == "true"
# Anthropic's server-side web search tool. Model-invoked: it searches only when a message warrants it.
WEB_SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL_VERSION", "web_search_20250305")
# Server-side web fetch tool (lets the model open a URL the user pastes). Beta-gated.
WEB_FETCH_TOOL = os.environ.get("WEB_FETCH_TOOL_VERSION", "web_fetch_20250910")
WEB_FETCH_BETA = os.environ.get("WEB_FETCH_BETA", "web-fetch-2025-09-10")
# OpenAI's hosted search tool. One tool covers both searching and opening pages, so it
# stands in for WEB_SEARCH_TOOL and WEB_FETCH_TOOL together. Empty disables it.
OPENAI_WEB_SEARCH = os.environ.get("OPENAI_WEB_SEARCH_TOOL", "web_search")

# Models predating adaptive thinking (pre-4.6). They take the old fixed-token-budget
# form, reject output_config.effort, and accept temperature. Everything newer takes the
# modern form. Unknown ids are assumed modern, the direction the API moved.
# Hand-maintained: add an id here if you expose an older model via MODELS.
LEGACY_MODELS = {
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-sonnet-4-0",
    "claude-opus-4-0",
    "claude-3-haiku-20240307",
}

# Fixed budgets the effort levels map to on legacy models. Modern models get the
# qualitative effort string instead and size their own thinking.
LEGACY_EFFORT_BUDGETS = {"low": 4000, "medium": 10000, "high": 24000}

# The effort vocabulary the frontend offers (store.js EFFORT_LEVELS). Anthropic takes it
# as output_config.effort, OpenAI as reasoning.effort. Both use these three words, so the
# lever needs no per-provider translation.
EFFORT_VALUES = ("low", "medium", "high")

# OpenAI reasoning models take reasoning.effort and reject temperature; older chat models
# are the inverse. Prefix match, hand-maintained like LEGACY_MODELS above.
OPENAI_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def apply_thinking(kwargs, effort, max_tokens):
    """Attach thinking config for `effort` ("", low, medium, high) to an API kwargs dict.

    Modern models (4.6+): adaptive thinking + output_config.effort, and no sampling
    params at all, since Opus 4.7+ reject `temperature` whether or not thinking is on.
    Legacy models: the pre-4.6 fixed budget, which requires budget < max_tokens and
    also drops temperature. Mutates and returns kwargs.
    """
    legacy = kwargs["model"] in LEGACY_MODELS
    if not legacy:
        # Rejected on Opus 4.7/4.8 even with thinking off, so this is unconditional.
        kwargs.pop("temperature", None)
    if not effort:
        return kwargs
    if legacy:
        budget = LEGACY_EFFORT_BUDGETS[effort]
        kwargs["max_tokens"] = max(max_tokens, budget + DEFAULT_MAX_TOKENS)
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        kwargs.pop("temperature", None)
    else:
        # display=summarized: the default is "omitted", which streams empty thinking
        # blocks and would blank the live trace in ChatPane.
        kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        kwargs["output_config"] = {"effort": effort}
        # Thinking spends from max_tokens, so a 4096 cap can be consumed entirely by it.
        kwargs["max_tokens"] = max(max_tokens, 32000)
    return kwargs


# Selectable models, labelled. Format: "provider/id:Label,id2:Label2" (label optional,
# provider optional). Built-ins are always offered; MODELS env appends extra ids. First
# occurrence of an id wins.
BUILTIN_MODELS = (
    "claude-fable-5:Fable 5,"
    "claude-opus-5:Opus 5,claude-sonnet-5:Sonnet 5,claude-opus-4-8:Opus 4.8,"
    "claude-sonnet-4-6:Sonnet 4.6,claude-haiku-4-5:Haiku 4.5,"
    "openai/gpt-5.6-sol:GPT-5.6 Sol,openai/gpt-5.6-terra:GPT-5.6 Terra,"
    "openai/gpt-5.6-luna:GPT-5.6 Luna,openai/gpt-5.5:GPT-5.5,"
    "openai/gpt-5-mini:GPT-5 Mini"
)


def split_model(mid):
    """"openai/gpt-5.6" -> ("openai", "gpt-5.6"); a bare id -> ("anthropic", id).

    Unprefixed means Anthropic permanently, the way a bare Docker image name means
    docker.io. Conversations saved before OpenAI support hold bare ids in IndexedDB and
    .env files still use them, so this stays true rather than becoming a migration step.
    rpartition, so a model id that itself contains a slash splits at the last one.
    """
    provider, _, name = mid.rpartition("/")
    return (provider or "anthropic"), name


def parse_models(raw):
    out, seen = [], set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        mid, _, label = entry.partition(":")
        mid = mid.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append({"id": mid, "label": label.strip() or mid, "provider": split_model(mid)[0]})
    return out


CONFIGURED = {p for p, key in (("anthropic", API_KEY), ("openai", OPENAI_API_KEY)) if key}

ALL_MODELS = parse_models(BUILTIN_MODELS + "," + os.environ.get("MODELS", ""))
# Only offer what we hold a key for: an unusable option in the dropdown fails as a bare
# 503 on send, and silently (swallowed) when it's the utility model.
MODELS = [m for m in ALL_MODELS if m["provider"] in CONFIGURED]

# Config problems downgrade the app and let it start: with one key missing the other
# provider still works. These ride along on /api/settings so the UI can name the cause of
# a missing model, which a startup crash or a bare 503 on send both fail to do.
CONFIG_ERRORS = []


def _config_error(msg):
    CONFIG_ERRORS.append(msg)
    logging.warning(msg)


_dropped = [m["id"] for m in ALL_MODELS if m["provider"] not in CONFIGURED]
if _dropped:
    _missing = sorted({split_model(i)[0] for i in _dropped})
    _config_error(
        f"No API key for {', '.join(_missing)}. Hidden from the model list: {', '.join(_dropped)}"
    )
for _name, _mid in (("DEFAULT_MODEL", DEFAULT_MODEL), ("DEFAULT_UTILITY_MODEL", DEFAULT_UTILITY_MODEL)):
    if not any(m["id"] == _mid for m in MODELS):
        _config_error(f"{_name}={_mid} is not selectable (no API key for it, or not in MODELS)")

client = AsyncAnthropic(api_key=API_KEY) if API_KEY else None
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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
    system: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    effort: str | None = None  # "" | low | medium | high; empty/None = thinking off


@app.post("/api/login")
def login(body: LoginBody):
    # Single shared secret, constant-time compare. Add a per-IP attempt limiter
    # here if brute force becomes a concern.
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
        # Not a setting: server-side config problems for the UI to surface. App.vue
        # strips this before the rest is merged into globalSettings.
        "config_errors": CONFIG_ERRORS,
    }


@app.get("/api/models")
def models(_=Depends(require_auth)):
    return MODELS


def sse(**payload):
    # json-encode each chunk so newlines/special chars can't break SSE framing.
    return f"data: {json.dumps(payload)}\n\n"


def field(obj, name):
    """Read a field off an SDK model or a plain dict.

    OpenAI annotation and action shapes vary between SDK versions. On a shape this
    doesn't recognise it returns None, which costs one trace event and leaves the
    stream running.
    """
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


async def anthropic_stream(model, messages, system, max_tokens, effort, temperature):
    kwargs = dict(model=model, max_tokens=max_tokens, temperature=temperature, messages=messages)
    apply_thinking(kwargs, effort, max_tokens)
    if system:
        kwargs["system"] = system
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
        kwargs["instructions"] = system  # the Responses API's system-prompt slot
    if model.startswith(OPENAI_REASONING_PREFIXES):
        if effort:
            # summary="auto" mirrors Anthropic's display="summarized": it is what makes
            # reasoning text stream at all. The trace can still come out empty, because
            # effort is a hint. Verified against the API: at "low" with a short system
            # prompt, gpt-5.6 often returns no reasoning item, while "high" reasons
            # reliably. An empty trace on an easy turn is the model's call.
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
                    # One citation per frame, where Anthropic batches them, so the trace
                    # shows more and smaller groups. Buffer here if that reads noisy.
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


# Serve the built SPA in production (same origin, so no CORS needed). API lives under /api.
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":  # self-check: python main.py (uvicorn imports app, never runs this)
    def _k(model, temperature=1.0):
        return {"model": model, "max_tokens": 4096, "temperature": temperature}

    # Modern model, thinking on: adaptive + effort, no temperature, roomier max_tokens.
    m = apply_thinking(_k("claude-opus-4-8"), "high", 4096)
    assert m["thinking"] == {"type": "adaptive", "display": "summarized"}, m
    assert m["output_config"] == {"effort": "high"}, m
    assert "temperature" not in m, m
    assert m["max_tokens"] == 32000, m

    # Modern model, thinking off: still no temperature (Opus 4.7/4.8 reject it outright).
    m = apply_thinking(_k("claude-opus-4-8"), "", 4096)
    assert "temperature" not in m and "thinking" not in m, m
    assert m["max_tokens"] == 4096, m

    # Legacy model: fixed budget, budget < max_tokens, temperature dropped only here.
    m = apply_thinking(_k("claude-haiku-4-5"), "medium", 4096)
    assert m["thinking"] == {"type": "enabled", "budget_tokens": 10000}, m
    assert m["max_tokens"] > m["thinking"]["budget_tokens"], m
    assert "output_config" not in m and "temperature" not in m, m

    # Legacy model, thinking off: temperature survives, since legacy models accept it.
    m = apply_thinking(_k("claude-haiku-4-5", temperature=0.3), "", 4096)
    assert m["temperature"] == 0.3, m
    assert "thinking" not in m, m

    # Unknown ids are treated as modern, not legacy.
    assert "output_config" in apply_thinking(_k("claude-future-9"), "low", 4096)

    # A bare id means Anthropic, permanently. Conversations saved before OpenAI support
    # hold bare ids, so this behaviour stays true for good.
    assert split_model("claude-opus-5") == ("anthropic", "claude-opus-5")
    assert split_model("openai/gpt-5.6") == ("openai", "gpt-5.6")
    # rpartition, so a provider id that itself contains a slash still splits at the last one.
    assert split_model("openai/ft:org/gpt-5.6") == ("openai/ft:org", "gpt-5.6")

    # parse_models: label optional, provider derived, first occurrence of an id wins.
    p = parse_models("claude-opus-5:Opus 5,openai/gpt-5.6:GPT,openai/gpt-5.6:dupe,bare-id")
    assert [m["id"] for m in p] == ["claude-opus-5", "openai/gpt-5.6", "bare-id"], p
    assert [m["provider"] for m in p] == ["anthropic", "openai", "anthropic"], p
    assert p[1]["label"] == "GPT" and p[2]["label"] == "bare-id", p

    # Models whose provider has no key are hidden rather than offered-then-503.
    _all = parse_models("claude-opus-5:Opus,openai/gpt-5.6:GPT")
    assert [m["id"] for m in _all if m["provider"] in {"anthropic"}] == ["claude-opus-5"], _all

    # Both providers share one effort vocabulary, so the lever needs no translation.
    assert set(EFFORT_VALUES) == set(LEGACY_EFFORT_BUDGETS), EFFORT_VALUES

    # field() reads SDK objects and plain dicts alike, and returns None on a shape it
    # doesn't recognise instead of raising mid-stream.
    class _Obj:
        type = "url_citation"
    assert field({"type": "url_citation"}, "type") == "url_citation"
    assert field(_Obj(), "type") == "url_citation"
    assert field({"a": 1}, "missing") is None and field(_Obj(), "missing") is None

    print("selfcheck OK")
