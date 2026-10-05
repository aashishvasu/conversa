"""Selfcheck: python -m selfchecks.gather"""

import asyncio
import json
from types import SimpleNamespace

from providers import Spend
from research import gather as g
from research import parsing as p
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
    assert app_search._hits([{"title": "T", "url": "https://x.org/b", "description": "desc"}, {"title": "no snippet", "url": "https://x.org/c"}]) == [
        {"title": "T", "url": "https://x.org/b", "snippet": "desc"},
        {"title": "no snippet", "url": "https://x.org/c"},
    ]
    assert app_search.filter_hits([{"title": "one", "url": "https://Example.com/a/?b=2&a=1#x", "snippet": "kept"}], 8) == [
        {"title": "one", "url": "https://example.com/a?a=1&b=2", "snippet": "kept"}
    ]
    assert g._triage_picks([3, 1], 2, 6) == [3, 1]
    assert g._triage_picks({"selected": [2]}, 2, 6) == [2]
    assert g._triage_picks([3, 1], 2, 6) == [3, 1]
    assert g._triage_picks(["bad"], 2, 6) is None
    assert g._triage_picks([99, 0, 1], 2, 6) == [1]
    assert g._triage_picks([], 2, 6) is None

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

    async def echo_reformulate(model, system, prompt, **kwargs):
        question = prompt.split("Research Question: ", 1)[1].split("\n", 1)[0]
        return f'["{question}"]'

    g.complete = echo_reformulate

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

    real_client = g.providers.CLIENTS["openai"]
    g.providers.CLIENTS["openai"] = SimpleNamespace(responses=FakeResponses())
    spend = Spend()
    try:
        await g._search_responses("q", "gpt-5.6-sol", 2, "openai", "prompt", spend, "openai/gpt-5.6-sol")
    finally:
        g.providers.CLIENTS["openai"] = real_client
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
        return p.Note(gist=f"evidence for {question}", claims=[])

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

# WHY: reformulate_query makes a live provider call, so stub g.complete to keep selfchecks hermetic and free.
async def _reformulation_checks():
    real_search, real_complete = g.search, g.complete

    queries = []

    async def rec_search(query, *args, **kwargs):
        queries.append(query)
        return []

    async def variants(model, system, prompt, **kwargs):
        return '["variant one", "variant two", "variant one"]'

    g.search, g.complete = rec_search, variants
    try:
        ops = {}
        out = await g.gather_task({"id": "T1", "question": "q"}, {}, "m", "m", {}, [], set(), operations=ops)
        queries.clear()
        await g.gather_task({"id": "T2", "question": "q"}, {}, "m", "m", {}, [], set(), operations=ops)
    finally:
        g.search, g.complete = real_search, real_complete
    assert queries == ["variant one", "variant two"], queries
    assert ops["reformulations"]["q"] == ["variant one", "variant two"], ops
    assert out["gaps"] == ["no usable evidence for q"], out

asyncio.run(_reformulation_checks())

async def _triage_checks():
    real_search, real_complete, real_page, real_note = g.search, g.complete, g._page, g.note
    calls = {"complete": 0, "note": 0}
    events = []

    def record(kind, **data):
        events.append((kind, data))

    async def scan_search(query, *args, **kwargs):
        return [{"title": f"hit {query} {i}", "url": f"https://{query}.example/{i}", "snippet": f"snippet {query} {i}"} for i in range(6)]

    async def fake_complete(model_id, system, prompt, max_tokens=None, spend=None):
        calls["complete"] += 1
        if "Candidates:" in prompt:
            assert "snippet scan q 3" in prompt
            return "[3, 1]"
        return '["scan q"]'

    async def fake_note(question, page, model_id, spend=None, note_prompt=None):
        calls["note"] += 1
        return p.Note(gist="note", claims=[])

    async def fake_page(url, question):
        return {"url": url, "title": "t", "kind": "article", "content": "body"}

    g.search, g.complete, g._page, g.note = scan_search, fake_complete, fake_page, fake_note
    try:
        evidence, registry, seen = [], {}, set()
        out = await g.gather_task({"id": "T1", "question": "scan q"}, {}, "m", "m", registry, evidence, seen, limit=2, emit=record, operations={})
    finally:
        g.search, g.complete, g._page, g.note = real_search, real_complete, real_page, real_note
    assert calls == {"complete": 2, "note": 2}, calls
    assert len(evidence) == 2, evidence
    assert {source["url"] for source in registry.values()} == {"https://scan q.example/2", "https://scan q.example/0"}, registry
    triage_events = [event for event in events if event[0] == "triage"]
    assert len(triage_events) == 1 and triage_events[0][1]["scanned"] == 6 and triage_events[0][1]["selected"] == 2, events

    async def garbage_complete(model_id, system, prompt, max_tokens=None, spend=None):
        calls["complete"] += 1
        return "cannot parse this"

    calls = {"complete": 0, "note": 0}
    g.search, g.complete, g._page, g.note = scan_search, garbage_complete, fake_page, fake_note
    try:
        evidence = []
        await g.gather_task({"id": "T1", "question": "scan q"}, {}, "m", "m", {}, evidence, set(), limit=2, operations={"reformulations": {"scan q": ["scan q"]}})
    finally:
        g.search, g.complete, g._page, g.note = real_search, real_complete, real_page, real_note
    assert calls == {"complete": 1, "note": 2}, calls
    assert len(evidence) == 2, evidence

asyncio.run(_triage_checks())


def _payload(relevant=True, gist="gist", claims=None):
    return json.dumps({"relevant": relevant, "gist": gist, "claims": claims or []})


async def _note_checks():
    real_complete = g.complete
    page = {"url": "https://x.example/a", "title": "t", "content": "body"}
    replies = []

    async def respond(model_id, system, prompt, max_tokens=None, spend=None):
        return replies.pop(0)

    g.complete = respond
    try:
        replies.append(_payload(gist="gist text", claims=[{"text": "c", "stance": "supports", "confidence": "high", "as_of": "2024-01-01"}]))
        parsed = await g.note("q", page, "m")
        assert parsed.gist == "gist text", parsed
        assert parsed.claims[0].model_dump() == {"text": "c", "stance": "supports", "confidence": "high", "as_of": "2024-01-01"}, parsed

        for reply in (
            _payload(relevant=False),
            "NOTHING RELEVANT",
            "no json at all",
            _payload(claims=[{"text": "c", "stance": "maybe", "confidence": "high", "as_of": ""}]),
            "[1, 2]",
        ):
            replies.append(reply)
            assert await g.note("q", page, "m") is None, reply
    finally:
        g.complete = real_complete


asyncio.run(_note_checks())


async def _claims_checks():
    real_search, real_page, real_complete = g.search, g._page, g.complete
    payloads = [
        _payload(gist="gist A", claims=[{"text": "a", "stance": "contradicts", "confidence": "medium", "as_of": ""}]),
        _payload(relevant=False),
        "no json at all",
    ]

    async def three_sources(query, *args, **kwargs):
        return [{"title": f"hit {i}", "url": f"https://src.example/{i}"} for i in range(3)]

    async def fake_page(url, question):
        return {"url": url, "title": "t", "kind": "article", "content": "body"}

    async def json_complete(model_id, system, prompt, max_tokens=None, spend=None):
        return payloads.pop(0)

    g.search, g._page, g.complete = three_sources, fake_page, json_complete
    try:
        evidence = []
        out = await g.gather_task({"id": "T1", "question": "q"}, {}, "m", "m", {}, evidence, set(), limit=3, operations={"reformulations": {"q": ["q"]}})
    finally:
        g.search, g._page, g.complete = real_search, real_page, real_complete
    assert len(evidence) == 1, evidence
    assert "leads" not in out, out
    record = evidence[0]
    assert record["excerpt"] == "gist A" and "note" not in record, record
    assert record["claims"][0]["stance"] == "contradicts" and record["claims"][0]["confidence"] == "medium", record
    gaps = [row for row in out["evidence"] if row.get("gap")]
    assert len(gaps) == 2, out


asyncio.run(_claims_checks())


async def _pagination_checks():
    real_note, real_execute_tool = g.note, g.execute_tool
    spend = SimpleNamespace(calls=0)
    notes, offsets = [], []

    async def request_note(question, page, model_id, spend=None, note_prompt=None):
        notes.append(note_prompt)
        spend.calls += 1
        return p.Note(gist=f"window {len(notes)}", fetch_offset=page["nextOffset"])

    async def read_window(tool, call):
        offset = call.arguments["offset"]
        offsets.append(offset)
        return SimpleNamespace(error=None, content=json.dumps({
            "url": "https://x.example/long",
            "title": "long",
            "kind": "article",
            "content": f"window at {offset}",
            "offset": offset,
            "totalChars": 500,
            "nextOffset": offset + 100,
        }))

    g.note, g.execute_tool = request_note, read_window
    try:
        result = await g._note_windows(
            "q",
            "https://x.example/long",
            {"url": "https://x.example/long", "content": "first", "offset": 0, "nextOffset": 100},
            "m",
            spend,
            "note prompt",
        )
    finally:
        g.note, g.execute_tool = real_note, real_execute_tool
    assert len(notes) == g.NOTE_MAX_PAGES and spend.calls == g.NOTE_MAX_PAGES, (notes, spend.calls)
    assert offsets == [100, 200], offsets
    assert '"fetch_offset": 100' in notes[0] and '"fetch_offset": 200' in notes[1], notes
    assert '"fetch_offset": 300' in notes[2], notes
    assert result.gist == "window 1 window 2 window 3", result


asyncio.run(_pagination_checks())


def _classification_checks():
    assert g._fatal_provider(RuntimeError("401 unauthorized"))
    assert not g._retryable(RuntimeError("401 unauthorized"))
    assert not g._fatal_provider(RuntimeError("request timeout"))
    assert g._retryable(RuntimeError("request timeout"))
    assert not g._fatal_provider(RuntimeError("429 rate limit"))
    assert g._retryable(RuntimeError("429 rate limit"))
    assert not g._fatal_provider(g.app_fetch.FetchError("credit", 403))
    assert not g._retryable(g.app_fetch.FetchError("forbidden", 403))
    assert g._retryable(g.app_fetch.FetchError("server", 503))
    assert not g._retryable(g.app_fetch.FetchPolicyError("blocked", 503))


_classification_checks()

print("gather selfcheck OK")
