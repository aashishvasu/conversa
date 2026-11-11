"""SSE framing shared by the chat and research streams."""

import json


def sse(**payload: object) -> str:
    # json-encode each chunk so newlines/special chars can't break SSE framing.
    return f"data: {json.dumps(payload)}\n\n"


def sse_ping() -> str:
    # A comment line keeps idle connections open; readers that parse only `data:` lines skip it.
    return ": ping\n\n"
