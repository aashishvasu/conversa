"""Selfcheck: python -m selfchecks.streams"""

import asyncio
from contextlib import suppress

from streams import EventLog, LogClosed, Registry, Stream


async def collect(log: EventLog, after: int = 0) -> list[tuple[int | None, dict | None]]:
    return [(seq, event) async for seq, event in log.tail(after)]


async def finished(stream: Stream) -> None:
    assert stream.task is not None
    await asyncio.wait({stream.task})


def present(registry: Registry, stream_id: str) -> Stream:
    stream = registry.get(stream_id)
    assert stream is not None, stream_id
    return stream


def gated_producer(count: int, gate: asyncio.Event | None = None, ran: list | None = None):
    async def produce(log: EventLog) -> None:
        if ran is not None:
            ran.append(log)
        for i in range(count):
            if gate is not None and i == 1:
                await gate.wait()
            log.append({"n": i})
            await asyncio.sleep(0)

    return produce


async def replay_checks():
    registry = Registry(ttl_seconds=60)
    stream, created = registry.start("a", gated_producer(5))
    assert created
    early = asyncio.create_task(collect(stream.log))
    await finished(stream)
    late = await collect(stream.log)
    assert await early == late
    assert [seq for seq, _ in late] == list(range(1, 6))
    assert [e for _, e in late] == [{"n": i} for i in range(5)]
    assert stream.status == "done" and stream.log.closed and stream.finished_at is not None

    after = await collect(stream.log, after=2)
    assert after == late[2:]
    assert await collect(stream.log, after=len(stream.log)) == []

    with suppress(LogClosed):
        stream.log.append({"n": 99})
        raise AssertionError("append after close must fail")


async def supplied_log_checks():
    registry = Registry(ttl_seconds=60)
    log = EventLog()
    log.append({"seed": True})
    stream, _ = registry.start("seeded", gated_producer(1), log=log)
    await finished(stream)
    events = [event for _, event in await collect(stream.log)]
    assert events == [{"seed": True}, {"n": 0}]
    assert stream.log.since(1) == events[1:]

async def abandoned_tail_checks():
    registry = Registry(ttl_seconds=60)
    gate = asyncio.Event()
    stream, _ = registry.start("a", gated_producer(4, gate))

    abandoned = stream.log.tail()
    assert (await anext(abandoned))[0] == 1
    await abandoned.aclose()

    cancelled = asyncio.create_task(collect(stream.log))
    await asyncio.sleep(0)
    cancelled.cancel()
    with suppress(asyncio.CancelledError):
        await cancelled

    gate.set()
    await finished(stream)
    assert stream.status == "done"
    assert [seq for seq, _ in await collect(stream.log)] == [1, 2, 3, 4]


async def wakeup_ordering_checks():
    log = EventLog()
    order = []

    async def reader():
        async for seq, _ in log.tail():
            order.append(("received", seq))

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    for seq in (1, 2, 3):
        order.append(("appended", log.append({"n": seq})))
        await asyncio.sleep(0)
    log.close()
    await task
    assert order == [(kind, seq) for seq in (1, 2, 3) for kind in ("appended", "received")], order


async def idle_checks():
    log = EventLog()
    tail = log.tail(idle=0.01)
    assert await asyncio.wait_for(anext(tail), 1) == (None, None)
    log.append({"n": 1})
    assert await asyncio.wait_for(anext(tail), 1) == (1, {"n": 1})
    log.close()
    with suppress(StopAsyncIteration):
        await asyncio.wait_for(anext(tail), 1)
        raise AssertionError("tail must end once the log is closed and drained")


async def start_idempotence_checks():
    registry = Registry(ttl_seconds=60)
    ran = []
    first, created = registry.start("a", gated_producer(1, ran=ran))
    second, again = registry.start("a", gated_producer(1, ran=ran))
    assert created and not again and second is first
    await finished(first)
    assert len(ran) == 1 and len(first.log) == 1


async def cancel_checks():
    registry = Registry(ttl_seconds=60)
    stopped = asyncio.Event()
    unwound_while_open = []

    async def produce(log: EventLog) -> None:
        log.append({"n": 0})
        try:
            await stopped.wait()
            log.append({"n": "unreachable"})
        except asyncio.CancelledError:
            unwound_while_open.append(not log.closed)
            log.append({"kind": "cancelled"})
            raise

    immediate, _ = registry.start("immediate", produce)
    await registry.cancel("immediate")
    assert immediate.status == "cancelled" and immediate.log.closed and immediate.finished_at is not None
    assert len(immediate.log) == 0 and registry.active_count() == 0

    stream, _ = registry.start("a", produce)
    await asyncio.sleep(0)
    assert registry.active_count() == 1
    await registry.cancel("a")
    assert stream.status == "cancelled" and stream.log.closed
    assert unwound_while_open == [True]
    assert [e for _, e in await collect(stream.log)] == [{"n": 0}, {"kind": "cancelled"}]
    assert registry.active_count() == 0

    await registry.cancel("a")
    await registry.cancel("unknown")
    await registry.forget("unknown")

    running, _ = registry.start("b", produce)
    await asyncio.sleep(0)
    await registry.forget("b")
    assert running.status == "cancelled" and registry.get("b") is None


async def error_checks():
    registry = Registry(ttl_seconds=60)
    failure = ValueError("producer failed")

    async def produce(log: EventLog) -> None:
        log.append({"n": 0})
        raise failure

    stream, _ = registry.start("a", produce)
    await finished(stream)
    assert stream.status == "error" and stream.error is failure and stream.log.closed
    assert len(stream.log) == 1


async def evict_checks():
    clock = [1000.0]
    registry = Registry(ttl_seconds=30, max_finished=2, now=lambda: clock[0])
    hold = asyncio.Event()

    async def held(log: EventLog) -> None:
        await hold.wait()

    running, _ = registry.start("running", held)
    for name in ("old", "mid", "new", "newest"):
        stream, _ = registry.start(name, gated_producer(1))
        await finished(stream)
        clock[0] += 1

    assert registry.get("running") is running
    assert registry.get("old") is None, "beyond max_finished, oldest first"
    kept = [n for n in ("mid", "new", "newest") if registry.get(n) is not None]
    assert len(kept) == registry.max_finished and kept == ["new", "newest"]

    newest_finished = present(registry, "newest").finished_at
    assert newest_finished is not None
    clock[0] = newest_finished + registry.ttl_seconds - 0.5
    registry.evict()
    assert registry.get("newest") is not None
    clock[0] = newest_finished + registry.ttl_seconds + 0.5
    registry.evict()
    assert registry.get("new") is None and registry.get("newest") is None

    clock[0] += registry.ttl_seconds * 10
    registry.evict()
    assert registry.get("running") is running and running.status == "running"

    unbounded = Registry(ttl_seconds=30, now=lambda: clock[0])
    for name in ("a", "b", "c"):
        stream, _ = unbounded.start(name, gated_producer(1))
        await finished(stream)
    assert all(unbounded.get(n) is not None for n in ("a", "b", "c"))

    hold.set()
    await finished(running)


async def restart_checks():
    registry = Registry(ttl_seconds=60)

    async def failing(log: EventLog) -> None:
        log.append({"n": 0})
        log.append({"n": 1})
        raise RuntimeError("first attempt")

    stream, _ = registry.start("a", failing)
    await finished(stream)
    assert stream.status == "error"
    before = len(stream.log)

    restarted = registry.restart("a", gated_producer(2))
    assert restarted is stream and not stream.log.closed and stream.status == "running" and stream.error is None
    await finished(stream)
    assert stream.status == "done" and stream.log.closed
    assert [seq for seq, _ in await collect(stream.log)] == list(range(1, before + 3))
    assert [seq for seq, _ in await collect(stream.log, after=before)] == [before + 1, before + 2]


async def main():
    await replay_checks()
    await supplied_log_checks()
    await abandoned_tail_checks()
    await wakeup_ordering_checks()
    await idle_checks()
    await start_idempotence_checks()
    await cancel_checks()
    await error_checks()
    await evict_checks()
    await restart_checks()
    print("streams selfcheck OK")


if __name__ == "__main__":
    asyncio.run(main())
