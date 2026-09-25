"""Selfcheck: python -m selfchecks.registry"""

from tools import TOOL_REGISTRY, ToolConfigError, resolve_enabled_tools, resolve_research_tools

assert [tool.name for tool in resolve_research_tools("search")] == ["search_web"]
assert [tool.name for tool in resolve_research_tools("note")] == ["fetch_url"]
assert resolve_research_tools("unknown") == []

expected_tools = {"search_web", "fetch_url", "datetime", "calculator", "random"}
assert set(TOOL_REGISTRY.keys()) == expected_tools, TOOL_REGISTRY

resolved = resolve_enabled_tools(["datetime", "calculator"])
assert [tool.name for tool in resolved] == ["datetime", "calculator"], resolved

# enabled_tools is authoritative: an empty list stays empty even with allow_tools=True
assert resolve_enabled_tools([], allow_tools=True) == []

# allow_tools compatibility applies only when enabled_tools is absent
compat_true = resolve_enabled_tools(None, allow_tools=True)
assert [tool.name for tool in compat_true] == ["search_web", "fetch_url"], compat_true
assert resolve_enabled_tools(None, allow_tools=False) == []

try:
    resolve_enabled_tools(["datetime", "datetime"])
    raise AssertionError("duplicate tool name was accepted")
except ToolConfigError as error:
    assert error.code == "duplicate_tool" and error.tool == "datetime", error.as_dict()

try:
    resolve_enabled_tools(["unknown_tool"])
    raise AssertionError("unknown tool name was accepted")
except ToolConfigError as error:
    assert error.code == "unknown_tool" and error.tool == "unknown_tool", error.as_dict()

print("registry selfcheck OK")
