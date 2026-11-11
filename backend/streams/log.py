"""Append-only event log that wakes its readers on every append."""

import asyncio
from collections.abc import AsyncGenerator


class LogClosed(Exception):
    pass


class EventLog:
    def __init__(self):
        self._events: list[dict] = []
        self._closed = False
        self._waiters: set[asyncio.Future] = set()

    def __len__(self) -> int:
        return len(self._events)

    @property
    def closed(self) -> bool:
        return self._closed

    def append(self, event: dict) -> int:
        if self._closed:
            raise LogClosed("append to a closed event log")
        self._events.append(event)
        self._wake()
        return len(self._events)

    def close(self) -> None:
        self._closed = True
        self._wake()

    def reopen(self) -> None:
        self._closed = False

    def _wake(self) -> None:
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters.clear()

    async def tail(self, after: int = 0, idle: float | None = None) -> AsyncGenerator[tuple[int | None, dict | None]]:
        """Yield `(seq, event)` after `after` until the log is closed and drained; `(None, None)` after `idle` silent seconds."""
        position = after
        while True:
            while position < len(self._events):
                position += 1
                yield position, self._events[position - 1]
            if self._closed:
                return
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.add(waiter)
            try:
                if idle is None:
                    await waiter
                    continue
                try:
                    async with asyncio.timeout(idle):
                        await waiter
                except TimeoutError:
                    yield None, None
            finally:
                self._waiters.discard(waiter)
