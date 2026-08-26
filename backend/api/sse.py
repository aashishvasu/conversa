"""SSE framing shared by the chat and research streams."""

import json
from collections.abc import AsyncIterable, AsyncIterator


def sse(**payload: object) -> str:
    # json-encode each chunk so newlines/special chars can't break SSE framing.
    return f"data: {json.dumps(payload)}\n\n"


async def sse_stream(events: AsyncIterable[dict]) -> AsyncIterator[str]:
    async for payload in events:
        yield sse(**payload)
