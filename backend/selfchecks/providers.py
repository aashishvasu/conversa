"""Selfcheck: python -m selfchecks.providers"""

from types import SimpleNamespace as Obj

from providers import (
    DIALECTS,
    EFFORT_VALUES,
    PROVIDERS,
    Spend,
    anthropic_frame,
    anthropic_system,
    anthropic_usage,
    apply_thinking,
    chat_completion_frames,
    chat_completion_usage,
    chat_completions_kwargs,
    complete_messages_kwargs,
    cost,
    field,
    join_model,
    join_system,
    openai_messages,
    parse_models,
    resolve_model,
    response_frame,
    responses_kwargs,
    responses_usage,
    split_model,
    takes_reasoning,
)
from providers.anthropic import LEGACY_EFFORT_BUDGETS


def request(model: str, temperature: float = 1.0) -> dict:
    return {"model": model, "max_tokens": 4096, "temperature": temperature}


modern = apply_thinking(request("claude-opus-4-8"), "high", 4096)
assert modern["thinking"] == {"type": "adaptive", "display": "summarized"}, modern
assert modern["output_config"] == {"effort": "high"} and modern["max_tokens"] == 32000, modern
assert "temperature" not in modern, modern

modern = apply_thinking(request("claude-opus-4-8"), "", 4096)
assert "temperature" not in modern and "thinking" not in modern, modern

legacy = apply_thinking(request("claude-haiku-4-5"), "medium", 4096)
assert legacy["thinking"] == {"type": "enabled", "budget_tokens": 10000}, legacy
assert legacy["max_tokens"] > legacy["thinking"]["budget_tokens"], legacy
assert "output_config" not in legacy and "temperature" not in legacy, legacy
assert apply_thinking(request("claude-haiku-4-5", 0.3), "", 4096)["temperature"] == 0.3
assert "output_config" in apply_thinking(request("claude-future-9"), "low", 4096)
assert set(EFFORT_VALUES) == set(LEGACY_EFFORT_BUDGETS), EFFORT_VALUES

assert split_model("claude-opus-5") == ("anthropic", "claude-opus-5")
assert split_model("openai/gpt-5.6") == ("openai", "gpt-5.6")
assert split_model("openai/ft:org/gpt-5.6") == ("openai/ft:org", "gpt-5.6")
models = parse_models("claude-opus-5:Opus 5,openai/gpt-5.6:GPT,openai/gpt-5.6:dupe,bare-id")
assert [model["id"] for model in models] == ["claude-opus-5", "openai/gpt-5.6", "bare-id"], models
assert [model["provider"] for model in models] == ["anthropic", "openai", "anthropic"], models
assert models[1]["label"] == "GPT" and models[2]["label"] == "bare-id", models
assert models[0]["supports_cache"] and models[2]["supports_cache"], "anthropic (named or bare) supports cache"
assert not models[1]["supports_cache"], "openai does not"
assert not parse_models("nosuch/model")[0]["supports_cache"], "an unknown provider defaults to unsupported"

assert set(PROVIDERS) == {"anthropic", "compatible", "deepseek", "openai"}, PROVIDERS
for name, entry in PROVIDERS.items():
    assert entry["dialect"] in DIALECTS and entry["key_env"] and "models" in entry, name
    assert entry.get("base_url") or name in ("anthropic", "compatible", "openai"), name
    for model in parse_models(entry["models"]):
        assert model["provider"] == name, (name, model)
assert PROVIDERS["compatible"]["models"] == ""
assert PROVIDERS["compatible"]["base_url_env"] == "OPENAI_COMPATIBLE_BASE_URL"

assert takes_reasoning("openai", "gpt-5.6-sol") and not takes_reasoning("openai", "gpt-4o")
assert takes_reasoning("deepseek", "deepseek-v4-flash")

blocks = anthropic_system(["stable", "volatile"])
assert blocks == [
    {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "volatile"},
], blocks
assert anthropic_system("plain") == "plain"
assert anthropic_system(["stable", ""]) == [{"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}}]

chat = chat_completions_kwargs(
    "some-model", [{"role": "user", "content": "hi"}], ["stable", "volatile"], 2048, temperature=0.3
)
assert chat["messages"][0] == {"role": "system", "content": "stable\n\nvolatile"}, chat
assert chat["messages"][1]["content"] == "hi" and chat["temperature"] == 0.3, chat
assert "temperature" not in chat_completions_kwargs("some-model", [], None, 2048)
responses = responses_kwargs("deepseek", "deepseek-v4-flash", [{"role": "user", "content": "hi"}], None, 20, "", 0.5)
assert responses["reasoning"] == {"effort": "none"} and "temperature" not in responses, responses
responses = responses_kwargs("deepseek", "deepseek-v4-flash", [], None, 20, "low", 0.5)
assert responses["reasoning"] == {"effort": "low", "summary": "auto"}, responses
assert responses["max_output_tokens"] == 32000, responses
assert join_system(["stable", ""]) == "stable" and join_system("plain") == "plain"
vision = [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/webp", "data": "DATA"}}, {"type": "text", "text": "look"}]}]
assert openai_messages(vision, True)[0]["content"] == [{"type": "input_image", "image_url": "data:image/webp;base64,DATA"}, {"type": "input_text", "text": "look"}]
assert openai_messages(vision, False)[0]["content"] == [{"type": "image_url", "image_url": {"url": "data:image/webp;base64,DATA"}}, {"type": "text", "text": "look"}]

# Preparation uses the same dialect conversion as chat, despite being a non-streaming call.
prepared_anthropic = complete_messages_kwargs("anthropic", "claude-opus-4-8", vision, ["stable", "volatile"], 1024, "")
assert prepared_anthropic["system"] == anthropic_system(["stable", "volatile"]), prepared_anthropic
assert prepared_anthropic["messages"] == vision, prepared_anthropic
prepared_responses = complete_messages_kwargs("deepseek", "deepseek-v4-flash", vision, ["stable", "volatile"], 1024, "")
assert prepared_responses["input"] == openai_messages(vision, True), prepared_responses
assert prepared_responses["instructions"] == "stable\n\nvolatile", prepared_responses
assert prepared_responses["reasoning"] == {"effort": "none"}, prepared_responses
prepared_chat = complete_messages_kwargs("compatible", "some-model", vision, ["stable", "volatile"], 1024, "")
assert prepared_chat["messages"] == [{"role": "system", "content": "stable\n\nvolatile"}, *openai_messages(vision, False)], prepared_chat

assert anthropic_frame(Obj(type="content_block_delta", delta=Obj(type="text_delta", text="hello"))) == {"text": "hello"}
assert anthropic_frame(Obj(type="content_block_delta", delta=Obj(type="thinking_delta", thinking="hmm"))) == {"think": "hmm"}
assert anthropic_frame(Obj(type="content_block_stop", content_block={
    "type": "server_tool_use", "name": "web_fetch", "input": {"url": "https://example.com"}
})) == {"fetch": "https://example.com"}

assert response_frame(Obj(type="response.output_text.delta", delta="hello")) == {"text": "hello"}
assert response_frame(Obj(type="response.reasoning_text.delta", delta="hmm")) == {"think": "hmm"}
assert response_frame(Obj(type="response.reasoning_summary_text.delta", delta="summary")) == {"think": "summary"}
assert response_frame(Obj(type="response.output_item.done", item={
    "type": "web_search_call", "action": {"type": "search", "query": "kettle"}
})) == {"search": "kettle"}
assert response_frame(Obj(type="response.output_text.annotation.added", annotation={
    "type": "url_citation", "title": "Kettles", "url": "https://example.com/kettle"
})) == {"results": [{"title": "Kettles", "url": "https://example.com/kettle"}]}

frames = chat_completion_frames(Obj(choices=[Obj(delta={"reasoning_content": "hmm", "content": "answer"})]))
assert frames == [{"think": "hmm"}, {"text": "answer"}], frames
assert chat_completion_frames(Obj(choices=[])) == []
assert field({"type": "url_citation"}, "type") == "url_citation"
assert field(Obj(type="url_citation"), "type") == "url_citation"

try:
    resolve_model("missing/model")
    raise AssertionError("unknown provider accepted")
except LookupError:
    pass

# join_model is split_model's inverse.
assert join_model(*split_model("claude-opus-5")) == "claude-opus-5"
assert join_model(*split_model("openai/gpt-5.6")) == "openai/gpt-5.6"
assert join_model("anthropic", "claude-x") == "claude-x"
assert join_model("openai", "gpt-x") == "openai/gpt-x"

# cost(): base rate, then each of cache write, cache read, and hosted search priced independently.
usd, priced = cost("anthropic", "claude-sonnet-5", 1_000_000, 0)
assert priced and usd == 3.0, usd
usd, _ = cost("anthropic", "claude-sonnet-5", 0, 0, cache_write=1_000_000)
assert usd == 3.75, usd  # 3 * 1.25
usd, _ = cost("anthropic", "claude-sonnet-5", 0, 0, cache_read=1_000_000)
assert usd == 0.3, usd  # 3 * 0.1
usd, _ = cost("anthropic", "claude-sonnet-5", 0, 0, search_requests=1000)
assert usd == 10.0, usd
usd, priced = cost("anthropic", "unknown-model-xyz", 1_000_000, 1_000_000)
assert not priced and usd == 30.0, usd  # UNKNOWN_PRICE (5, 25)

# Spend: totals plus a per-model breakdown, so as_dict() answers both the sidebar's total and a future per-model view.
spend = Spend()
spend.add("claude-haiku-4-5", 100, 50)
spend.add("claude-haiku-4-5", 200, 0, cache_read=500)
spend.add("openai/gpt-5.6-luna", 10, 10)
d = spend.as_dict()
assert d["calls"] == 3 and d["input"] == 310 and d["output"] == 60, d
assert d["cache_read"] == 500, d
assert set(d["models"]) == {"claude-haiku-4-5", "openai/gpt-5.6-luna"}, d
assert d["models"]["claude-haiku-4-5"]["calls"] == 2, d
spend.add("openai/some-unknown-model", 0, 100)
assert spend.as_dict()["models"]["openai/some-unknown-model"]["unpriced"] == 1, spend.as_dict()
assert spend.as_dict()["models"]["claude-haiku-4-5"]["unpriced"] == 0, "a priced model's row is not flagged"

# anthropic_usage: cache and hosted-search counts alongside tokens, from message.usage.
assert anthropic_usage(Obj(
    input_tokens=10, output_tokens=5, cache_read_input_tokens=3, cache_creation_input_tokens=2,
    server_tool_use=Obj(web_search_requests=1),
)) == {"input": 10, "output": 5, "cache_read": 3, "cache_write": 2, "search_requests": 1}
assert anthropic_usage(Obj(
    input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0,
    server_tool_use=None,
))["search_requests"] == 0

# responses_usage: only the response.completed event carries usage; every other event is None.
assert responses_usage(Obj(type="response.output_text.delta", delta="x")) is None
usage = responses_usage(Obj(type="response.completed", response={"usage": {
    "input_tokens": 8, "output_tokens": 4,
    "input_tokens_details": {"cached_tokens": 6, "cache_write_tokens": 1},
}}))
assert usage == {"input": 8, "output": 4, "cache_read": 6, "cache_write": 1, "search_requests": 0}, usage

# chat_completion_usage: only the final chunk (stream_options include_usage) carries usage.
assert chat_completion_usage(Obj(choices=[], usage=None)) is None
usage = chat_completion_usage(Obj(choices=[], usage={
    "prompt_tokens": 8, "completion_tokens": 4,
    "prompt_tokens_details": {"cached_tokens": 6, "cache_write_tokens": 1},
}))
assert usage == {"input": 8, "output": 4, "cache_read": 6, "cache_write": 1, "search_requests": 0}, usage

print("providers selfcheck OK")
