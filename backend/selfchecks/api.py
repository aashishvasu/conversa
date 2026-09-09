"""Selfcheck: python -m selfchecks.api"""

from pydantic import ValidationError

from api.chat import (
    DEFAULT_TOOL_CALCULATOR,
    DEFAULT_TOOL_DATETIME,
    DEFAULT_TOOL_FETCH_URL,
    DEFAULT_TOOL_RANDOM,
    DEFAULT_TOOL_WEB_SEARCH,
    DEFAULT_TOOLS_ENABLED,
    ChatRequest,
    Msg,
    settings,
)
from api.research import PREPARE_SYSTEM, parse_prepare_response
from api.sse import sse

assert sse(text="a\nb") == 'data: {"text": "a\\nb"}\n\n'
image = Msg.model_validate({"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/webp", "data": "x"}}]})
assert image.content[0].source.media_type == "image/webp"
assert not ChatRequest(messages=[]).allow_tools
assert ChatRequest(messages=[], allow_tools=True).allow_tools
assert ChatRequest(messages=[]).enabled_tools is None
assert ChatRequest(messages=[], enabled_tools=["datetime"]).enabled_tools == ["datetime"]

# /api/settings carries the six tool defaults, all on unless the operator disables them.
payload = settings(None)
for key, value in {
    "tools_enabled": DEFAULT_TOOLS_ENABLED,
    "tool_web_search": DEFAULT_TOOL_WEB_SEARCH,
    "tool_fetch_url": DEFAULT_TOOL_FETCH_URL,
    "tool_datetime": DEFAULT_TOOL_DATETIME,
    "tool_calculator": DEFAULT_TOOL_CALCULATOR,
    "tool_random": DEFAULT_TOOL_RANDOM,
}.items():
    assert payload[key] is value, (key, payload[key])
assert all(isinstance(v, bool) for v in (DEFAULT_TOOLS_ENABLED, DEFAULT_TOOL_WEB_SEARCH, DEFAULT_TOOL_FETCH_URL, DEFAULT_TOOL_DATETIME, DEFAULT_TOOL_CALCULATOR, DEFAULT_TOOL_RANDOM))
try:
    Msg.model_validate({"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/avif", "data": "x"}}]})
except ValidationError:
    pass
else:
    raise AssertionError("unsupported image formats are rejected")

# Preparation defaults ordinary conversation to an answer and accepts only its complete JSON contract.
assert "Default to `answer`" in PREPARE_SYSTEM
assert "Research capability is enabled for every request" in PREPARE_SYSTEM
decision = parse_prepare_response('{"action":"research","goal":"Compare databases for Project Orion’s regulated launch","questions":[]}')
assert decision.goal.startswith("Compare databases for Project Orion")
for malformed in ('not json', '{"action":"research","goal":"","questions":[]}', '{"action":"research","goal":"x","questions":[],"extra":true}', '{"action":"research","goal":"x","questions":["1","2","3","4","5","6"]}'):
    try:
        parse_prepare_response(malformed)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid preparation response accepted: {malformed}")
print("api selfcheck OK")
