"""Fetch public URLs into readable markdown and retain recent page extracts."""

import asyncio
import io
import ipaddress
import json
import os
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx2 as httpx
import pypdf
import trafilatura

from tools.topic import match_topic

UA = "Mozilla/5.0 (compatible; conversa/1.0)"
MAX_BYTES = 5 * 1024 * 1024
MAX_CONTENT = 500_000
MAX_CACHE_CHARS = 2_000_000
TOPIC_BUDGET = 40_000
REQUEST_TIMEOUT = 20
DNS_TIMEOUT = 5
MAX_REDIRECTS = 5
FETCH_DEADLINE = 90
PDF_MAX_PAGES = 100
WAYBACK_STATUSES = {403, 404, 410, 451}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|msclkid$|mc_cid$|mc_eid$)")
_ANCHOR = re.compile(r"\[¶\]\([^)]*\)")
_TITLE_TAIL = re.compile(r"[¶#\s]+$")


def _cache_ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("FETCH_CACHE_TTL_SECONDS", "1800")))
    except ValueError:
        return 1800.0


FETCH_CACHE_TTL_SECONDS = _cache_ttl()


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class FetchPolicyError(FetchError):
    """A target the app must not delegate to another fetcher."""


def is_private_ip(ip: str) -> bool:
    """Identify addresses that callers may not fetch."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True
    address = getattr(address, "ipv4_mapped", None) or address
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or (address.version == 4 and address in _CGNAT)
    )


async def assert_public_target(url: str) -> None:
    """Raise unless `url` has an HTTP(S) host resolving only to public addresses."""
    parsed = httpx.URL(str(url))
    if parsed.scheme not in ("http", "https"):
        raise FetchPolicyError(f"only http and https are fetchable, not {parsed.scheme!r}")
    host = parsed.host
    if not host:
        raise FetchPolicyError("no host in URL")
    if host == "localhost" or host.endswith(".localhost"):
        raise FetchPolicyError(f"blocked: {host} is loopback")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if is_private_ip(host):
            raise FetchPolicyError(f"blocked: {host} is a private address")
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None), DNS_TIMEOUT)
    except Exception as error:
        raise FetchPolicyError(f"could not verify public address for {host}") from error
    if any(is_private_ip(info[4][0]) for info in infos):
        raise FetchPolicyError(f"blocked: {host} resolves to a private address")


def canonicalize(url: str) -> str:
    """Normalize a URL for deduplication and cache keys."""
    parsed = urlsplit(url)
    query = sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if not _TRACKING.match(key))
    path = parsed.path.rstrip("/") if len(parsed.path) > 1 else parsed.path
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), ""))


async def _get(client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None) -> tuple[httpx.Response, bytes]:
    """Read one response, checking every redirect target before following it."""
    for _ in range(MAX_REDIRECTS):
        await assert_public_target(url)
        request = client.build_request("GET", url, headers={"user-agent": UA, **(headers or {})})
        try:
            response = await client.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as error:
            raise FetchError(f"could not reach {url}: {error}")
        try:
            location = response.headers.get("location")
            if response.is_redirect and location:
                url = str(response.url.join(location))
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


def _pdf_text(body: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(body))
        pages = reader.pages[:PDF_MAX_PAGES]
        text = "\n\n".join(page.extract_text() or "" for page in pages).strip()
    except Exception as error:
        raise FetchError(f"could not read the PDF: {error}")
    if not text:
        raise FetchError("PDF has no extractable text, so it is probably scanned images")
    if len(reader.pages) > PDF_MAX_PAGES:
        text += f"\n\n(truncated at {PDF_MAX_PAGES} of {len(reader.pages)} pages)"
    return text


def _extract_sync(response: httpx.Response, body: bytes, url: str) -> tuple[str, str | None, str]:
    content_type = response.headers.get("content-type", "")
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        return "pdf", None, _pdf_text(body)
    if "html" in content_type or body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        markdown = trafilatura.extract(body, output_format="markdown", include_links=True, include_tables=True) or trafilatura.extract(body, output_format="markdown", include_links=True, favor_recall=True)
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
            pass
    return "text", None, text


async def _extract(response: httpx.Response, body: bytes, url: str) -> tuple[str, str | None, str]:
    return await asyncio.to_thread(_extract_sync, response, body, url)


async def _wayback(client: httpx.AsyncClient, url: str, original: FetchError) -> tuple[str, str | None, str]:
    probe = f"https://archive.org/wayback/available?url={quote(url)}"
    try:
        _, body = await _get(client, probe)
        snapshot = (json.loads(body).get("archived_snapshots") or {}).get("closest") or {}
        if not snapshot.get("available"):
            raise original
        response, snap_body = await _get(client, snapshot["url"])
        kind, title, content = await _extract(response, snap_body, snapshot["url"])
    except FetchPolicyError:
        raise
    except FetchError:
        raise original
    note = f"(Wayback snapshot {snapshot.get('timestamp')}; the live page returned HTTP {original.status})"
    return kind, title, f"{note}\n\n{content}"


async def _fetch_full(url: str) -> dict[str, str | None]:
    canonical = canonicalize(url)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            response, body = await _get(client, canonical)
            kind, title, content = await _extract(response, body, canonical)
        except FetchError as error:
            if error.status not in WAYBACK_STATUSES:
                raise
            kind, title, content = await _wayback(client, canonical, error)
    return {"url": canonical, "title": title, "kind": kind, "content": content[:MAX_CONTENT]}


async def _fetch_page(url: str) -> dict[str, str | None]:
    try:
        return await asyncio.wait_for(_fetch_full(url), FETCH_DEADLINE)
    except asyncio.TimeoutError:
        raise FetchError(f"gave up on {url} after {FETCH_DEADLINE}s")


def select(content: str, topic: str | None) -> str:
    """Select the content relevant to `topic`, or the content head when unmatched."""
    if not topic:
        return content
    return match_topic(content, topic, TOPIC_BUDGET) or content[:TOPIC_BUDGET]


class PageCache:
    """Process-local LRU cache of full extracted pages."""
    def __init__(self, fetch: Callable[[str], Awaitable[dict[str, str | None]]] | None = None, clock: Callable[[], float] | None = None, ttl: float | None = None, max_chars: int = MAX_CACHE_CHARS):
        self.pages: OrderedDict[str, tuple[dict[str, str | None], float]] = OrderedDict()
        self.inflight: dict[str, asyncio.Task[dict[str, str | None]]] = {}
        self.fetches = 0
        self.size = 0
        self._fetch = fetch or _fetch_page
        self._clock = clock or time.monotonic
        self._ttl = FETCH_CACHE_TTL_SECONDS if ttl is None else ttl
        self._max_chars = max_chars

    async def get(self, url: str, topic: str | None = None) -> dict[str, str | None]:
        canonical = canonicalize(url)
        page = self._cached(canonical)
        if page is None:
            task = self.inflight.get(canonical)
            if task is None:
                self.fetches += 1
                task = asyncio.create_task(self._load(canonical))
                self.inflight[canonical] = task
                task.add_done_callback(lambda done, key=canonical: self._finished(key, done))
            page = await asyncio.shield(task)
        return {**page, "content": select(str(page["content"]), topic)}

    async def _load(self, canonical: str) -> dict[str, str | None]:
        page = await self._fetch(canonical)
        self._store(canonical, page)
        return page

    def _finished(self, canonical: str, task: asyncio.Task) -> None:
        if self.inflight.get(canonical) is task:
            del self.inflight[canonical]
        if not task.cancelled():
            task.exception()

    def _cached(self, canonical: str) -> dict[str, str | None] | None:
        entry = self.pages.get(canonical)
        if entry is None:
            return None
        page, expires_at = entry
        if expires_at <= self._clock():
            self.size -= len(str(page["content"]))
            del self.pages[canonical]
            return None
        self.pages.move_to_end(canonical)
        return page

    def _store(self, canonical: str, page: dict[str, str | None]) -> None:
        content_size = len(str(page["content"]))
        if self._ttl <= 0 or content_size > self._max_chars:
            return
        old = self.pages.pop(canonical, None)
        if old is not None:
            self.size -= len(str(old[0]["content"]))
        self.pages[canonical] = (page, self._clock() + self._ttl)
        self.size += content_size
        while self.size > self._max_chars:
            _, (evicted, _) = self.pages.popitem(last=False)
            self.size -= len(str(evicted["content"]))


PAGE_CACHE = PageCache()


async def fetch(url: str, topic: str | None = None) -> dict[str, str | None]:
    """Fetch `url` and select content for this call's topic."""
    return await PAGE_CACHE.get(url, topic)
