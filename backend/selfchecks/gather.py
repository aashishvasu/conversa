"""Selfcheck: python -m selfchecks.gather"""

import asyncio
from types import SimpleNamespace

from providers import Spend
from research import gather as g
from tools import search as app_search

assert app_search.is_blocked("https://medium.com/x") and app_search.is_blocked("https://foo.medium.com/x")
assert app_search.is_blocked("https://www.geeksforgeeks.org/python/")
assert not app_search.is_blocked("https://notmedium.com/x")
assert not app_search.is_blocked("https://docs.python.org/3/library/asyncio-task.html")
assert not app_search.is_blocked("https://www.sqlite.org/wal.html")
response = SimpleNamespace(output=[SimpleNamespace(content=[SimpleNamespace(text="See https://example.com/docs.", annotations=[])])])
assert g._responses_hits(response, 2) == [{"title": None, "url": "https://example.com/docs"}]

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

async def _resilience_checks():
    real_search, real_page, real_note = g.search, g._page, g.note
    real_app_search, real_hosted_finder = app_search.search, g._hosted_finder

    async def paid_out_search(query, limit):
        raise RuntimeError("402 Payment Required")

    async def hosted(query, model, limit, provider, prompt, spend=None, model_id=None):
        return [{"title": "hosted", "url": "https://hosted.example/result"}]

    app_search.search = paid_out_search
    g._hosted_finder = lambda provider: hosted
    try:
        hits = await g.search("q", "claude-sonnet-5")
    finally:
        app_search.search, g._hosted_finder = real_app_search, real_hosted_finder
    assert hits == [{"title": "hosted", "url": "https://hosted.example/result"}], hits

    class FakeResponses:
        async def create(self, **kwargs):
            return SimpleNamespace(output=response.output, usage=SimpleNamespace(input_tokens=3, output_tokens=4))

    real_client = g.providers.CLIENTS["deepseek"]
    g.providers.CLIENTS["deepseek"] = SimpleNamespace(responses=FakeResponses())
    spend = Spend()
    try:
        await g._search_responses("q", "deepseek-v4-pro", 2, "deepseek", "prompt", spend, "deepseek/deepseek-v4-pro")
    finally:
        g.providers.CLIENTS["deepseek"] = real_client
    assert (spend.calls, spend.input, spend.output) == (1, 3, 4)

    async def dead_note(question, page, model_id, spend=None, note_prompt=None):
        raise RuntimeError("Error code: 529 - overloaded_error")

    async def two_sources(query, model_id, limit=8, search_prompt=None, spend=None):
        return [{"title": "a", "url": "https://a.example/1"}, {"title": "b", "url": "https://b.example/2"}]

    async def fake_page(url, question):
        return {"url": url, "title": "t", "kind": "article", "content": "body"}

    g.search, g._page, g.note = two_sources, fake_page, dead_note
    try:
        evidence = []
        out = await g.gather_task({"id": "T1", "question": "q"}, {}, "m", "m", {}, evidence, set(), limit=2)
    finally:
        g.search, g._page, g.note = real_search, real_page, real_note
    failed = [row for row in out["evidence"] if "error" in row]
    assert evidence == [], evidence
    assert len(failed) == 2 and all("529" in row["error"] for row in failed), out

    async def distinct_search(query, *args, **kwargs):
        return [{"title": query, "url": f"https://{query}.example/page"}]

    async def useful_note(question, page, model_id, spend=None, note_prompt=None):
        await asyncio.sleep(0)
        return f"evidence for {question}"

    registry, evidence = {}, []
    g.search, g._page, g.note = distinct_search, fake_page, useful_note
    try:
        await asyncio.gather(
            g.gather_task({"id": "T1", "question": "one"}, {}, "m", "m", registry, evidence, set()),
            g.gather_task({"id": "T2", "question": "two"}, {}, "m", "m", registry, evidence, set()),
        )
    finally:
        g.search, g._page, g.note = real_search, real_page, real_note
    assert {source["id"] for source in registry.values()} == {"S1", "S2"}, registry
    assert {item["source_id"] for item in evidence} == {"S1", "S2"}, evidence

    async def fatal_search(*args, **kwargs):
        raise RuntimeError("invalid model")
    g.search = fatal_search
    try:
        try:
            await g.gather_task({"id": "T1", "question": "q"}, {}, "m", "m", {}, [], set())
        except RuntimeError as error:
            assert "invalid model" in str(error)
        else:
            raise AssertionError("fatal provider failure was converted to a local gap")
    finally:
        g.search = real_search


asyncio.run(_resilience_checks())

print("gather selfcheck OK")
