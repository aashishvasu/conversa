"""Provider tool schemas, calls, request selection, and continuations."""

import json

from tools import ConversaTool, ToolCall, ToolResult


def field(obj: object, name: str) -> object | None:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def tool_schema(tool: ConversaTool) -> dict:
    return tool.arguments.model_json_schema()


def anthropic_tools(tools: list[ConversaTool]) -> list[dict]:
    return [{"name": tool.name, "description": tool.description, "input_schema": tool_schema(tool)} for tool in tools]


def responses_tools(tools: list[ConversaTool]) -> list[dict]:
    return [{"type": "function", "name": tool.name, "description": tool.description, "parameters": tool_schema(tool)} for tool in tools]


def _arguments(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tool_call(value: object, fallback_id: str = "") -> ToolCall | None:
    call_id = field(value, "call_id") or field(value, "id") or fallback_id
    name = field(value, "name")
    if not isinstance(call_id, str) or not isinstance(name, str):
        return None
    arguments = field(value, "input") if field(value, "input") is not None else field(value, "arguments")
    return ToolCall(call_id, name, _arguments(arguments))


def anthropic_tool_calls(message: object) -> list[ToolCall]:
    return [call for block in field(message, "content") or [] if field(block, "type") == "tool_use" if (call := _tool_call(block))]


def responses_tool_calls(response: object) -> list[ToolCall]:
    return [call for item in field(response, "output") or [] if field(item, "type") == "function_call" if (call := _tool_call(item))]


def _prefer_streamed_arguments(calls: list[ToolCall], streamed: list[ToolCall]) -> list[ToolCall]:
    streamed_by_id = {call.id: call for call in streamed}
    return [streamed_by_id.get(call.id, call) if not call.arguments else call for call in calls]


class _AnthropicToolDeltas:
    def __init__(self):
        self.calls: dict[int, dict] = {}

    def add(self, event: object) -> None:
        if field(event, "type") == "content_block_start":
            block = field(event, "content_block")
            if field(block, "type") == "tool_use":
                self.calls[field(event, "index") or 0] = {"id": field(block, "id"), "name": field(block, "name"), "input": field(block, "input") or {}, "partial": ""}
        if field(event, "type") == "content_block_delta" and field(field(event, "delta"), "type") == "input_json_delta":
            state = self.calls.get(field(event, "index") or 0)
            if state:
                state["partial"] += field(field(event, "delta"), "partial_json") or ""

    def parsed(self) -> list[ToolCall]:
        out = []
        for state in self.calls.values():
            value = {**state, "input": _arguments(state["partial"]) if state["partial"] else state["input"]}
            if call := _tool_call(value):
                out.append(call)
        return out


class _ResponsesToolDeltas:
    def __init__(self):
        self.calls: dict[str, dict] = {}
        self.order: list[str] = []

    def add(self, event: object) -> None:
        event_type = field(event, "type")
        if event_type in ("response.output_item.added", "response.output_item.done"):
            item = field(event, "item")
            if field(item, "type") == "function_call":
                key = field(item, "id") or field(event, "item_id") or field(item, "call_id")
                if isinstance(key, str):
                    if key not in self.calls:
                        self.order.append(key)
                    prior = self.calls.get(key, {})
                    self.calls[key] = {"id": field(item, "call_id") or field(item, "id"), "name": field(item, "name"), "arguments": field(item, "arguments") or prior.get("arguments", "")}
        if event_type in ("response.function_call_arguments.delta", "response.function_call_arguments.done"):
            key = field(event, "item_id") or field(event, "output_index")
            state = self.calls.get(str(key)) if key is not None else None
            if state is not None:
                if event_type.endswith(".delta"):
                    state["arguments"] += field(event, "delta") or ""
                else:
                    state["arguments"] = field(event, "arguments") or state["arguments"]

    def parsed(self) -> list[ToolCall]:
        return [call for key in self.order if (call := _tool_call(self.calls[key]))]


def _anthropic_request_tools(entry: dict, app_tools: list[ConversaTool] | None, allow_hosted_tools: bool) -> list[dict]:
    if app_tools:
        return anthropic_tools(app_tools)
    if not allow_hosted_tools:
        return []
    tools = []
    if entry.get("search_tool"):
        tools.append({"type": entry["search_tool"], "name": "web_search", "max_uses": 5})
    if entry.get("fetch_tool"):
        tools.append({"type": entry["fetch_tool"], "name": "web_fetch", "max_uses": 5})
    return tools


def responses_request_tools(entry: dict, app_tools: list[ConversaTool] | None, allow_hosted_tools: bool) -> list[dict]:
    if app_tools:
        return responses_tools(app_tools)
    search_tool = entry.get("search_tool")
    return [{"type": search_tool}] if allow_hosted_tools and search_tool else []


def _as_dict(value: object) -> dict | None:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump(exclude_none=True) if dump else None


def _response_items(response: object) -> list[dict]:
    return [_as_dict(item) or item for item in field(response, "output") or []]


def _anthropic_followup(messages: list[dict], response: object, results: list[ToolResult]) -> list[dict]:
    return [*messages, {"role": "assistant", "content": field(response, "content")}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": result.call_id, "content": result.content, **({"is_error": True} if result.error else {})} for result in results]}]


def _responses_followup(input_items: list[dict], response: object, results: list[ToolResult]) -> list[dict]:
    return [*input_items, *_response_items(response), *[{"type": "function_call_output", "call_id": result.call_id, "output": result.content} for result in results]]
