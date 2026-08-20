"""Fetch a URL and return readable markdown.

This opens a caller-supplied URL from inside the network, so assert_public_target() gates every request and runs again on each redirect hop.

Extraction pipeline, SSRF guard, URL canonicalization and Wayback fallback are ported from magpi (MIT, grainologic/magpi).

One generic handler, no registry.
A GitHub repo page yields its README through the HTML path, and raw.githubusercontent.com arrives as text/plain, so the content-type branch covers both.
Add a registry once a second handler earns its place, with a bot-blocked or SPA-rendered site as the trigger.
"""

import asyncio
import io
import ipaddress
import json
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
import pypdf
import trafilatura

from topic import match_topic

UA = "Mozilla/5.0 (compatible; conversa/1.0)"
MAX_BYTES = 5 * 1024 * 1024  # response cap; 5MB of text is already absurd for a prompt
MAX_CONTENT = 500_000  # extracted markdown kept, before topic selection
TOPIC_BUDGET = 40_000  # characters returned when a topic is given
REQUEST_TIMEOUT = 20
DNS_TIMEOUT = 5
MAX_REDIRECTS = 5
FETCH_DEADLINE = 90  # whole call, including a Wayback retry
PDF_MAX_PAGES = 100  # pypdf is pure Python, and a thesis-length PDF costs seconds per hundred pages
# Statuses worth a second look in the archive: gone, blocked, or geo-refused.
WAYBACK_STATUSES = {403, 404, 410, 451}

# Carrier-grade NAT.
# Python's is_private covers it from 3.13; spelled out so the guard behaves the same on 3.12.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|msclkid$|mc_cid$|mc_eid$)")
# Docs generators leave a permalink pilcrow inside every heading; it costs tokens and blurs heading matching in topic.py.
_ANCHOR = re.compile(r"\[¶\]\([^)]*\)")
# The same generators leave the bare pilcrow on the <h1>, which reaches us as a trailing character on the title.
_TITLE_TAIL = re.compile(r"[¶#\s]+$")


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def is_private_ip(ip):
    """True for loopback, link-local, private, CGNAT, reserved, multicast, and unspecified addresses.

    Link-local matters most: 169.254.169.254 is the cloud metadata endpoint. An address that fails to parse is treated as private.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    addr = getattr(addr, "ipv4_mapped", None) or addr  # ::ffff:10.0.0.1 is 10.0.0.1
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or (addr.version == 4 and addr in _CGNAT)
    )


async def assert_public_target(url):
    """Raise unless `url` names a public http(s) address.

    Checks the scheme, the literal host, and every address the name resolves to.

    Known gap: resolve-then-connect, so a name answering with a public address here and a private one microseconds later (DNS rebinding) gets through.
    Closing that means resolving once and dialling the pinned IP with an explicit Host header and SNI, from a custom transport.
    Worth building if this endpoint is ever reachable by more than one trusted password holder.
    """
    u = httpx.URL(str(url))
    if u.scheme not in ("http", "https"):
        raise FetchError(f"only http and https are fetchable, not {u.scheme!r}")
    host = u.host
    if not host:
        raise FetchError("no host in URL")
    if host == "localhost" or host.endswith(".localhost"):
        raise FetchError(f"blocked: {host} is loopback")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # a name, resolved below
    else:
        if is_private_ip(host):
            raise FetchError(f"blocked: {host} is a private address")
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None), DNS_TIMEOUT)
    except Exception:
        return  # resolution failed; the request itself reports the real error
    if any(is_private_ip(i[4][0]) for i in infos):
        raise FetchError(f"blocked: {host} resolves to a private address")


def canonicalize(url):
    """One URL, one form: fragment dropped, tracking params dropped, query sorted, host lowercased, trailing slash stripped.

    Page variants collapse to a single key, so a run fetches each page once however many searches surfaced it.
    """
    u = urlsplit(url)
    query = sorted(
        (k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not _TRACKING.match(k)
    )
    path = u.path.rstrip("/") if len(u.path) > 1 else u.path
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), path, urlencode(query), ""))


async def _get(client, url, headers=None):
    """GET with the guard applied to every hop, returning (response, body).

    Redirects are followed by hand: httpx follows them internally, which would let hop two land on a private address after hop one passed the check.
    """
    for _ in range(MAX_REDIRECTS):
        await assert_public_target(url)
        request = client.build_request("GET", url, headers={"user-agent": UA, **(headers or {})})
        try:
            response = await client.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as err:
            # Every request routes through here, so transport failures become FetchError in one place.
            # Without this a bad hostname or a refused connection escapes as an httpx exception and the route answers 500.
            raise FetchError(f"could not reach {url}: {err}")
        try:
            location = response.headers.get("location")
            if response.is_redirect and location:
                url = response.url.join(location)
                continue
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code} for {url}", response.status_code)
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FetchError(f"response over {MAX_BYTES} bytes from {url}")
            return response, body
        finally:
            await response.aclose()
    raise FetchError(f"more than {MAX_REDIRECTS} redirects from {url}")


def _pdf_text(body):
    try:
        reader = pypdf.PdfReader(io.BytesIO(body))
        pages = reader.pages[:PDF_MAX_PAGES]
        text = "\n\n".join(page.extract_text() or "" for page in pages).strip()
    except Exception as err:
        raise FetchError(f"could not read the PDF: {err}")
    if not text:
        raise FetchError("PDF has no extractable text, so it is probably scanned images")
    if len(reader.pages) > PDF_MAX_PAGES:
        text += f"\n\n(truncated at {PDF_MAX_PAGES} of {len(reader.pages)} pages)"
    return text


def _extract_sync(response, body, url):
    """(kind, title, content) from a fetched response, dispatched on content type."""
    content_type = response.headers.get("content-type", "")
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        return "pdf", None, _pdf_text(body)

    if "html" in content_type or body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        # Bytes, not str: trafilatura reads the meta charset, which is the only declaration many pages carry.
        markdown = trafilatura.extract(
            body, output_format="markdown", include_links=True, include_tables=True
        ) or trafilatura.extract(  # the precision default discards short pages whole
            body, output_format="markdown", include_links=True, favor_recall=True
        )
        if not markdown:
            raise FetchError(f"no readable content in {url}")
        meta = trafilatura.extract_metadata(body)
        title = _TITLE_TAIL.sub("", meta.title) if meta and meta.title else None
        return "article", title, _ANCHOR.sub("", markdown)

    text = body.decode(response.charset_encoding or "utf-8", errors="replace")
    if "json" in content_type:
        try:
            return "json", None, json.dumps(json.loads(text), indent=2)
        except ValueError:
            pass  # not actually JSON; serve it raw
    return "text", None, text


async def _extract(response, body, url):
    """Extraction off the event loop.

    Both heavy paths are pure Python CPU work: pypdf on a hundred pages, trafilatura on a multi-megabyte page.
    Left inline they stall every other request in the process, which the per-fetch deadline does nothing about.
    """
    return await asyncio.to_thread(_extract_sync, response, body, url)


async def _wayback(client, url, original):
    """Last look for a page that is gone or blocking us.

    Re-raises `original` when the archive has nothing either, since the live failure is the one worth reporting.
    """
    probe = f"https://archive.org/wayback/available?url={quote(url)}"
    try:
        _, body = await _get(client, probe)
        snapshot = (json.loads(body).get("archived_snapshots") or {}).get("closest") or {}
        if not snapshot.get("available"):
            raise original
        response, snap_body = await _get(client, snapshot["url"])
        kind, title, content = await _extract(response, snap_body, snapshot["url"])
    except FetchError:
        raise original
    note = f"(Wayback snapshot {snapshot.get('timestamp')}; the live page returned HTTP {original.status})"
    return kind, title, f"{note}\n\n{content}"


async def _fetch(url, topic=None):
    canonical = canonicalize(url)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            response, body = await _get(client, canonical)
            kind, title, content = await _extract(response, body, canonical)
        except FetchError as err:
            if err.status not in WAYBACK_STATUSES:
                raise
            kind, title, content = await _wayback(client, canonical, err)

    return {"url": canonical, "title": title, "kind": kind, "content": select(content[:MAX_CONTENT], topic)}


def select(content, topic):
    """The sections of `content` answering `topic`, or the head of it when nothing matches.

    Separate from fetch() so a caller holding a cached page can select against a different topic without refetching.
    """
    if not topic:
        return content
    return match_topic(content, topic, TOPIC_BUDGET) or content[:TOPIC_BUDGET]


async def fetch(url, topic=None):
    """Fetch `url` as markdown. With `topic`, return the sections that answer it.

    The deadline covers the whole call: REQUEST_TIMEOUT bounds one hop, and a redirect chain into a Wayback retry is several.
    """
    try:
        return await asyncio.wait_for(_fetch(url, topic), FETCH_DEADLINE)
    except asyncio.TimeoutError:
        raise FetchError(f"gave up on {url} after {FETCH_DEADLINE}s")


if __name__ == "__main__":  # self-check: python fetcher.py
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
