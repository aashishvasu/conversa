"""Selfcheck: python -m selfchecks.fetcher"""

import asyncio

from research.fetcher import FetchError, assert_public_target, canonicalize, is_private_ip

# The guard is the security boundary, so it gets the asserts.
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
    await assert_public_target("https://example.com/ok")  # public names pass

asyncio.run(_guard_checks())

# Canonicalization: variants of one page collapse to one key.
same = {
    canonicalize("https://Example.com/a/b/?b=2&a=1#frag"),
    canonicalize("https://example.com/a/b?a=1&b=2"),
    canonicalize("https://example.com/a/b/?a=1&utm_source=x&b=2&fbclid=y"),
}
assert len(same) == 1, same
assert canonicalize("https://example.com/") == "https://example.com/", "root slash kept"

print("fetcher selfcheck OK")
