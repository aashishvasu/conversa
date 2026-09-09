"""Chat turn orchestration: tool loop and usage aggregation."""

from collections.abc import AsyncIterator

from tools import ConversaTool
from tools.runner import DEFAULT_MAX_CALLS, DEFAULT_MAX_ROUNDS, ToolRunner, error_result, tool_frame

from .dialects import _anthropic_stream, _chat_completions_stream, _responses_stream, openai_messages
from .tool_use import _anthropic_followup, _responses_followup
from .registry import PROVIDERS, cost, join_model


_DIALECT_STREAMS = {
    "anthropic": _anthropic_stream,
    "responses": _responses_stream,
    "chat_completions": _chat_completions_stream,
}


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
    usages = []
    generations = 0
    try:
        while True:
            generations += 1
            response = None
            calls = []
            kwargs = {"app_tools": app_tools, "allow_hosted_tools": hosted_tools_enabled}
            if dialect == "responses":
                kwargs["input_items"] = input_items
            async for frame in _DIALECT_STREAMS[dialect](provider, model, working_messages, system, max_tokens, effort, temperature, **kwargs):
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
