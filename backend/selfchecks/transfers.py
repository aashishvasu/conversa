"""Selfcheck: python -m selfchecks.transfers"""

import asyncio
import json
import re

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.auth import mint_token
from api.transfers import CreateBody, _read_limited_body, router
from transfers import phrases
from transfers.store import STORE, CapacityFull, EntryTooLarge, Store

# --- Word pools and phrase format -------------------------------------------------
for word in phrases.VERBS + phrases.ADJECTIVES + phrases.ANIMALS:
    assert re.fullmatch(r"[a-z]+", word), word
for pool in (phrases.VERBS, phrases.ADJECTIVES, phrases.ANIMALS):
    assert len(pool) == len(set(pool)), "word pool has duplicates"

assert phrases.entropy_bits() >= 40, phrases.entropy_bits()

phrase = phrases.generate()
assert phrases.normalize(phrase) == phrase
assert re.fullmatch(r"[a-z]+-[a-z]+-[a-z]+-[a-z]+-[a-z]+", phrase)
assert len({phrases.generate() for _ in range(1000)}) == 1000, "a burst of phrases stays distinct"

# --- Normalization ---------------------------------------------------------------
assert phrases.normalize("run-jump-happy-calm-fox") == "run-jump-happy-calm-fox"
assert phrases.normalize("  RUN  Jump_happy calm FOX ") == "run-jump-happy-calm-fox"
assert phrases.normalize("RUN\nJump\thappy.calm fox") == "run-jump-happy-calm-fox"
for bad in ("", "not enough words", "six-whole-words-right-here-now", "walk-jump-kind", "walk-jump-kind-kind", "walk-jump-kind-kind-kind-kind-fox"):
    assert phrases.normalize(bad) is None, bad


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


# --- Store roundtrip, expiry, and limits -----------------------------------------
async def _store_checks():
    clock = Clock()
    store = Store(ttl=60, max_entry_bytes=10000, max_total_bytes=10000, max_entries=8, now=clock)
    data = {"version": 2, "conversations": [{"id": "a", "messages": []}]}
    entry = await store.create("conversation", data)
    assert entry["bytes"] > 0
    assert entry["phrase"].count("-") == 4
    assert isinstance(store._lock, asyncio.Lock)

    stored = store.entries[entry["phrase"]]
    assert "payload" in stored
    assert "data" not in stored
    assert isinstance(stored["payload"], bytes)
    expected_payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert stored["payload"] == expected_payload
    assert entry["bytes"] == len(expected_payload)

    got = await store.retrieve(entry["phrase"])
    assert got["scope"] == "conversation"
    assert got["data"] == data
    assert (await store.retrieve("  " + entry["phrase"].upper().replace("-", " ") + "  "))["scope"] == "conversation"
    assert await store.retrieve(entry["phrase"]) is not None, "retrieval must not consume an entry"
    clock.advance(61)
    assert await store.retrieve(entry["phrase"]) is None, "an expired entry is gone"
    assert entry["phrase"] not in store.entries, "the expired entry was pruned"

    # Per-entry byte limit is enforced on the exact serialized UTF-8 bytes.
    small = Store(ttl=60, max_entry_bytes=100, max_total_bytes=10000, max_entries=8, now=Clock())
    try:
        await small.create("snapshot", {"blob": "a" * 500})
        raise AssertionError("oversized entry accepted")
    except EntryTooLarge:
        pass

    # Entry count limit, then expiry frees a slot.
    clock = Clock()
    tight = Store(ttl=60, max_entry_bytes=1000, max_total_bytes=100000, max_entries=2, now=clock)
    payload = {"blob": "a" * 200}
    await tight.create("snapshot", payload)
    await tight.create("snapshot", payload)
    try:
        await tight.create("snapshot", payload)
        raise AssertionError("over-count entry accepted")
    except CapacityFull:
        pass
    clock.advance(61)
    assert (await tight.create("snapshot", payload))["phrase"], "pruning expired entries frees a slot"

    # Total-byte limit uses the stored payload bytes.
    clock = Clock()
    quota = Store(ttl=60, max_entry_bytes=1000, max_total_bytes=600, max_entries=8, now=clock)
    await quota.create("snapshot", {"blob": "a" * 300})
    try:
        await quota.create("snapshot", {"blob": "a" * 300})
        raise AssertionError("over-quota entry accepted")
    except CapacityFull:
        pass

    # Collision handling: a generated phrase that is already present is regenerated.
    clock = Clock()
    colliding = Store(ttl=60, max_entry_bytes=1000, max_total_bytes=100000, max_entries=8, now=clock)
    colliding.entries["zzzz-yyyy-xxxx-wwww-vvvv"] = {"scope": "snapshot", "payload": b"{}", "expires_at": 1e9}
    original_generate = phrases.generate
    results = iter(["zzzz-yyyy-xxxx-wwww-vvvv", "jump-jump-quick-quick-owl"])
    phrases.generate = lambda: next(results)
    try:
        made = await colliding.create("snapshot", {"a": 1})
        assert made["phrase"] == "jump-jump-quick-quick-owl", "the collision was skipped"
    finally:
        phrases.generate = original_generate

    # Concurrent creates are serialised by the lock and respect capacity.
    clock = Clock()
    limited = Store(ttl=60, max_entry_bytes=1000, max_total_bytes=100000, max_entries=3, now=clock)

    async def try_create(i):
        try:
            return await limited.create("snapshot", {"i": i})
        except CapacityFull:
            return None

    outcomes = await asyncio.gather(*(try_create(i) for i in range(5)))
    successes = [o for o in outcomes if o]
    assert len(successes) == 3, successes
    assert sum(len(e["payload"]) for e in limited.entries.values()) == limited._total_bytes()


# --- Endpoint behaviour ----------------------------------------------------------
async def _endpoint_checks():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {mint_token()}"}

    assert client.post("/api/transfers", json={"scope": "conversation", "data": {}}).status_code == 401
    assert client.post("/api/transfers/retrieve", json={"phrase": "walk-walk-kind-kind-fox"}).status_code == 401

    STORE.entries.clear()
    created = client.post(
        "/api/transfers",
        json={"scope": "conversation", "data": {"version": 2, "conversations": [{"id": "c1", "messages": []}]}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    phrase = created.json()["phrase"]
    retrieved = client.post("/api/transfers/retrieve", json={"phrase": phrase}, headers=headers)
    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["scope"] == "conversation"

    for bad in ("too short", "walk-jump-kind", "six-whole-words-right-here-now", "walk-walk-kind-kind-fox"):
        response = client.post("/api/transfers/retrieve", json={"phrase": bad}, headers=headers)
        assert response.status_code == 404, bad
        assert response.json()["detail"]["code"] == "no_such_transfer"

    # Malformed retrieve requests are treated the same as unknown or expired ones.
    malformed_headers = {**headers, "Content-Type": "application/json"}
    for body in ("not json", "{}", '{"phrase": 123}', '{"phrase": null}', '{"other": "value"}'):
        response = client.post("/api/transfers/retrieve", data=body, headers=malformed_headers)
        assert response.status_code == 404, body
        assert response.json()["detail"]["code"] == "no_such_transfer", body

    # Unauthenticated malformed requests still return 401.
    assert client.post("/api/transfers/retrieve", data="not json").status_code == 401

    for entry in STORE.entries.values():
        entry["expires_at"] = 0
    expired = client.post("/api/transfers/retrieve", json={"phrase": phrase}, headers=headers)
    assert expired.status_code == 404
    assert expired.json()["detail"]["code"] == "no_such_transfer", "expired and unknown share one detail"
    STORE.entries.clear()

    # Request models validate the wire contract.
    assert CreateBody.model_validate_json('{"scope": "snapshot", "data": {}}').scope == "snapshot"
    for bad in ('{"scope": "workspace", "data": {}}', '{"scope": "conversation"}'):
        try:
            CreateBody.model_validate_json(bad)
            raise AssertionError(f"accepted {bad}")
        except ValidationError:
            pass


# --- Request-body buffering bounds ----------------------------------------------
async def _buffer_checks():
    class FakeRequest:
        def __init__(self, headers, chunks):
            self.headers = headers
            self._chunks = chunks

        async def stream(self):
            for chunk in self._chunks:
                yield chunk

    # Content-Length fast path rejects before streaming.
    big = b"x" * 9
    req = FakeRequest({"content-length": "9"}, [big])
    try:
        await _read_limited_body(req, 8)
        raise AssertionError("content-length overflow accepted")
    except HTTPException as exc:
        assert exc.status_code == 413

    # Chunked body is rejected once the accumulated bytes cross the limit.
    req2 = FakeRequest({}, [b"xxxx", b"xxxxx"])
    try:
        await _read_limited_body(req2, 8)
        raise AssertionError("chunked overflow accepted")
    except HTTPException as exc:
        assert exc.status_code == 413

    # A body that stays within the limit is returned intact.
    req3 = FakeRequest({"content-length": "5"}, [b"hello"])
    assert await _read_limited_body(req3, 8) == b"hello"


async def main():
    await _store_checks()
    await _endpoint_checks()
    await _buffer_checks()
    print("transfers selfcheck OK")


if __name__ == "__main__":
    asyncio.run(main())
