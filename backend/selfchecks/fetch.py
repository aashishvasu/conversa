"""Selfcheck: python -m selfchecks.fetch"""

import asyncio

from tools.fetch import FetchError, PageCache, assert_public_target, canonicalize, is_private_ip, view

for blocked in (
    "127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1", "169.254.169.254",
    "0.0.0.0", "100.64.0.1", "::1", "fc00::1", "fe80::1", "::ffff:10.0.0.1",
    "not-an-ip",
):
    assert is_private_ip(blocked), blocked
for public in ("8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111"):
    assert not is_private_ip(public), public


async def _guard_checks():
    for bad in (
        "file:///etc/passwd",
        "http://localhost:8000/",
        "http://foo.localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "https://10.0.0.5/admin",
    ):
        try:
            await assert_public_target(bad)
        except FetchError:
            continue
        raise AssertionError(f"should have been blocked: {bad}")
    await assert_public_target("https://example.com/ok")


asyncio.run(_guard_checks())

same = {
    canonicalize("https://Example.com/a/b/?b=2&a=1#frag"),
    canonicalize("https://example.com/a/b?a=1&b=2"),
    canonicalize("https://example.com/a/b/?a=1&utm_source=x&b=2&fbclid=y"),
}
assert len(same) == 1, same
assert canonicalize("https://example.com/") == "https://example.com/"


async def _cache_checks():
    now = [0.0]
    calls = []

    async def fake_fetch(url, raw):
        calls.append((url, raw))
        await asyncio.sleep(0.01)
        return {
            "url": url,
            "title": "title",
            "kind": "html" if raw else "article",
            "content": "# Alpha\nalpha alpha\n\n# Beta\nbeta beta",
        }

    cache = PageCache(fake_fetch, clock=lambda: now[0], ttl=10, max_chars=1000)
    alpha, beta, again = await asyncio.gather(
        cache.get("https://Example.com/page/?b=2&a=1#fragment"),
        cache.get("https://example.com/page?a=1&b=2"),
        cache.get("https://example.com/page/?a=1&b=2"),
    )
    assert len(calls) == 1, calls
    assert alpha["content"].startswith("# Alpha") and alpha == beta == again
    assert cache.inflight == {}, cache.inflight

    raw = await cache.get("https://example.com/page?a=1&b=2", True)
    assert len(calls) == 2 and raw["kind"] == "html" and len(cache.pages) == 2, (calls, cache.pages)

    now[0] = 10.0
    await cache.get("https://example.com/page?a=1&b=2")
    assert len(calls) == 3, calls

    async def sized_fetch(url, raw):
        return {"url": url, "title": None, "kind": "text", "content": url[-1] * 10}

    lru = PageCache(sized_fetch, ttl=100, max_chars=25)
    await lru.get("https://example.com/a")
    await lru.get("https://example.com/b")
    await lru.get("https://example.com/a")
    await lru.get("https://example.com/c")
    assert ("https://example.com/a", False) in lru.pages, lru.pages
    assert ("https://example.com/b", False) not in lru.pages, lru.pages
    assert lru.size <= 25, lru.size

    oversized_calls = 0

    async def oversized_fetch(url, raw):
        nonlocal oversized_calls
        oversized_calls += 1
        await asyncio.sleep(0.01)
        return await sized_fetch(url, raw)

    oversized = PageCache(oversized_fetch, ttl=100, max_chars=5)
    await asyncio.gather(oversized.get("https://example.com/z"), oversized.get("https://example.com/z"))
    assert oversized_calls == 1, oversized_calls
    assert oversized.pages == {} and oversized.size == 0, oversized.pages

    failures = 0

    async def failing_fetch(url, raw):
        nonlocal failures
        failures += 1
        await asyncio.sleep(0.01)
        raise FetchError("unavailable")

    failed = PageCache(failing_fetch, ttl=100)
    errors = await asyncio.gather(
        failed.get("https://example.com/fail"),
        failed.get("https://example.com/fail"),
        return_exceptions=True,
    )
    assert failures == 1 and all(isinstance(error, FetchError) for error in errors), (failures, errors)
    try:
        await failed.get("https://example.com/fail")
    except FetchError:
        pass
    else:
        raise AssertionError("failed fetch was returned")
    assert failures == 2 and failed.pages == {} and failed.inflight == {}, (failures, failed.pages, failed.inflight)


asyncio.run(_cache_checks())

page = {"url": "https://example.com/doc", "title": None, "kind": "article", "content": "# Alpha\n" + "x" * 100 + "\n\n# Beta\n" + "y" * 100}

first = view(page, None, False, 0, budget=120)
assert first["offset"] == 0 and first["totalChars"] == len(page["content"]) and first["nextOffset"] == 120, first
rest = view(page, None, False, 120, budget=1000)
assert rest["nextOffset"] is None and rest["content"] == page["content"][120:], rest
assert view(page, "beta", False, 0)["content"] == "# Beta\n" + "y" * 100, view(page, "beta", False, 0)
assert view(page, "beta", True, 0)["content"] == page["content"], "raw ignores topic"

print("fetch selfcheck OK")
