"""Model-callable web search and URL fetching."""

from pydantic import BaseModel, Field

from . import fetch, search
from .conversa_tool import ConversaTool, ToolArguments, ToolFailed, ToolOutput, ToolRejected, ToolUnavailable


class SearchWebArguments(ToolArguments):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=12)


class SearchHit(BaseModel):
    title: str | None
    url: str


class SearchWebOutput(BaseModel):
    results: list[SearchHit]


class FetchUrlArguments(ToolArguments):
    url: str = Field(min_length=1, max_length=2048)
    topic: str | None = Field(default=None, max_length=500)
    raw: bool = False
    offset: int = Field(default=0, ge=0)


class FetchUrlOutput(BaseModel):
    url: str
    title: str | None
    kind: str
    content: str
    offset: int
    totalChars: int
    nextOffset: int | None


async def search_web(arguments: SearchWebArguments) -> ToolOutput:
    try:
        hits = await search.search(arguments.query, arguments.limit)
    except Exception as error:
        raise ToolUnavailable(f"app web search failed: {error}") from error
    if hits is None:
        raise ToolUnavailable("app web search is not configured")
    result = SearchWebOutput(results=[SearchHit.model_validate(hit) for hit in hits])
    return ToolOutput(
        result,
        {"query": arguments.query, "results": [hit.model_dump(mode="json") for hit in result.results]},
        # WHY: the artifact is the durable client-side provenance record, so it repeats the query and the hits; the trace alone is ephemeral and redacted.
        {"input": {"query": arguments.query, "limit": arguments.limit}, "output": {"results": [hit.model_dump(mode="json") for hit in result.results]}},
    )


async def fetch_url(arguments: FetchUrlArguments) -> ToolOutput:
    try:
        page = await fetch.fetch(arguments.url, arguments.topic, arguments.raw, arguments.offset)
    except fetch.FetchPolicyError as error:
        raise ToolRejected(str(error)) from error
    except fetch.FetchError as error:
        raise ToolFailed(f"app URL fetch failed: {error}") from error
    result = FetchUrlOutput.model_validate(page)
    return ToolOutput(
        result,
        {"url": result.url, "title": result.title, "kind": result.kind},
        # WHY: persists the window (bounded by fetch.py budgets) so later turns can cite it without refetching; the trace keeps no body by design.
        {"input": {"url": arguments.url, "topic": arguments.topic, "raw": arguments.raw, "offset": arguments.offset}, "output": result.model_dump(mode="json")},
    )


# Matches FETCH_CACHE_TTL_SECONDS: provenance counts as current for as long as the cached page would serve.
ARTIFACT_FRESH_SECONDS = 1800


WEB_TOOLS = [
    ConversaTool(
        "search_web",
        "Search the public web for current or external information. Returns source titles and URLs; use fetch_url to read a result.",
        SearchWebArguments,
        search_web,
        artifact_fresh_for=ARTIFACT_FRESH_SECONDS,
    ),
    ConversaTool(
        "fetch_url",
        "Read a public HTTP or HTTPS URL and return one window of it. `topic` returns only the sections relevant to it; omit `topic` to read the whole page; `raw` returns the page's HTML source instead of extracted content, ignoring `topic`; `offset` continues a long page where a previous call stopped. The response includes `totalChars` and `nextOffset` for reading the rest. Use it for URLs supplied by the user or returned by search_web.",
        FetchUrlArguments,
        fetch_url,
        artifact_fresh_for=ARTIFACT_FRESH_SECONDS,
    ),
]
