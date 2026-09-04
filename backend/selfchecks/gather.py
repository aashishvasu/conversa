"""Selfcheck: python -m selfchecks.gather"""

import asyncio

from research import gather as g
from research.gather import lines
from tools import search as app_search

assert lines("NONE", 5) == []
assert lines("Sure, here you go:\n- What time period should this cover?", 5) == ["What time period should this cover?"]
assert app_search.is_blocked("https://medium.com/x") and app_search.is_blocked("https://foo.medium.com/x")
assert app_search.is_blocked("https://www.geeksforgeeks.org/python/")
assert not app_search.is_blocked("https://notmedium.com/x")
assert not app_search.is_blocked("https://docs.python.org/3/library/asyncio-task.html")
assert not app_search.is_blocked("https://www.sqlite.org/wal.html")

original_keys = app_search.EXA_API_KEY, app_search.BRAVE_API_KEY, app_search.SEARXNG_URL
original_finders = app_search._search_exa, app_search._search_brave, app_search._search_searxng
try:
    assert app_search._hits([{"title": "T", "url": "https://x.org/a"}, {"title": "row without url"}]) == [{"title": "T", "url": "https://x.org/a"}]
    assert app_search._hits(None) == []
    app_search.EXA_API_KEY, app_search.BRAVE_API_KEY, app_search.SEARXNG_URL = None, "key", ""
    assert app_search.app_finders() == [app_search._search_brave]
    app_search.EXA_API_KEY, app_search.SEARXNG_URL = "key", "https://sx.local"
    assert app_search.app_finders() == [app_search._search_exa, app_search._search_brave, app_search._search_searxng]
    assert app_search.filter_hits([
        {"title": "one", "url": "https://Example.com/a/?b=2&a=1#x"},
        {"title": "duplicate", "url": "https://example.com/a?a=1&b=2"},
        {"title": "blocked", "url": "https://medium.com/a"},
    ], 8) == [{"title": "one", "url": "https://example.com/a?a=1&b=2"}]

    tried = []

    async def unavailable(query, limit):
        tried.append("exa")
        raise RuntimeError("unavailable")

    async def available(query, limit):
        tried.append("brave")
        return [{"title": "result", "url": "https://example.com/result"}]

    app_search._search_exa, app_search._search_brave = unavailable, available
    assert asyncio.run(app_search.search("question")) == [{"title": "result", "url": "https://example.com/result"}]
    assert tried == ["exa", "brave"], tried
finally:
    app_search.EXA_API_KEY, app_search.BRAVE_API_KEY, app_search.SEARXNG_URL = original_keys
    app_search._search_exa, app_search._search_brave, app_search._search_searxng = original_finders

parsed = lines("Here you go:\n1. What is the cost?\n- How does it scale over time?\n\n* Why now, though?\nok", 5)
assert parsed == ["What is the cost?", "How does it scale over time?", "Why now, though?"], parsed
assert len(lines("\n".join(f"subquestion number {i} here" for i in range(9)), 4)) == 4


async def _resilience_checks():
    real_search, real_page, real_note = g.search, g._page, g.note

    async def dead_note(question, page, model_id, spend=None):
        raise RuntimeError("Error code: 529 - overloaded_error")

    async def two_sources(query, model_id, limit=8):
        return [{"title": "a", "url": "https://a.example/1"}, {"title": "b", "url": "https://b.example/2"}]

    async def fake_page(url, question):
        return {"url": url, "title": "t", "kind": "article", "content": "body"}

    g.search, g._page, g.note = two_sources, fake_page, dead_note
    try:
        out = await g.gather("q", "m", "m", limit=2)
    finally:
        g.search, g._page, g.note = real_search, real_page, real_note
    assert out["notes"] == [], out
    assert len(out["failed"]) == 2 and all("529" in failed["error"] for failed in out["failed"]), out


asyncio.run(_resilience_checks())

print("gather selfcheck OK")
