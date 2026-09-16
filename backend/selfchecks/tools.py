"""Selfcheck: python -m selfchecks.tools"""

import asyncio
import json

from pydantic import BaseModel

from tools import ConversaTool, ToolArguments, ToolCall, ToolOutput, ToolRejected, ToolUnavailable, execute_tool


class LookupArguments(ToolArguments):
    count: int


class LookupValue(BaseModel):
    items: list[int]


async def lookup(arguments: LookupArguments):
    return ToolOutput(LookupValue(items=[arguments.count]), {"source": "lookup", "count": arguments.count})


async def unavailable(_arguments: LookupArguments):
    raise ToolUnavailable("lookup credentials are unavailable")


async def rejected(_arguments: LookupArguments):
    raise ToolRejected("lookup is forbidden")


lookup_tool = ConversaTool("lookup", "Look up items.", LookupArguments, lookup, artifact_fresh_for=None)

result = asyncio.run(execute_tool(lookup_tool, ToolCall("call-1", "lookup", {"count": 2})))
assert result.call_id == "call-1" and result.name == "lookup" and result.error is None, result
assert result.content == '{"items":[2]}', result
assert result.trace == {"source": "lookup", "count": 2}, result
assert json.loads(result.content) != result.trace, "model output and browser trace are separate"

invalid = asyncio.run(execute_tool(lookup_tool, ToolCall("call-2", "lookup", {"count": "2"})))
assert invalid.error == "invalid_arguments", invalid
assert json.loads(invalid.content)["error"]["code"] == "invalid_arguments", invalid
assert invalid.trace == {"status": "error", "code": "invalid_arguments"}, invalid

extra = asyncio.run(execute_tool(lookup_tool, ToolCall("call-3", "lookup", {"count": 2, "page": 1})))
assert extra.error == "invalid_arguments", extra

unavailable_tool = ConversaTool("unavailable", "Look up unavailable items.", LookupArguments, unavailable, artifact_fresh_for=None)
unavailable_result = asyncio.run(execute_tool(unavailable_tool, ToolCall("call-4", "unavailable", {"count": 2})))
assert unavailable_result.error == "tool_unavailable", unavailable_result
assert unavailable_result.trace == {"status": "error", "code": "tool_unavailable"}, unavailable_result

rejected_tool = ConversaTool("rejected", "Reject a lookup.", LookupArguments, rejected, artifact_fresh_for=None)
rejected_result = asyncio.run(execute_tool(rejected_tool, ToolCall("call-5", "rejected", {"count": 2})))
assert rejected_result.error == "tool_rejected", rejected_result

mismatch = asyncio.run(execute_tool(lookup_tool, ToolCall("call-6", "other", {"count": 2})))
assert mismatch.error == "tool_unavailable", mismatch

try:
    class LooseArguments(BaseModel):
        count: int

    ConversaTool("loose", "Loose arguments.", LooseArguments, lookup, artifact_fresh_for=None)
    raise AssertionError("non-ToolArguments model accepted")
except TypeError:
    pass

print("tools selfcheck OK")
