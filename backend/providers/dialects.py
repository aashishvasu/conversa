"""The three provider wire protocols, normalized to conversa event dictionaries."""

from collections.abc import AsyncIterator

from .anthropic import LEGACY_EFFORT_BUDGETS, LEGACY_MODELS
from .registry import (
    CLIENTS,
    DEFAULT_MAX_TOKENS,
    PROVIDERS,
    cost,
    join_model,
    resolve_model,
)


# Reasoning spends from the output budget, so any effort-enabled call gets at least this much or the answer starves after the thinking.
REASONING_OUTPUT_FLOOR = 32000


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
        kwargs["max_tokens"] = max(max_tokens, REASONING_OUTPUT_FLOOR)
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


def anthropic_usage(usage: object) -> dict:
    """Token, cache, and hosted-search counts from an Anthropic Usage object."""
    tool = field(usage, "server_tool_use")
    return {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_read": usage.cache_read_input_tokens or 0,
        "cache_write": usage.cache_creation_input_tokens or 0,
        "search_requests": (field(tool, "web_search_requests") or 0) if tool else 0,
    }


def _cache_fields(details: object | None) -> tuple[int, int]:
    if not details:
        return 0, 0
    return field(details, "cached_tokens") or 0, field(details, "cache_write_tokens") or 0


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


def responses_usage_from(usage: object) -> dict:
    """Token and cache counts from a Responses Usage object, streamed or from complete()."""
    cache_read, cache_write = _cache_fields(field(usage, "input_tokens_details"))
    return {
        "input": field(usage, "input_tokens") or 0,
        "output": field(usage, "output_tokens") or 0,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "search_requests": 0,  # the Responses dialect reports no hosted-search use count
    }


def responses_usage(event: object) -> dict | None:
    """Usage from a streamed response.completed event, or None for any other event type."""
    if field(event, "type") != "response.completed":
        return None
    usage = field(field(event, "response"), "usage")
    return responses_usage_from(usage) if usage else None


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


def chat_completion_usage_from(usage: object) -> dict:
    """Token and cache counts from a chat.completions Usage object."""
    cache_read, cache_write = _cache_fields(field(usage, "prompt_tokens_details"))
    return {
        "input": field(usage, "prompt_tokens") or 0,
        "output": field(usage, "completion_tokens") or 0,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "search_requests": 0,
    }


def chat_completion_usage(chunk: object) -> dict | None:
    """Usage from the chunk stream_options={"include_usage": True} attaches, or None otherwise."""
    usage = field(chunk, "usage")
    return chat_completion_usage_from(usage) if usage else None


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
        yield {"_usage": anthropic_usage((await stream.get_final_message()).usage)}


def openai_messages(messages: list[dict], responses: bool) -> list[dict]:
    text_type = "input_text" if responses else "text"
    image_type = "input_image" if responses else "image_url"
    out = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            out.append(message)
            continue
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append({"type": text_type, "text": block["text"]})
            else:
                source = block["source"]
                url = f"data:{source['media_type']};base64,{source['data']}"
                parts.append({"type": image_type, "image_url": url} if responses else {"type": image_type, "image_url": {"url": url}})
        out.append({**message, "content": parts})
    return out


def responses_kwargs(
    provider: str,
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    effort: str,
    temperature: float,
) -> dict:
    kwargs = {"model": model, "input": openai_messages(messages, True), "max_output_tokens": max_tokens, "stream": True}
    if system:
        kwargs["instructions"] = join_system(system)
    if takes_reasoning(provider, model):
        if effort:
            kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
            kwargs["max_output_tokens"] = max(max_tokens, REASONING_OUTPUT_FLOOR)
        elif provider == "deepseek":
            kwargs["reasoning"] = {"effort": "none"}
    else:
        kwargs["temperature"] = temperature
    if search_tool := PROVIDERS[provider].get("search_tool"):
        kwargs["tools"] = [{"type": search_tool}]
    return kwargs


async def _responses_stream(
    provider: str,
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    effort: str,
    temperature: float,
) -> AsyncIterator[dict]:
    stream = await CLIENTS[provider].responses.create(**responses_kwargs(
        provider, model, messages, system, max_tokens, effort, temperature
    ))
    async for event in stream:
        if frame := response_frame(event):
            yield frame
        if usage := responses_usage(event):
            yield {"_usage": usage}


async def _chat_completions_stream(
    provider: str,
    model: str,
    messages: list[dict],
    system: str | list[str] | None,
    max_tokens: int,
    _effort: str,
    temperature: float,
) -> AsyncIterator[dict]:
    kwargs = chat_completions_kwargs(model, openai_messages(messages, False), system, max_tokens, temperature)
    # WHY: opt into the OpenAI-standard usage-on-final-chunk flag, otherwise chat.completions pricing is permanently blind.
    # A strict OpenAI-compatible endpoint that rejects the param would 400 the whole stream; no key is available to verify one that does.
    kwargs["stream_options"] = {"include_usage": True}
    stream = await CLIENTS[provider].chat.completions.create(stream=True, **kwargs)
    async for chunk in stream:
        for frame in chat_completion_frames(chunk):
            yield frame
        if usage := chat_completion_usage(chunk):
            yield {"_usage": usage}


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
        usage = None
        async for frame in DIALECT_STREAMS[PROVIDERS[provider]["dialect"]](
            provider, model, messages, system, max_tokens, effort, temperature
        ):
            if "_usage" in frame:
                usage = frame["_usage"]  # internal signal from the adapter, not forwarded to the client
                continue
            yield frame
        if usage:
            usd, priced = cost(
                provider, model, usage["input"], usage["output"],
                usage["cache_read"], usage["cache_write"], usage["search_requests"],
            )
            yield {"usage": {
                "model": join_model(provider, model),
                "input": usage["input"], "output": usage["output"],
                "cache_read": usage["cache_read"], "cache_write": usage["cache_write"],
                "usd": round(usd, 6), "unpriced": not priced,
            }}
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
            usage = anthropic_usage(message.usage)
            spend.add(model_id, usage["input"], usage["output"], usage["cache_read"],
                      usage["cache_write"], usage["search_requests"])
        return "".join(block.text for block in message.content if block.type == "text").strip()
    if entry["dialect"] == "responses":
        kwargs = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
        if system:
            kwargs["instructions"] = join_system(system)
        if effort and takes_reasoning(provider, model):
            kwargs["reasoning"] = {"effort": effort}
            kwargs["max_output_tokens"] = max(max_tokens, REASONING_OUTPUT_FLOOR)
        response = await api.responses.create(**kwargs)
        if spend and response.usage:
            usage = responses_usage_from(response.usage)
            spend.add(model_id, usage["input"], usage["output"], usage["cache_read"], usage["cache_write"])
        return (response.output_text or "").strip()
    kwargs = chat_completions_kwargs(model, [{"role": "user", "content": prompt}], system, max_tokens)
    response = await api.chat.completions.create(**kwargs)
    if spend and response.usage:
        usage = chat_completion_usage_from(response.usage)
        spend.add(model_id, usage["input"], usage["output"], usage["cache_read"], usage["cache_write"])
    return (response.choices[0].message.content or "").strip()
