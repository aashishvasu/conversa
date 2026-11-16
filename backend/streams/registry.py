"""Process-local registry of detached streams: one task and one event log per browser-chosen id."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from streams.log import EventLog

Producer = Callable[[EventLog], Awaitable[None]]


@dataclass(eq=False)
class Stream:
    id: str
    log: EventLog = field(default_factory=EventLog)
    task: asyncio.Task | None = None
    status: str = "running"
    error: BaseException | None = None
    finished_at: float | None = None
    owner: Any = None


class Registry:
    def __init__(self, ttl_seconds: float, max_finished: int | None = None, now: Callable[[], float] = time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.max_finished = max_finished
        self._now = now
        self._streams: dict[str, Stream] = {}

    def start(self, stream_id: str, produce: Producer, owner: Any = None, log: EventLog | None = None) -> tuple[Stream, bool]:
        self.evict()
        existing = self._streams.get(stream_id)
        if existing is not None:
            return existing, False
        stream = Stream(id=stream_id, owner=owner, log=log if log is not None else EventLog())
        self._streams[stream_id] = stream
        self._launch(stream, produce)
        return stream, True

    def restart(self, stream_id: str, produce: Producer) -> Stream:
        stream = self._streams[stream_id]
        if stream.status == "running":
            raise RuntimeError(f"stream {stream_id} is still running")
        stream.log.reopen()
        self._launch(stream, produce)
        return stream

    def get(self, stream_id: str) -> Stream | None:
        self.evict()
        return self._streams.get(stream_id)

    async def cancel(self, stream_id: str) -> None:
        stream = self._streams.get(stream_id)
        if stream is None or stream.task is None or stream.task.done():
            return
        stream.task.cancel()
        await asyncio.wait({stream.task})
        if stream.finished_at is None:
            stream.status = "cancelled"
            stream.finished_at = self._now()
            stream.log.close()

    async def forget(self, stream_id: str) -> None:
        await self.cancel(stream_id)
        self._streams.pop(stream_id, None)

    def evict(self) -> None:
        finished = sorted(((s.finished_at, s) for s in self._streams.values() if s.finished_at is not None), key=lambda pair: pair[0])
        cutoff = self._now() - self.ttl_seconds
        expired = [s for finished_at, s in finished if finished_at < cutoff]
        kept = [s for _, s in finished][len(expired):]
        if self.max_finished is not None and len(kept) > self.max_finished:
            expired += kept[: len(kept) - self.max_finished]
        for stream in expired:
            del self._streams[stream.id]

    def active_count(self) -> int:
        return sum(s.status == "running" for s in self._streams.values())

    def _launch(self, stream: Stream, produce: Producer) -> None:
        stream.status, stream.error, stream.finished_at = "running", None, None
        stream.task = asyncio.create_task(self._run(stream, produce))

    async def _run(self, stream: Stream, produce: Producer) -> None:
        try:
            await produce(stream.log)
            stream.status = "done"
        except asyncio.CancelledError:
            stream.status = "cancelled"
            raise
        except Exception as exc:
            stream.status, stream.error = "error", exc
        finally:
            stream.finished_at = self._now()
            stream.log.close()
