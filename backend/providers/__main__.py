"""Provider package self-check: python -m providers."""

from . import *

def _k(model, temperature=1.0):
    return {"model": model, "max_tokens": 4096, "temperature": temperature}

# Modern model, thinking on: adaptive + effort, no temperature, roomier max_tokens.
m = apply_thinking(_k("claude-opus-4-8"), "high", 4096)
assert m["thinking"] == {"type": "adaptive", "display": "summarized"}, m
assert m["output_config"] == {"effort": "high"}, m
assert "temperature" not in m, m
assert m["max_tokens"] == 32000, m

# Modern model, thinking off: still no temperature (Opus 4.7/4.8 reject it outright).
m = apply_thinking(_k("claude-opus-4-8"), "", 4096)
assert "temperature" not in m and "thinking" not in m, m
assert m["max_tokens"] == 4096, m

# Legacy model: fixed budget, budget < max_tokens, temperature dropped only here.
m = apply_thinking(_k("claude-haiku-4-5"), "medium", 4096)
assert m["thinking"] == {"type": "enabled", "budget_tokens": 10000}, m
assert m["max_tokens"] > m["thinking"]["budget_tokens"], m
assert "output_config" not in m and "temperature" not in m, m

# Legacy model, thinking off: temperature survives, since legacy models accept it.
m = apply_thinking(_k("claude-haiku-4-5", temperature=0.3), "", 4096)
assert m["temperature"] == 0.3, m
assert "thinking" not in m, m

# Unknown ids are treated as modern, not legacy.
assert "output_config" in apply_thinking(_k("claude-future-9"), "low", 4096)

# A bare id means Anthropic, permanently.
# Conversations saved before OpenAI support hold bare ids.
assert split_model("claude-opus-5") == ("anthropic", "claude-opus-5")
assert split_model("openai/gpt-5.6") == ("openai", "gpt-5.6")
# rpartition, so a provider id that itself contains a slash still splits at the last one.
assert split_model("openai/ft:org/gpt-5.6") == ("openai/ft:org", "gpt-5.6")

# parse_models: label optional, provider derived, first occurrence of an id wins.
p = parse_models("claude-opus-5:Opus 5,openai/gpt-5.6:GPT,openai/gpt-5.6:dupe,bare-id")
assert [m["id"] for m in p] == ["claude-opus-5", "openai/gpt-5.6", "bare-id"], p
assert [m["provider"] for m in p] == ["anthropic", "openai", "anthropic"], p
assert p[1]["label"] == "GPT" and p[2]["label"] == "bare-id", p

# Models whose provider has no key are hidden rather than offered-then-503.
_all = parse_models("claude-opus-5:Opus,openai/gpt-5.6:GPT")
assert [m["id"] for m in _all if m["provider"] in {"anthropic"}] == ["claude-opus-5"], _all

# Registry shape: a typo in `dialect` surfaces as a 400 on send, and a chat.completions entry without a
# base_url would go to api.openai.com under someone else's key.
for _name, _entry in PROVIDERS.items():
    assert _entry["dialect"] in DIALECTS, _name
    assert _entry["key_env"] and _entry["models"], _name
    # Only the two first-class endpoints are the SDK defaults; anything else needs its own address.
    assert _entry.get("base_url") or _name in ("anthropic", "openai"), _name
    # An entry whose ids carry the wrong prefix stays hidden whatever keys are set, since MODELS filters on provider.
    for _m in parse_models(_entry["models"]):
        assert _m["provider"] == _name, (_name, _m)

# Reasoning gate: OpenAI splits its lineup by id prefix, DeepSeek reasons on everything it offers.
assert takes_reasoning("openai", "gpt-5.6-sol") and not takes_reasoning("openai", "gpt-4o")
assert takes_reasoning("deepseek", "deepseek-v4-flash")

# chat.completions: the system param becomes the leading message, and temperature is omitted unless asked for.
_cc = chat_completions_kwargs("kimi-k2-thinking", [{"role": "user", "content": "hi"}],
                              ["stable", "volatile"], 2048, temperature=0.3)
assert _cc["messages"][0] == {"role": "system", "content": "stable\n\nvolatile"}, _cc
assert _cc["messages"][1]["content"] == "hi" and _cc["temperature"] == 0.3, _cc
_cc = chat_completions_kwargs("kimi-k2-thinking", [{"role": "user", "content": "hi"}], None, 2048)
assert _cc["messages"][0]["content"] == "hi" and "temperature" not in _cc, _cc

# An empty half is dropped rather than joined into leading blank lines.
assert join_system(["stable", ""]) == "stable"
assert join_system("plain") == "plain"

# Both providers share one effort vocabulary, so the lever needs no translation.
assert set(EFFORT_VALUES) == set(LEGACY_EFFORT_BUDGETS), EFFORT_VALUES

# field() reads SDK objects and plain dicts alike, and returns None on a shape it doesn't recognise.
class _Obj:
    type = "url_citation"
assert field({"type": "url_citation"}, "type") == "url_citation"
assert field(_Obj(), "type") == "url_citation"
assert field({"a": 1}, "missing") is None and field(_Obj(), "missing") is None

print("providers selfcheck OK")
