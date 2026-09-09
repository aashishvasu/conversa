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
    supports_tools = dialect in ("anthropic", "responses")
    selected_tools = {tool.name: tool for tool in (tools or [])} if supports_tools else {}
    search_selected = "search_web" in selected_tools
    fetch_selected = "fetch_url" in selected_tools

    active_tools = dict(selected_tools)
    runner = ToolRunner(list(active_tools.values()), max_tool_rounds, max_tool_calls) if active_tools else None

    search_fallback_blocked = False
    fetch_fallback_blocked = False
    hosted_search_enabled = False
    hosted_fetch_enabled = False

    working_messages = messages
    input_items = openai_messages(messages, True) if dialect == "responses" else None
    usages = []
    generations = 0
    try:
        while True:
            generations += 1
            response = None
            calls = []
            kwargs = {
                "app_tools": list(active_tools.values()) if active_tools else None,
                "hosted_search": hosted_search_enabled,
            }
            if dialect == "anthropic":
                kwargs["hosted_fetch"] = hosted_fetch_enabled
            elif dialect == "responses":
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

            if budget_exhausted:
                active_tools.clear()
                runner = None
                hosted_search_enabled = False
                hosted_fetch_enabled = False
            else:
                for result in results:
                    if result.name == "search_web":
                        if result.error == "tool_rejected":
                            search_fallback_blocked = True
                            hosted_search_enabled = False
                        elif result.error == "tool_unavailable":
                            active_tools.pop("search_web", None)
                            runner.disable_tool("search_web")
                            if search_selected and not search_fallback_blocked and allow_hosted_tools:
                                hosted_search_enabled = True
                    elif result.name == "fetch_url":
                        if result.error == "tool_rejected":
                            fetch_fallback_blocked = True
                            hosted_fetch_enabled = False
                        elif result.error == "tool_unavailable":
                            active_tools.pop("fetch_url", None)
                            runner.disable_tool("fetch_url")
                            if fetch_selected and not fetch_fallback_blocked and allow_hosted_tools:
                                hosted_fetch_enabled = True
                    elif result.error == "tool_unavailable":
                        active_tools.pop(result.name, None)
                        runner.disable_tool(result.name)

        if usages:
            yield _usage_frame(provider, model, usages, generations)
        yield {"done": True}
    except Exception as error:
        yield {"error": str(error)}
