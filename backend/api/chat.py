"""Settings, models, and the chat completion stream."""

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import require_auth
from api.sse import sse_stream
from providers import (
    CONFIG_ERRORS, DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE,
    DEFAULT_UTILITY_MODEL, EFFORT_VALUES, MODELS, resolve_model, stream_chat,
)
from tools import ToolConfigError, resolve_enabled_tools

DEFAULT_NUM_MESSAGES = int(os.environ.get("DEFAULT_NUM_MESSAGES", "20"))
DEFAULT_SEND_SYSTEM = os.environ.get("DEFAULT_SEND_SYSTEM_PROMPT", "true").lower() == "true"
DEFAULT_USE_MEMORY = os.environ.get("DEFAULT_USE_MEMORY", "false").lower() == "true"
DEFAULT_SUMMARIZE_N = int(os.environ.get("DEFAULT_SUMMARIZE_N", "20"))
DEFAULT_USE_RECALL = os.environ.get("DEFAULT_USE_RECALL", "false").lower() == "true"
# Prompt caching, off by default.
# A write costs 1.25x and the entry expires in minutes, so it pays back only in a conversation you keep sending to.
# It also needs a workspace prompt or docs large enough to clear the ~1024-token minimum.
DEFAULT_USE_CACHE = os.environ.get("DEFAULT_USE_CACHE", "false").lower() == "true"
# Tool defaults: the master switch and each of the five tools, all on unless the operator turns one off.
DEFAULT_TOOLS_ENABLED = os.environ.get("DEFAULT_TOOLS_ENABLED", "true").lower() == "true"
DEFAULT_TOOL_WEB_SEARCH = os.environ.get("DEFAULT_TOOL_WEB_SEARCH", "true").lower() == "true"
DEFAULT_TOOL_FETCH_URL = os.environ.get("DEFAULT_TOOL_FETCH_URL", "true").lower() == "true"
DEFAULT_TOOL_DATETIME = os.environ.get("DEFAULT_TOOL_DATETIME", "true").lower() == "true"
DEFAULT_TOOL_CALCULATOR = os.environ.get("DEFAULT_TOOL_CALCULATOR", "true").lower() == "true"
DEFAULT_TOOL_RANDOM = os.environ.get("DEFAULT_TOOL_RANDOM", "true").lower() == "true"
DEFAULT_TOOL_MAX_ROUNDS = max(1, int(os.environ.get("DEFAULT_TOOL_MAX_ROUNDS", "4")))
DEFAULT_TOOL_MAX_CALLS = max(1, int(os.environ.get("DEFAULT_TOOL_MAX_CALLS", "16")))

router = APIRouter()


class TextBlock(BaseModel):
    type: Literal["text"]
    text: str


class ImageSource(BaseModel):
    type: Literal["base64"]
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str


class ImageBlock(BaseModel):
    type: Literal["image"]
    source: ImageSource


class Msg(BaseModel):
    role: str  # user | assistant (system goes in the top-level `system` field)
    content: str | list[TextBlock | ImageBlock]


class ChatRequest(BaseModel):
    messages: list[Msg]
    # A list is [stable, volatile] from buildPayload: the stable half gets cached.
    system: str | list[str] | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    effort: str | None = None  # "" | low | medium | high; empty/None = thinking off
    allow_tools: bool = False
    enabled_tools: list[str] | None = None
    tool_max_rounds: int | None = None
    tool_max_calls: int | None = None


@router.get("/api/settings")
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
        "tools_enabled": DEFAULT_TOOLS_ENABLED,
        "tool_web_search": DEFAULT_TOOL_WEB_SEARCH,
        "tool_fetch_url": DEFAULT_TOOL_FETCH_URL,
        "tool_datetime": DEFAULT_TOOL_DATETIME,
        "tool_calculator": DEFAULT_TOOL_CALCULATOR,
        "tool_random": DEFAULT_TOOL_RANDOM,
        "tool_max_rounds": DEFAULT_TOOL_MAX_ROUNDS,
        "tool_max_calls": DEFAULT_TOOL_MAX_CALLS,
        "research_search_model": os.environ.get("DEFAULT_RESEARCH_SEARCH_MODEL", DEFAULT_MODEL),
        "research_note_model": os.environ.get("DEFAULT_RESEARCH_NOTE_MODEL", DEFAULT_UTILITY_MODEL),
        "research_report_model": os.environ.get("DEFAULT_RESEARCH_REPORT_MODEL", DEFAULT_MODEL),
        "research_depth": int(os.environ.get("DEFAULT_RESEARCH_DEPTH", "5")),
        # Not a setting: server-side config problems for the UI to surface.
        # App.vue strips this before the rest is merged into globalSettings.
        "config_errors": CONFIG_ERRORS,
    }


@router.get("/api/models")
def models(_=Depends(require_auth)):
    return MODELS


@router.post("/api/chat")
async def chat(req: ChatRequest, _=Depends(require_auth)):
    max_tokens = req.max_tokens or DEFAULT_MAX_TOKENS
    effort = req.effort if req.effort is not None else DEFAULT_EFFORT
    if effort and effort not in EFFORT_VALUES:
        raise HTTPException(400, {"code": "unknown_effort", "message": f"unknown effort level: {effort}", "effort": effort})
    try:
        provider, model = resolve_model(req.model or DEFAULT_MODEL)
    except LookupError as error:
        raise HTTPException(400, {"code": "invalid_model", "message": str(error)})
    except RuntimeError as error:
        raise HTTPException(503, {"code": "provider_unavailable", "message": str(error)})
    try:
        selected_tools = resolve_enabled_tools(req.enabled_tools, req.allow_tools)
    except ToolConfigError as error:
        raise HTTPException(400, error.as_dict())
    events = stream_chat(
        provider,
        model,
        [message.model_dump() for message in req.messages],
        req.system,
        max_tokens,
        effort,
        req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE,
        tools=selected_tools if selected_tools else None,
        max_tool_rounds=req.tool_max_rounds or DEFAULT_TOOL_MAX_ROUNDS,
        max_tool_calls=req.tool_max_calls or DEFAULT_TOOL_MAX_CALLS,
        allow_hosted_tools=True,
    )
    return StreamingResponse(sse_stream(events), media_type="text/event-stream")
