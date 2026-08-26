"""The three provider wire protocols, normalized to conversa event dictionaries."""

from collections.abc import AsyncIterator

from .anthropic import LEGACY_EFFORT_BUDGETS, LEGACY_MODELS
from .registry import (
    CLIENTS,
    DEFAULT_MAX_TOKENS,
    PROVIDERS,
    resolve_model,
)


def apply_thinking(kwargs: dict, effort: str, max_tokens: int) -> dict:
    """Attach Anthropic thinking config to a request kwargs dict."""
    legacy = kwargs["model"] in LEGACY_MODELS
    if not legacy:
        kwargs.pop("temperature", None)
    if not effort:
        return kwargs
    if legacy:
        budget = LEGACY_EFFORT_BUDGETS[effort]
        kwargs["max_tokens"] = max(max_tokens, budget + DEFAULT_MAX_TOKENS)
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        kwargs.pop("temperature", None)
    else:
        kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        kwargs["output_config"] = {"effort": effort}
        kwargs["max_tokens"] = max(max_tokens, 32000)
    return kwargs


def takes_reasoning(provider: str, model: str) -> bool:
    prefixes = PROVIDERS[provider].get("reasoning_prefixes")
    return model.startswith(prefixes) if prefixes else True


def join_system(system: str | list[str] | None) -> str | None:
    return "\n\n".join(part for part in system if part) if isinstance(system, list) else system


def anthropic_system(system: str | list[str] | None) -> str | list[dict] | None:
    """Convert [stable, volatile] into Anthropic blocks, caching the stable half."""
    if not isinstance(system, list):
        return system
    return [
        {"type": "text", "text": text, **({"cache_control": {"type": "ephemeral"}} if index == 0 else {})}
        for index, text in enumerate(system)
        if text
    ]


def chat_completions_kwargs(
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    temperature: float | None = None,
) -> dict:
    if system:
        messages = [{"role": "system", "content": join_system(system)}, *messages]
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return kwargs


def field(obj: object, name: str) -> object | None:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def anthropic_frame(event: object) -> dict | None:
    if event.type == "content_block_delta":
        if event.delta.type == "text_delta":
            return {"text": event.delta.text}
        if event.delta.type == "thinking_delta":
            return {"think": event.delta.thinking}
    if event.type != "content_block_stop":
        return None
    block = event.content_block
    if field(block, "type") == "server_tool_use":
        key = "fetch" if field(block, "name") == "web_fetch" else "search"
        value = field(block, "input").get("url" if key == "fetch" else "query")
        return {key: value}
    if field(block, "type") == "web_search_tool_result" and isinstance(field(block, "content"), list):
        links = [
            {"title": field(result, "title"), "url": field(result, "url")}
            for result in block.content
            if field(result, "type") == "web_search_result"
        ]
        return {"results": links} if links else None
    return None


def response_frame(event: object) -> dict | None:
    event_type = field(event, "type") or ""
    if event_type == "response.output_text.delta":
        return {"text": field(event, "delta")}
    if event_type in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
        return {"think": field(event, "delta")}
    if event_type == "response.output_item.done":
        item = field(event, "item")
        action = field(item, "action") if field(item, "type") == "web_search_call" else None
        if action is not None:
            if field(action, "type") == "open_page":
                return {"fetch": field(action, "url")}
            if field(action, "query"):
                return {"search": field(action, "query")}
    if event_type == "response.output_text.annotation.added":
        annotation = field(event, "annotation")
        if field(annotation, "type") == "url_citation":
            return {"results": [{"title": field(annotation, "title"), "url": field(annotation, "url")}]}
    if event_type == "error":
        return {"error": str(field(event, "message") or event)}
    return None


def chat_completion_frames(chunk: object) -> list[dict]:
    if not chunk.choices:
        return []
    delta = chunk.choices[0].delta
    frames = []
    if field(delta, "reasoning_content"):
        frames.append({"think": field(delta, "reasoning_content")})
    if field(delta, "content"):
        frames.append({"text": field(delta, "content")})
    return frames


async def _anthropic_stream(
    provider: str,
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    effort: str,
    temperature: float,
) -> AsyncIterator[dict]:
    entry = PROVIDERS[provider]
    kwargs = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": messages}
    apply_thinking(kwargs, effort, max_tokens)
    if system:
        kwargs["system"] = anthropic_system(system)
    tools = []
    if entry.get("search_tool"):
        tools.append({"type": entry["search_tool"], "name": "web_search", "max_uses": 5})
    if entry.get("fetch_tool"):
        tools.append({"type": entry["fetch_tool"], "name": "web_fetch", "max_uses": 5})
        kwargs["extra_headers"] = {"anthropic-beta": entry["fetch_beta"]}
    if tools:
        kwargs["tools"] = tools
    async with CLIENTS[provider].messages.stream(**kwargs) as stream:
        async for event in stream:
            if frame := anthropic_frame(event):
                yield frame


async def _responses_stream(
    provider: str,
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    effort: str,
    temperature: float,
) -> AsyncIterator[dict]:
    kwargs = {"model": model, "input": messages, "max_output_tokens": max_tokens, "stream": True}
    if system:
        kwargs["instructions"] = join_system(system)
    if takes_reasoning(provider, model):
        if effort:
            kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
    else:
        kwargs["temperature"] = temperature
    if search_tool := PROVIDERS[provider].get("search_tool"):
        kwargs["tools"] = [{"type": search_tool}]
    stream = await CLIENTS[provider].responses.create(**kwargs)
    async for event in stream:
        if frame := response_frame(event):
            yield frame


async def _chat_completions_stream(
    provider: str,
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    _effort: str,
    temperature: float,
) -> AsyncIterator[dict]:
    kwargs = chat_completions_kwargs(model, messages, system, max_tokens, temperature)
    stream = await CLIENTS[provider].chat.completions.create(stream=True, **kwargs)
    async for chunk in stream:
        for frame in chat_completion_frames(chunk):
            yield frame


DIALECT_STREAMS = {
    "anthropic": _anthropic_stream,
    "responses": _responses_stream,
    "chat_completions": _chat_completions_stream,
}


async def stream_chat(
    provider: str,
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    effort: str,
    temperature: float,
) -> AsyncIterator[dict]:
    try:
        async for frame in DIALECT_STREAMS[PROVIDERS[provider]["dialect"]](
            provider, model, messages, system, max_tokens, effort, temperature
        ):
            yield frame
        yield {"done": True}
    except Exception as error:
        yield {"error": str(error)}


async def complete(
    model_id: str,
    system: str | list[str] | None,
    prompt: str,
    max_tokens: int = 2048,
    effort: str = "",
    spend: object | None = None,
) -> str:
    provider, model = resolve_model(model_id)
    entry = PROVIDERS[provider]
    api = CLIENTS[provider]
    if entry["dialect"] == "anthropic":
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        apply_thinking(kwargs, effort, max_tokens)
        async with api.messages.stream(**kwargs) as stream:
            message = await stream.get_final_message()
        if spend:
            spend.add(model_id, message.usage.input_tokens, message.usage.output_tokens)
        return "".join(block.text for block in message.content if block.type == "text").strip()
    if entry["dialect"] == "responses":
        kwargs = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
        if system:
            kwargs["instructions"] = join_system(system)
        if effort and takes_reasoning(provider, model):
            kwargs["reasoning"] = {"effort": effort}
        response = await api.responses.create(**kwargs)
        if spend and response.usage:
            spend.add(model_id, response.usage.input_tokens, response.usage.output_tokens)
        return (response.output_text or "").strip()
    kwargs = chat_completions_kwargs(model, [{"role": "user", "content": prompt}], system, max_tokens)
    response = await api.chat.completions.create(**kwargs)
    if spend and response.usage:
        spend.add(model_id, response.usage.prompt_tokens, response.usage.completion_tokens)
    return (response.choices[0].message.content or "").strip()
