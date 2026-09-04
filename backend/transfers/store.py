"""Process-memory store for transient transfer blobs.

An entry is the UTF-8 payload bytes keyed by its phrase, expiring after a fixed TTL.
There is no timer: creation prunes expired entries up front, and retrieval drops an
expired entry lazily, so an expired phrase is indistinguishable from an unknown one.
A process restart clears the store, which is why multi-worker or replicated
deployments need a shared TTL store (see DEVELOPMENT.md).
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone

from transfers import phrases

TRANSFER_TTL = float(os.environ.get("TRANSFER_TTL_SECONDS", "3600"))
TRANSFER_MAX_ENTRY_BYTES = int(os.environ.get("TRANSFER_MAX_ENTRY_BYTES", "10000000"))
TRANSFER_MAX_TOTAL_BYTES = int(os.environ.get("TRANSFER_MAX_TOTAL_BYTES", "50000000"))
TRANSFER_MAX_ENTRIES = int(os.environ.get("TRANSFER_MAX_ENTRIES", "32"))


class EntryTooLarge(Exception):
    pass


class CapacityFull(Exception):
    pass


class Store:
    def __init__(
        self,
        ttl=TRANSFER_TTL,
        max_entry_bytes=TRANSFER_MAX_ENTRY_BYTES,
        max_total_bytes=TRANSFER_MAX_TOTAL_BYTES,
        max_entries=TRANSFER_MAX_ENTRIES,
        now=time.time,
    ):
        self.ttl = ttl
        self.max_entry_bytes = max_entry_bytes
        self.max_total_bytes = max_total_bytes
        self.max_entries = max_entries
        self.now = now
        self.entries = {}
        self._lock = asyncio.Lock()

    def _prune(self):
        now = self.now()
        for phrase in [p for p, e in self.entries.items() if e["expires_at"] <= now]:
            del self.entries[phrase]

    def _total_bytes(self):
        return sum(len(e["payload"]) for e in self.entries.values())

    async def create(self, scope, data):
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        size = len(payload)
        if size > self.max_entry_bytes:
            raise EntryTooLarge()
        async with self._lock:
            self._prune()
            if len(self.entries) >= self.max_entries:
                raise CapacityFull()
            if self._total_bytes() + size > self.max_total_bytes:
                raise CapacityFull()
            phrase = phrases.generate()
            while phrase in self.entries:
                phrase = phrases.generate()
            expires_at = self.now() + self.ttl
            self.entries[phrase] = {"scope": scope, "payload": payload, "expires_at": expires_at}
        return {
            "phrase": phrase,
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
            "bytes": size,
        }

    async def retrieve(self, phrase):
        key = phrases.normalize(phrase)
        if not key:
            return None
        async with self._lock:
            entry = self.entries.get(key)
            if not entry or entry["expires_at"] <= self.now():
                if entry:
                    del self.entries[key]
                return None
            data = json.loads(entry["payload"].decode("utf-8"))
            return {"scope": entry["scope"], "data": data}


STORE = Store()
