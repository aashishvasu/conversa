"""Bounded execution and browser-safe tracing for client tools."""

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from .conversa_tool import ConversaTool, ToolCall, ToolResult, execute_tool


DEFAULT_MAX_ROUNDS = 4
DEFAULT_MAX_CALLS = 16
_REDACTED_KEYS = {"arguments", "authorization", "content", "data", "input", "key", "output", "password", "result", "secret", "token", "value"}


def error_result(call: ToolCall, code: str, message: str) -> ToolResult:
    return ToolResult(
        call.id,
        call.name,
        json.dumps({"error": {"code": code, "message": message}}, separators=(",", ":")),
        {"status": "error", "code": code},
        code,
    )


def _redacted_key(key: object) -> bool:
    name = str(key).lower()
    return name in _REDACTED_KEYS or any(part in name for part in ("secret", "token", "password", "authorization", "api_key"))


def redact_trace(value: object, content: str | None = None) -> object:
    """Keep browser traces structural while removing model output and secrets."""
    if isinstance(value, dict):
        return {str(key): redact_trace(item, content) for key, item in value.items() if not _redacted_key(key)}
    if isinstance(value, (list, tuple)):
        return [redact_trace(item, content) for item in value]
    if isinstance(value, str) and value == content:
        return "[redacted]"
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def tool_frame(result: ToolResult, status: str) -> dict:
    """Render a result without exposing its model-facing content."""
    return {"tool": {"id": result.call_id, "name": result.name, "status": status, "trace": redact_trace(result.trace, result.content)}}


@dataclass(slots=True)
class ToolRunner:
    """Run a request's app tools within fixed round and call budgets."""

    tools: Iterable[ConversaTool]
    max_rounds: int = DEFAULT_MAX_ROUNDS
    max_calls: int = DEFAULT_MAX_CALLS
    rounds: int = 0
    calls: int = 0
    _tools: dict[str, ConversaTool] = field(init=False)

    def __post_init__(self) -> None:
        if self.max_rounds < 1 or self.max_calls < 1:
            raise ValueError("tool budgets must be positive")
        self._tools = {tool.name: tool for tool in self.tools}

    def can_run_round(self) -> bool:
        return self.rounds < self.max_rounds

    async def run(self, calls: list[ToolCall]) -> tuple[list[ToolResult], list[dict]]:
        """Execute calls concurrently, retaining provider order in results and frames."""
        self.rounds += 1
        pending = []
        results = []
        running = []
        for call in calls:
            if self.calls >= self.max_calls:
                results.append(error_result(call, "tool_call_limit", "tool call limit reached"))
                continue
            self.calls += 1
            pending.append(call)
            results.append(None)
            running.append({"tool": {"id": call.id, "name": call.name, "status": "running", "trace": None}})
        completed = await asyncio.gather(*(self._execute(call) for call in pending))
        iterator = iter(completed)
        ordered = [result if result is not None else next(iterator) for result in results]
        frames = [*running, *(tool_frame(result, "error" if result.error else "completed") for result in ordered)]
        return ordered, frames

    async def _execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return error_result(call, "tool_unavailable", "tool is unavailable")
        try:
            return await execute_tool(tool, call)
        except Exception:
            return error_result(call, "tool_error", "tool execution failed")
