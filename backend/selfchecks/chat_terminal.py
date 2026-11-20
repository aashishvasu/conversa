"""Selfcheck: python -m selfchecks.chat_terminal"""

import asyncio
from types import SimpleNamespace

from providers import chat
from providers.dialects import response_frame


async def collect(gen):
    return [frame async for frame in gen]


async def main():
    original = chat._DIALECT_STREAMS["anthropic"]

    async def error_after_text(provider, model, messages, system, max_tokens, effort, temperature, **kw):
        yield {"text": "partial"}
        yield {"error": "SENTINEL-PROVIDER-FAIL"}
        yield {"text": "MUST-NOT-APPEAR"}

    chat._DIALECT_STREAMS["anthropic"] = error_after_text
    try:
        out = await collect(chat.stream_chat("anthropic", "m", [], None, 10, "low", 0.0))
    finally:
        chat._DIALECT_STREAMS["anthropic"] = original
    assert out[0] == {"text": "partial"}, out
    assert out[-1].get("error") and out[-1].get("code"), out[-1]
    assert all("done" not in f for f in out), "a terminal failure emits no done frame"
    assert all(f.get("text") != "MUST-NOT-APPEAR" for f in out), "no frames follow the terminal"
    assert "SENTINEL-PROVIDER-FAIL" not in out[-1]["error"], "raw provider text is sanitized"

    async def capped(provider, model, messages, system, max_tokens, effort, temperature, **kw):
        yield {"text": "cut"}
        yield {"_response": SimpleNamespace(stop_reason="max_tokens")}

    chat._DIALECT_STREAMS["anthropic"] = capped
    try:
        out = await collect(chat.stream_chat("anthropic", "m", [], None, 10, "low", 0.0))
    finally:
        chat._DIALECT_STREAMS["anthropic"] = original
    assert out[-1] == {"done": True, "finishReason": "output_limit"}, out[-1]

    async def bare_eof(provider, model, messages, system, max_tokens, effort, temperature, **kw):
        yield {"text": "partial"}

    chat._DIALECT_STREAMS["anthropic"] = bare_eof
    try:
        out = await collect(chat.stream_chat("anthropic", "m", [], None, 10, "low", 0.0))
    finally:
        chat._DIALECT_STREAMS["anthropic"] = original
    assert out[0] == {"text": "partial"}, out
    assert out[-1].get("error") and out[-1].get("code"), out[-1]
    assert all("done" not in f for f in out), "bare EOF settles as a failed turn"

    async def refused(provider, model, messages, system, max_tokens, effort, temperature, **kw):
        event = {
            "type": "response.output_item.done",
            "item": {"type": "message", "content": [{"type": "refusal", "refusal": "SENTINEL-REFUSAL"}]},
        }
        if frame := response_frame(event):
            yield frame
        yield {"text": "MUST-NOT-APPEAR"}

    chat._DIALECT_STREAMS["responses"] = refused
    try:
        out = await collect(chat.stream_chat("openai", "m", [], None, 10, "low", 0.0))
    finally:
        chat._DIALECT_STREAMS["responses"] = original
    assert out[-1].get("error") and out[-1].get("code"), out[-1]
    assert all("done" not in f for f in out), "a refusal settles as a failed turn"
    assert all(f.get("text") != "MUST-NOT-APPEAR" for f in out), "no frames follow refusal"
    assert "SENTINEL-REFUSAL" not in out[-1]["error"], "refusal text is sanitized"
    print("chat_terminal selfcheck ok")


asyncio.run(main())
