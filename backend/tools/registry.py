"""Centralized app tool registry and request resolution."""

from .calculator import CALCULATOR_TOOL
from .conversa_tool import ConversaTool
from .random_tool import RANDOM_TOOL
from .temporal import DATETIME_TOOL
from .web import WEB_TOOLS


class ToolConfigError(ValueError):
    """Raised when request tool configuration is invalid."""

    def __init__(self, code: str, message: str, tool: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.tool = tool

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "tool": self.tool}


TOOL_REGISTRY: dict[str, ConversaTool] = {
    tool.name: tool
    for tool in [*WEB_TOOLS, DATETIME_TOOL, CALCULATOR_TOOL, RANDOM_TOOL]
}

DEFAULT_WEB_TOOLS: list[str] = ["search_web", "fetch_url"]


def resolve_enabled_tools(enabled_tools: list[str] | None, allow_tools: bool = False) -> list[ConversaTool]:
    """Resolve and validate request tools once at request start.

    When enabled_tools is present, it is authoritative. Duplicate or unknown names
    raise ToolConfigError. When absent, allow_tools maintains backwards compatibility.
    """
    if enabled_tools is not None:
        seen = set()
        resolved = []
        for name in enabled_tools:
            if name in seen:
                raise ToolConfigError("duplicate_tool", f"duplicate tool name: {name}", name)
            seen.add(name)
            tool = TOOL_REGISTRY.get(name)
            if tool is None:
                raise ToolConfigError("unknown_tool", f"unknown tool: {name}", name)
            resolved.append(tool)
        return resolved

    if allow_tools:
        return [TOOL_REGISTRY[name] for name in DEFAULT_WEB_TOOLS if name in TOOL_REGISTRY]
    return []
