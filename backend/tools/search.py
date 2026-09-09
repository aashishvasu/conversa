"""App-configured web search backends."""

import logging
import os
from collections.abc import Awaitable, Callable

import httpx2 as httpx

from tools.fetch import REQUEST_TIMEOUT, canonicalize

BLOCKED_DOMAINS = [
    "geeksforgeeks.org", "codemia.io", "fixdevs.com", "coddy.tech", "w3schools.com",
    "tutorialspoint.com", "javatpoint.com", "medium.com", "goodreads.com", "quora.com",
]

EXA_API_KEY = os.environ.get("EXA_API_KEY")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY")
SEARXNG_URL = (os.environ.get("SEARXNG_URL") or "").rstrip("/")
logger = logging.getLogger(__name__)


SearchFinder = Callable[[str, int], Awaitable[list[dict[str, str | None]]]]


def is_blocked(url: str) -> bool:
    """Return whether `url` belongs to a blocked source domain."""
    host = (httpx.URL(url).host or "").removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in BLOCKED_DOMAINS)


def _hits(results: list[dict[str, str | None]] | None) -> list[dict[str, str | None]]:
    """Normalize a search API result list, dropping rows without a URL."""
    return [{"title": result.get("title"), "url": result["url"]} for result in results or [] if result.get("url")]


async def _search_exa(query: str, limit: int) -> list[dict[str, str | None]]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": EXA_API_KEY},
            json={"query": query, "numResults": limit * 3},
        )
    response.raise_for_status()
    return _hits(response.json().get("results"))


async def _search_brave(query: str, limit: int) -> list[dict[str, str | None]]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"},
            params={"q": query, "count": min(limit * 3, 20)},
        )
    response.raise_for_status()
    return _hits((response.json().get("web") or {}).get("results"))


async def _search_searxng(query: str, limit: int) -> list[dict[str, str | None]]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(f"{SEARXNG_URL}/search", params={"q": query, "format": "json"})
    response.raise_for_status()
    return _hits(response.json().get("results"))[:limit * 3]


def app_finders() -> list[SearchFinder]:
    """Return configured app finders in Exa, Brave, SearXNG order."""
    keyed = ((EXA_API_KEY, _search_exa), (BRAVE_API_KEY, _search_brave), (SEARXNG_URL, _search_searxng))
    return [finder for key, finder in keyed if key]


def filter_hits(hits: list[dict[str, str | None]], limit: int) -> list[dict[str, str | None]]:
    """Canonicalize, block, and deduplicate source candidates."""
    seen, out = set(), []
    for hit in hits:
        canonical = canonicalize(str(hit["url"]))
        if canonical in seen or is_blocked(canonical):
            continue
        seen.add(canonical)
        out.append({"title": hit.get("title"), "url": canonical})
    return out[:limit]


async def search(query: str, limit: int = 8) -> list[dict[str, str | None]] | None:
    """Search configured app finders, returning None when none are configured.

    A successful finder, including one with no acceptable sources, ends the fallback chain.
    """
    attempts = app_finders()
    if not attempts:
        return None
    error = None
    for finder in attempts:
        name = finder.__name__.removeprefix("_search_")
        try:
            hits = await finder(query, limit)
            logger.info("web search via %s", name)
            return filter_hits(hits, limit)
        except Exception as err:
            error = err
            logger.warning("web search via %s failed (%s), trying the next finder", name, err)
    raise error
