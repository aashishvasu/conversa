"""Provider package self-check: python -m providers."""

from types import SimpleNamespace as Obj

from . import (
    DIALECTS,
    EFFORT_VALUES,
    PROVIDERS,
    anthropic_frame,
    anthropic_system,
    apply_thinking,
    chat_completion_frames,
    chat_completions_kwargs,
    field,
    join_system,
    parse_models,
    resolve_model,
    response_frame,
    split_model,
    takes_reasoning,
)
from .anthropic import LEGACY_EFFORT_BUDGETS


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
assert join_system(["stable", ""]) == "stable" and join_system("plain") == "plain"

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

print("providers selfcheck OK")
