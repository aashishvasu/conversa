"""Selfcheck: python -m selfchecks.api"""

from pydantic import ValidationError

from api.chat import ChatRequest, Msg
from api.research import PREPARE_SYSTEM, parse_prepare_response
from api.sse import sse

assert sse(text="a\nb") == 'data: {"text": "a\\nb"}\n\n'
image = Msg.model_validate({"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/webp", "data": "x"}}]})
assert image.content[0].source.media_type == "image/webp"
assert not ChatRequest(messages=[]).allow_tools
assert ChatRequest(messages=[], allow_tools=True).allow_tools
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
