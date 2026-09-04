"""The three provider wire protocols, normalized to conversa event dictionaries."""

from collections.abc import AsyncIterator

from tools import ConversaTool, ToolCall
from tools.runner import DEFAULT_MAX_CALLS, DEFAULT_MAX_ROUNDS, ToolRunner, error_result, tool_frame

from .anthropic import LEGACY_EFFORT_BUDGETS, LEGACY_MODELS
from .registry import CLIENTS, DEFAULT_MAX_TOKENS, PROVIDERS, cost, join_model, resolve_model
from .tool_use import (
    _AnthropicToolDeltas,
    _ResponsesToolDeltas,
    _anthropic_followup,
    _anthropic_request_tools,
    _prefer_streamed_arguments,
    _responses_followup,
    anthropic_tool_calls,
    anthropic_tools,
    field,
    responses_request_tools,
    responses_tool_calls,
    responses_tools,
    tool_schema,
)


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
    return [{"type": "text", "text": text, **({"cache_control": {"type": "ephemeral"}} if index == 0 else {})} for index, text in enumerate(system) if text]


def chat_completions_kwargs(model: str, messages: list[dict], system: str | list[str] | None, max_tokens: int, temperature: float | None = None) -> dict:
    if system:
        messages = [{"role": "system", "content": join_system(system)}, *messages]
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return kwargs


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
        links = [{"title": field(result, "title"), "url": field(result, "url")} for result in block.content if field(result, "type") == "web_search_result"]
        return {"results": links} if links else None
    return None


def anthropic_usage(usage: object) -> dict:
    tool = field(usage, "server_tool_use")
    return {"input": field(usage, "input_tokens") or 0, "output": field(usage, "output_tokens") or 0, "cache_read": field(usage, "cache_read_input_tokens") or 0, "cache_write": field(usage, "cache_creation_input_tokens") or 0, "search_requests": (field(tool, "web_search_requests") or 0) if tool else 0}


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
            link = {"title": field(annotation, "title"), "url": field(annotation, "url")}
            return {"results": [link]}
    if event_type == "error":
        return {"error": str(field(event, "message") or event)}
    return None


def responses_usage_from(usage: object) -> dict:
    cache_read, cache_write = _cache_fields(field(usage, "input_tokens_details"))
    return {"input": field(usage, "input_tokens") or 0, "output": field(usage, "output_tokens") or 0, "cache_read": cache_read, "cache_write": cache_write, "search_requests": 0}


def responses_usage(event: object) -> dict | None:
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
    cache_read, cache_write = _cache_fields(field(usage, "prompt_tokens_details"))
    return {"input": field(usage, "prompt_tokens") or 0, "output": field(usage, "completion_tokens") or 0, "cache_read": cache_read, "cache_write": cache_write, "search_requests": 0}


def chat_completion_usage(chunk: object) -> dict | None:
    usage = field(chunk, "usage")
    return chat_completion_usage_from(usage) if usage else None


async def _anthropic_stream(provider: str, model: str, messages: list[dict], system: str | list[str] | None, max_tokens: int, effort: str, temperature: float, app_tools: list[ConversaTool] | None = None, allow_hosted_tools: bool = True) -> AsyncIterator[dict]:
    entry = PROVIDERS[provider]
    kwargs = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": messages}
    apply_thinking(kwargs, effort, max_tokens)
    if system:
        kwargs["system"] = anthropic_system(system)
    if tools := _anthropic_request_tools(entry, app_tools, allow_hosted_tools):
        kwargs["tools"] = tools
        if not app_tools and entry.get("fetch_tool"):
            kwargs["extra_headers"] = {"anthropic-beta": entry["fetch_beta"]}
    deltas = _AnthropicToolDeltas()
    async with CLIENTS[provider].messages.stream(**kwargs) as stream:
        async for event in stream:
            deltas.add(event)
            if frame := anthropic_frame(event):
                yield frame
        message = await stream.get_final_message()
    parsed_calls = anthropic_tool_calls(message)
    yield {"_usage": anthropic_usage(message.usage), "_response": message, "_tool_calls": _prefer_streamed_arguments(parsed_calls, deltas.parsed()) if parsed_calls else deltas.parsed()}


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


def responses_kwargs(provider: str, model: str, messages: list[dict], system: str | list[str] | None, max_tokens: int, effort: str, temperature: float, app_tools: list[ConversaTool] | None = None, allow_hosted_tools: bool = True, input_items: list[dict] | None = None) -> dict:
    kwargs = {"model": model, "input": input_items if input_items is not None else openai_messages(messages, True), "max_output_tokens": max_tokens, "stream": True}
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
    if tools := responses_request_tools(PROVIDERS[provider], app_tools, allow_hosted_tools):
        kwargs["tools"] = tools
    return kwargs


async def _responses_stream(provider: str, model: str, messages: list[dict], system: str | list[str] | None, max_tokens: int, effort: str, temperature: float, app_tools: list[ConversaTool] | None = None, allow_hosted_tools: bool = True, input_items: list[dict] | None = None) -> AsyncIterator[dict]:
    stream = await CLIENTS[provider].responses.create(**responses_kwargs(provider, model, messages, system, max_tokens, effort, temperature, app_tools, allow_hosted_tools, input_items))
    deltas = _ResponsesToolDeltas()
    response = None
    async for event in stream:
        deltas.add(event)
        if frame := response_frame(event):
            yield frame
        if usage := responses_usage(event):
            response = field(event, "response")
            yield {"_usage": usage}
    parsed_calls = responses_tool_calls(response) if response else []
    yield {"_response": response, "_tool_calls": _prefer_streamed_arguments(parsed_calls, deltas.parsed()) if parsed_calls else deltas.parsed()}


async def _chat_completions_stream(provider: str, model: str, messages: list[dict], system: str | list[str] | None, max_tokens: int, _effort: str, temperature: float, app_tools: list[ConversaTool] | None = None, allow_hosted_tools: bool = True) -> AsyncIterator[dict]:
    kwargs = chat_completions_kwargs(model, openai_messages(messages, False), system, max_tokens, temperature)
    kwargs["stream_options"] = {"include_usage": True}
    stream = await CLIENTS[provider].chat.completions.create(stream=True, **kwargs)
    async for chunk in stream:
        for frame in chat_completion_frames(chunk):
            yield frame
        if usage := chat_completion_usage(chunk):
            yield {"_usage": usage}


DIALECT_STREAMS = {"anthropic": _anthropic_stream, "responses": _responses_stream, "chat_completions": _chat_completions_stream}


def _usage_frame(provider: str, model: str, usages: list[dict], generations: int) -> dict:
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0, "unpriced": 0}
    for usage in usages:
        total["input"] += usage["input"]
        total["output"] += usage["output"]
        total["cache_read"] += usage["cache_read"]
        total["cache_write"] += usage["cache_write"]
        usd, priced = cost(provider, model, usage["input"], usage["output"], usage["cache_read"], usage["cache_write"], usage["search_requests"])
        total["usd"] += usd
        total["unpriced"] += not priced
    return {"usage": {"model": join_model(provider, model), "calls": generations, "input": total["input"], "output": total["output"], "cache_read": total["cache_read"], "cache_write": total["cache_write"], "usd": round(total["usd"], 6), "unpriced": total["unpriced"]}}


async def stream_chat(provider: str, model: str, messages: list[dict], system: str | list[str] | None, max_tokens: int, effort: str, temperature: float, tools: list[ConversaTool] | None = None, max_tool_rounds: int = DEFAULT_MAX_ROUNDS, max_tool_calls: int = DEFAULT_MAX_CALLS, allow_hosted_tools: bool = True) -> AsyncIterator[dict]:
    """Stream a chat turn, executing app tools only for tool-capable dialects."""
    dialect = PROVIDERS[provider]["dialect"]
    app_tools = tools if dialect in ("anthropic", "responses") and tools else None
    runner = ToolRunner(app_tools, max_tool_rounds, max_tool_calls) if app_tools else None
    hosted_fallback_blocked = False
    hosted_tools_enabled = allow_hosted_tools and not app_tools
    working_messages = messages
    input_items = openai_messages(messages, True) if dialect == "responses" else None
    usages: list[dict] = []
    generations = 0
    try:
        while True:
            generations += 1
            response = None
            calls: list[ToolCall] = []
            kwargs = {"app_tools": app_tools, "allow_hosted_tools": hosted_tools_enabled}
            if dialect == "responses":
                kwargs["input_items"] = input_items
            async for frame in DIALECT_STREAMS[dialect](provider, model, working_messages, system, max_tokens, effort, temperature, **kwargs):
                internal = False
                if "_usage" in frame:
                    usages.append(frame["_usage"])
                    internal = True
                if "_response" in frame:
                    response = frame["_response"]
                    calls = frame.get("_tool_calls", [])
                    internal = True
                if not internal:
                    yield frame
            if not calls:
                break
            if runner is None:
                break
            budget_exhausted = not runner.can_run_round()
            if budget_exhausted:
                results = [error_result(call, "tool_round_limit", "tool round limit reached") for call in calls]
                frames = [tool_frame(result, "error") for result in results]
            else:
                results, frames = await runner.run(calls)
            for frame in frames:
                yield frame
            if dialect == "anthropic":
                working_messages = _anthropic_followup(working_messages, response, results)
            else:
                input_items = _responses_followup(input_items or [], response, results)
            hosted_fallback_blocked |= any(result.error == "tool_rejected" for result in results)
            unavailable = any(result.error == "tool_unavailable" for result in results)
            if unavailable or budget_exhausted:
                app_tools = None
                runner = None
                hosted_tools_enabled = allow_hosted_tools and unavailable and not hosted_fallback_blocked
        if usages:
            yield _usage_frame(provider, model, usages, generations)
        yield {"done": True}
    except Exception as error:
        yield {"error": str(error)}


def complete_messages_kwargs(provider: str, model: str, messages: list[dict], system: str | list[str] | None, max_tokens: int, effort: str) -> dict:
    """Build one non-streaming completion request from assembled chat context."""
    dialect = PROVIDERS[provider]["dialect"]
    if dialect == "anthropic":
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = anthropic_system(system)
        return apply_thinking(kwargs, effort, max_tokens)
    if dialect == "responses":
        kwargs = {"model": model, "input": openai_messages(messages, True), "max_output_tokens": max_tokens}
        if system:
            kwargs["instructions"] = join_system(system)
        if takes_reasoning(provider, model):
            if effort:
                kwargs["reasoning"] = {"effort": effort}
                kwargs["max_output_tokens"] = max(max_tokens, REASONING_OUTPUT_FLOOR)
            elif provider == "deepseek":
                kwargs["reasoning"] = {"effort": "none"}
        return kwargs
    return chat_completions_kwargs(model, openai_messages(messages, False), system, max_tokens)


async def complete_messages(model_id: str, system: str | list[str] | None, messages: list[dict], max_tokens: int = 2048, effort: str = "") -> str:
    """Complete an already assembled conversation without flattening its context."""
    provider, model = resolve_model(model_id)
    api = CLIENTS[provider]
    kwargs = complete_messages_kwargs(provider, model, messages, system, max_tokens, effort)
    if PROVIDERS[provider]["dialect"] == "anthropic":
        async with api.messages.stream(**kwargs) as stream:
            message = await stream.get_final_message()
        return "".join(block.text for block in message.content if block.type == "text").strip()
    if PROVIDERS[provider]["dialect"] == "responses":
        response = await api.responses.create(**kwargs)
        return (response.output_text or "").strip()
    response = await api.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()


async def complete(model_id: str, system: str | list[str] | None, prompt: str, max_tokens: int = 2048, effort: str = "", spend: object | None = None) -> str:
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
            spend.add(model_id, usage["input"], usage["output"], usage["cache_read"], usage["cache_write"], usage["search_requests"])
        return "".join(block.text for block in message.content if block.type == "text").strip()
    if entry["dialect"] == "responses":
        kwargs = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
        if system:
            kwargs["instructions"] = join_system(system)
        if effort and takes_reasoning(provider, model):
            kwargs["reasoning"] = {"effort": effort}
            kwargs["max_output_tokens"] = max(max_tokens, REASONING_OUTPUT_FLOOR)
        elif provider == "deepseek":
            kwargs["reasoning"] = {"effort": "none"}
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
