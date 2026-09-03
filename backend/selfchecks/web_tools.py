"""Selfcheck: python -m selfchecks.web_tools"""

import asyncio
import json

from tools import fetch, search
from tools.conversa_tool import ToolCall, execute_tool
from tools.web import WEB_TOOLS


tools = {tool.name: tool for tool in WEB_TOOLS}


async def checks():
    real_search, real_fetch = search.search, fetch.fetch

    async def fake_search(query, limit):
        assert query == "current release" and limit == 2
        return [{"title": "Release", "url": "https://example.com/release"}]

    async def fake_fetch(url, topic):
        assert url == "https://example.com/release" and topic == "release date"
        return {"url": url, "title": "Release", "kind": "article", "content": "PRIVATE PAGE BODY"}

    search.search, fetch.fetch = fake_search, fake_fetch
    try:
        found = await execute_tool(tools["search_web"], ToolCall("s1", "search_web", {"query": "current release", "limit": 2}))
        page = await execute_tool(tools["fetch_url"], ToolCall("f1", "fetch_url", {"url": "https://example.com/release", "topic": "release date"}))
    finally:
        search.search, fetch.fetch = real_search, real_fetch

    assert json.loads(found.content)["results"][0]["title"] == "Release", found
    assert found.trace == {"query": "current release", "results": [{"title": "Release", "url": "https://example.com/release"}]}, found
    assert json.loads(page.content)["content"] == "PRIVATE PAGE BODY", page
    assert page.trace == {"url": "https://example.com/release", "title": "Release", "kind": "article"}, page
    assert "PRIVATE PAGE BODY" not in str(page.trace), page

    missing_topic = await execute_tool(tools["fetch_url"], ToolCall("f2", "fetch_url", {"url": "https://example.com"}))
    assert missing_topic.error == "invalid_arguments", missing_topic

    async def no_search(_query, _limit):
        return None

    search.search = no_search
    unavailable = await execute_tool(tools["search_web"], ToolCall("s2", "search_web", {"query": "x"}))
    search.search = real_search
    assert unavailable.error == "tool_unavailable", unavailable

    async def failed_fetch(_url, _topic):
        raise fetch.FetchError("timed out")

    fetch.fetch = failed_fetch
    failed = await execute_tool(tools["fetch_url"], ToolCall("f3", "fetch_url", {"url": "https://example.com/slow", "topic": "slow"}))
    fetch.fetch = real_fetch
    assert failed.error == "tool_error", failed

    rejected = await execute_tool(tools["fetch_url"], ToolCall("f4", "fetch_url", {"url": "file:///etc/passwd", "topic": "passwords"}))
    assert rejected.error == "tool_rejected", rejected


asyncio.run(checks())
print("web tools selfcheck OK")
