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

    async def fake_fetch(url, topic, raw, offset):
        assert url == "https://example.com/release" and topic == "release date" and raw is False and offset == 0
        return {"url": url, "title": "Release", "kind": "article", "content": "PRIVATE PAGE BODY", "offset": 0, "totalChars": 17, "nextOffset": None}

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
    # The durable artifact is the client-safe provenance record: query, hits, and the fetched body itself.
    assert found.artifact == {"input": {"query": "current release", "limit": 2}, "output": {"results": [{"title": "Release", "url": "https://example.com/release"}]}}, found
    assert page.artifact == {"input": {"url": "https://example.com/release", "topic": "release date", "raw": False, "offset": 0}, "output": {"url": "https://example.com/release", "title": "Release", "kind": "article", "content": "PRIVATE PAGE BODY", "offset": 0, "totalChars": 17, "nextOffset": None}}, page
    assert tools["search_web"].artifact_fresh_for == 1800 and tools["fetch_url"].artifact_fresh_for == 1800

    seen = []

    async def window_fetch(url, topic, raw, offset):
        seen.append((topic, raw, offset))
        return {"url": url, "title": None, "kind": "html" if raw else "article", "content": "body", "offset": offset, "totalChars": 10, "nextOffset": offset + 4 if offset + 4 < 10 else None}

    fetch.fetch = window_fetch
    whole = await execute_tool(tools["fetch_url"], ToolCall("f2", "fetch_url", {"url": "https://example.com/doc"}))
    source = await execute_tool(tools["fetch_url"], ToolCall("f5", "fetch_url", {"url": "https://example.com/doc", "raw": True}))
    tail = await execute_tool(tools["fetch_url"], ToolCall("f6", "fetch_url", {"url": "https://example.com/doc", "offset": 6}))
    fetch.fetch = real_fetch
    assert seen == [(None, False, 0), (None, True, 0), (None, False, 6)], seen
    assert json.loads(whole.content)["nextOffset"] == 4, whole
    assert json.loads(source.content)["kind"] == "html", source
    assert json.loads(tail.content)["nextOffset"] is None, tail

    async def no_search(_query, _limit):
        return None

    search.search = no_search
    unavailable = await execute_tool(tools["search_web"], ToolCall("s2", "search_web", {"query": "x"}))
    search.search = real_search
    assert unavailable.error == "tool_unavailable", unavailable
    assert unavailable.artifact is None, unavailable

    async def failed_fetch(_url, _topic, _raw, _offset):
        raise fetch.FetchError("timed out")

    fetch.fetch = failed_fetch
    failed = await execute_tool(tools["fetch_url"], ToolCall("f3", "fetch_url", {"url": "https://example.com/slow", "topic": "slow"}))
    fetch.fetch = real_fetch
    assert failed.error == "tool_error", failed
    assert failed.artifact is None, failed

    rejected = await execute_tool(tools["fetch_url"], ToolCall("f4", "fetch_url", {"url": "file:///etc/passwd", "topic": "passwords"}))
    assert rejected.error == "tool_rejected", rejected
    assert rejected.artifact is None, rejected


asyncio.run(checks())
print("web tools selfcheck OK")
