"""Provider-neutral tool definitions and execution."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError


class ToolArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ToolUnavailable(Exception):
    """Raised when a tool cannot run in the current environment."""


class ToolRejected(Exception):
    """Raised when app policy forbids an operation and hosted fallback."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolOutput:
    value: object
    trace: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    trace: dict[str, object] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ConversaTool:
    name: str
    description: str
    arguments: type[ToolArguments]
    execute: Callable[[ToolArguments], Awaitable[ToolOutput]]

    def __post_init__(self):
        if not issubclass(self.arguments, ToolArguments):
            raise TypeError("tool arguments must extend ToolArguments")


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _error(call: ToolCall, code: str, message: str) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=_json({"error": {"code": code, "message": message}}),
        trace={"status": "error", "code": code},
        error=code,
    )


def _validation_message(error: ValidationError) -> str:
    problems = []
    for problem in error.errors(include_input=False):
        location = ".".join(str(part) for part in problem["loc"])
        problems.append(f"{location}: {problem['type']}")
    return "; ".join(problems)


async def execute_tool(tool: ConversaTool, call: ToolCall) -> ToolResult:
    """Validate and execute one normalized tool call."""
    if call.name != tool.name:
        return _error(call, "tool_unavailable", "tool is unavailable")
    try:
        arguments = tool.arguments.model_validate(call.arguments)
    except ValidationError as error:
        return _error(call, "invalid_arguments", _validation_message(error))
    try:
        output = await tool.execute(arguments)
    except ToolRejected as error:
        return _error(call, "tool_rejected", str(error) or "tool request was rejected")
    except ToolUnavailable as error:
        return _error(call, "tool_unavailable", str(error) or "tool is unavailable")
    trace = json.loads(_json(output.trace)) if output.trace is not None else None
    return ToolResult(call.id, call.name, _json(output.value), trace)
