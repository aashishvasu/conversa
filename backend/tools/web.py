"""Model-callable web search and URL fetching."""

from pydantic import BaseModel, Field

from . import fetch, search
from .conversa_tool import ConversaTool, ToolArguments, ToolOutput, ToolRejected, ToolUnavailable


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
    topic: str = Field(min_length=1, max_length=500)


class FetchUrlOutput(BaseModel):
    url: str
    title: str | None
    kind: str
    content: str


async def search_web(arguments: SearchWebArguments) -> ToolOutput:
    try:
        hits = await search.search(arguments.query, arguments.limit)
    except Exception as error:
        raise ToolUnavailable("app web search failed") from error
    if hits is None:
        raise ToolUnavailable("app web search is not configured")
    result = SearchWebOutput(results=[SearchHit.model_validate(hit) for hit in hits])
    return ToolOutput(
        result,
        {"query": arguments.query, "results": [hit.model_dump(mode="json") for hit in result.results]},
    )


async def fetch_url(arguments: FetchUrlArguments) -> ToolOutput:
    try:
        page = await fetch.fetch(arguments.url, arguments.topic)
    except fetch.FetchPolicyError as error:
        raise ToolRejected(str(error)) from error
    except fetch.FetchError as error:
        raise ToolUnavailable("app URL fetch failed") from error
    result = FetchUrlOutput.model_validate(page)
    return ToolOutput(result, {"url": result.url, "title": result.title, "kind": result.kind})


WEB_TOOLS = [
    ConversaTool(
        "search_web",
        "Search the public web for current or external information. Returns source titles and URLs; use fetch_url to read a result.",
        SearchWebArguments,
        search_web,
    ),
    ConversaTool(
        "fetch_url",
        "Read a public HTTP or HTTPS URL and return the sections relevant to a stated topic. Use it for URLs supplied by the user or returned by search_web.",
        FetchUrlArguments,
        fetch_url,
    ),
]
