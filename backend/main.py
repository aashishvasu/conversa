import hmac
import json
import os
import secrets
import time

import jwt
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
# Signing key for session tokens. If unset, generate a random one per process —
# secure by default, but restarting logs everyone out. Set it to persist sessions.
JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
TOKEN_TTL = int(os.environ.get("TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-sonnet-4-6")
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "1.0"))
DEFAULT_NUM_MESSAGES = int(os.environ.get("DEFAULT_NUM_MESSAGES", "20"))
DEFAULT_SEND_SYSTEM = os.environ.get("DEFAULT_SEND_SYSTEM_PROMPT", "true").lower() == "true"
DEFAULT_MAX_TOKENS = int(os.environ.get("DEFAULT_MAX_TOKENS", "4096"))
# Cheap model for auxiliary tasks: title generation and history compression.
DEFAULT_UTILITY_MODEL = os.environ.get("DEFAULT_UTILITY_MODEL", "claude-haiku-4-5")
DEFAULT_USE_MEMORY = os.environ.get("DEFAULT_USE_MEMORY", "false").lower() == "true"
DEFAULT_COMPRESSION_THRESHOLD = int(os.environ.get("DEFAULT_COMPRESSION_THRESHOLD", "4000"))
# Anthropic's server-side web search tool. Model-invoked: it searches only when a message warrants it.
WEB_SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL_VERSION", "web_search_20250305")

# Selectable models, labelled. Format: "id:Label,id2:Label2" (label optional).
MODELS_RAW = os.environ.get(
    "MODELS",
    "claude-sonnet-4-6:Sonnet 4.6,claude-opus-4-8:Opus 4.8,claude-haiku-4-5:Haiku 4.5",
)


def parse_models(raw):
    out = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        mid, _, label = entry.partition(":")
        out.append({"id": mid.strip(), "label": label.strip() or mid.strip()})
    return out


MODELS = parse_models(MODELS_RAW)

client = AsyncAnthropic(api_key=API_KEY) if API_KEY else None

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


@app.post("/api/login")
def login(body: LoginBody):
    # Single shared secret. Add a per-IP attempt limiter here if brute force is a
    # concern; behind HTTPS with a strong password it isn't, so it's omitted.
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
        "utility_model": DEFAULT_UTILITY_MODEL,
        "use_memory": DEFAULT_USE_MEMORY,
        "compression_threshold": DEFAULT_COMPRESSION_THRESHOLD,
    }


@app.get("/api/models")
def models(_=Depends(require_auth)):
    return MODELS


@app.post("/api/chat")
async def chat(req: ChatRequest, _=Depends(require_auth)):
    if client is None:
        raise HTTPException(503, "server API key not configured")

    kwargs = dict(
        model=req.model or DEFAULT_MODEL,
        max_tokens=req.max_tokens or DEFAULT_MAX_TOKENS,
        temperature=req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE,
        messages=[m.model_dump() for m in req.messages],
    )
    if req.system:
        kwargs["system"] = req.system
    if WEB_SEARCH_TOOL:
        kwargs["tools"] = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": 5}]

    async def gen():
        # json-encode each chunk so newlines/special chars can't break SSE framing.
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        d = event.delta
                        if d.type == "text_delta":
                            yield f"data: {json.dumps({'text': d.text})}\n\n"
                        elif d.type == "thinking_delta":  # extended-thinking models
                            yield f"data: {json.dumps({'think': d.thinking})}\n\n"
                    # server-side web search: content_block_stop carries the finalized block
                    elif event.type == "content_block_stop":
                        block = event.content_block
                        if getattr(block, "type", "") == "server_tool_use":
                            yield f"data: {json.dumps({'search': block.input.get('query')})}\n\n"
                        elif getattr(block, "type", "") == "web_search_tool_result" and isinstance(block.content, list):
                            links = [{"title": getattr(r, "title", None), "url": getattr(r, "url", None)}
                                     for r in block.content if getattr(r, "type", "") == "web_search_result"]
                            if links:
                                yield f"data: {json.dumps({'results': links})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:  # surface API errors to the client instead of a dead stream
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# Serve the built SPA in production (same origin → no CORS needed). API lives under /api.
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
