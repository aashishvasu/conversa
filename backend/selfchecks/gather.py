"""Selfcheck: python -m selfchecks.gather"""

import asyncio

from research import gather as g
from research.gather import PageCache, _hits, app_finders, is_blocked, lines

# The clarify prompt's NONE sentinel resolves to no questions through lines()' length floor.
assert lines("NONE", 5) == []
assert lines("Sure, here you go:\n- What time period should this cover?", 5) == ["What time period should this cover?"]

assert is_blocked("https://medium.com/x") and is_blocked("https://foo.medium.com/x")
assert is_blocked("https://www.geeksforgeeks.org/python/")
# Suffix matching has to respect the dot, or an unrelated host gets blocked by accident.
assert not is_blocked("https://notmedium.com/x")
assert not is_blocked("https://docs.python.org/3/library/asyncio-task.html")
assert not is_blocked("https://www.sqlite.org/wal.html")

# App finders: one normalizer for every API's result list, and precedence follows configuration order.
# The finder list reads module globals, so the configuration is set on the module.
assert _hits([{"title": "T", "url": "https://x.org/a"}, {"title": "row without url"}]) == [{"title": "T", "url": "https://x.org/a"}]
assert _hits(None) == []
g.EXA_API_KEY, g.BRAVE_API_KEY, g.SEARXNG_URL = None, "key", ""
assert app_finders() == [g._search_brave]
g.EXA_API_KEY, g.SEARXNG_URL = "key", "https://sx.local"
assert app_finders() == [g._search_exa, g._search_brave, g._search_searxng]
g.EXA_API_KEY = g.BRAVE_API_KEY = g.SEARXNG_URL = None
assert app_finders() == []

# lines(): models add numbering and bullets whatever the prompt says, and sometimes a preamble.
parsed = lines("Here you go:\n1. What is the cost?\n- How does it scale over time?\n\n* Why now, though?\nok", 5)
assert parsed == ["What is the cost?", "How does it scale over time?", "Why now, though?"], parsed
assert len(lines("\n".join(f"subquestion number {i} here" for i in range(9)), 4)) == 4


# PageCache: one download per URL however many subquestions want it, even when they race.
# Each caller still gets an extract selected against its own topic.
async def _cache_checks():
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        await asyncio.sleep(0.01)  # long enough for the racers below to pile up on the lock
        return {"url": url, "title": "t", "kind": "article",
                "content": "# Alpha\nalpha alpha alpha\n\n# Beta\nbeta beta beta"}

    cache = PageCache(fetch=fake_fetch)
    got = await asyncio.gather(*(cache.get("https://x.example/p", t) for t in ("alpha", "beta", "alpha")))
    assert len(calls) == 1, calls
    assert cache.fetches == 1, cache.fetches
    assert got[0]["content"].startswith("# Alpha") and got[1]["content"].startswith("# Beta")
    await cache.get("https://y.example/p", "alpha")
    assert cache.fetches == 2, "a different URL is a real fetch"

asyncio.run(_cache_checks())


# Failure isolation, stubbed so it costs nothing and stays runnable.
# One source raising must cost that source alone.
async def _resilience_checks():
    real_search, real_page, real_note = g.search, g._page, g.note

    async def dead_note(question, page, model_id, spend=None):
        raise RuntimeError("Error code: 529 - overloaded_error")

    async def two_sources(query, model_id, limit=8):
        return [{"title": "a", "url": "https://a.example/1"}, {"title": "b", "url": "https://b.example/2"}]

    async def fake_page(url, question, pages):
        return {"url": url, "title": "t", "kind": "article", "content": "body"}

    g.search, g._page, g.note = two_sources, fake_page, dead_note
    try:
        out = await g.gather("q", "m", "m", limit=2)
    finally:
        g.search, g._page, g.note = real_search, real_page, real_note
    assert out["notes"] == [], out
    assert len(out["failed"]) == 2 and all("529" in f["error"] for f in out["failed"]), out

asyncio.run(_resilience_checks())

print("gather selfcheck OK")
