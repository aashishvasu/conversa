"""Provider layer: clients, the model registry, and the two shapes of a model call.

Everything that knows an API key or a model id lives here.
main.py owns the web app and research.py owns the run loop, and both import this, which is what keeps them from importing each other.
"""

import logging
import os

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Idempotent, and it has to run here too: importing this module before main reads the env otherwise finds nothing.
load_dotenv()

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-sonnet-5")
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "1.0"))
DEFAULT_MAX_TOKENS = int(os.environ.get("DEFAULT_MAX_TOKENS", "4096"))
# Thinking effort: "" (off), "low", "medium", "high".
# See apply_thinking() for how it reaches the API.
# The wire format differs between model generations.
DEFAULT_EFFORT = os.environ.get("DEFAULT_EFFORT", "")
# Cheap model for auxiliary tasks: title generation and history compression.
DEFAULT_UTILITY_MODEL = os.environ.get("DEFAULT_UTILITY_MODEL", "claude-haiku-4-5")

# Anthropic's server-side web search tool.
# Model-invoked: it searches only when a message warrants it.
WEB_SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL_VERSION", "web_search_20250305")
# Server-side web fetch tool (lets the model open a URL the user pastes).
# Beta-gated.
WEB_FETCH_TOOL = os.environ.get("WEB_FETCH_TOOL_VERSION", "web_fetch_20250910")
WEB_FETCH_BETA = os.environ.get("WEB_FETCH_BETA", "web-fetch-2025-09-10")
# OpenAI's hosted search tool.
# One tool covers both searching and opening pages, so it stands in for both of the above.
# Empty disables it.
OPENAI_WEB_SEARCH = os.environ.get("OPENAI_WEB_SEARCH_TOOL", "web_search")

# A research run makes ~30 calls, so a transient 429 or 529 during one of them should be expected.
# The SDKs retry 408/409/429/5xx and connection errors with exponential backoff; the default of 2 is too few for that.
API_MAX_RETRIES = int(os.environ.get("API_MAX_RETRIES", "5"))

# Models predating adaptive thinking (pre-4.6).
# They take the old fixed-token-budget form, reject output_config.effort, and accept temperature.
# Everything newer takes the modern form.
# Unknown ids are assumed modern, the direction the API moved.
# Hand-maintained: add an id here if you expose an older model via MODELS.
LEGACY_MODELS = {
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-sonnet-4-0",
    "claude-opus-4-0",
    "claude-3-haiku-20240307",
}

# Fixed budgets the effort levels map to on legacy models.
# Modern models get the qualitative effort string instead and size their own thinking.
LEGACY_EFFORT_BUDGETS = {"low": 4000, "medium": 10000, "high": 24000}

# The effort vocabulary the frontend offers (store.js EFFORT_LEVELS).
# Anthropic takes it as output_config.effort, OpenAI as reasoning.effort, so the lever needs no translation.
EFFORT_VALUES = ("low", "medium", "high")

# OpenAI reasoning models take reasoning.effort and reject temperature; older chat models are the inverse.
# Prefix match, hand-maintained like LEGACY_MODELS above.
OPENAI_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

# Selectable models, labelled.
# Format: "provider/id:Label,id2:Label2" (label optional, provider optional).
# Built-ins are always offered; the MODELS env var appends extra ids.
# First occurrence of an id wins.
BUILTIN_MODELS = (
    "claude-fable-5:Fable 5,"
    "claude-opus-5:Opus 5,claude-sonnet-5:Sonnet 5,claude-opus-4-8:Opus 4.8,"
    "claude-sonnet-4-6:Sonnet 4.6,claude-haiku-4-5:Haiku 4.5,"
    "openai/gpt-5.6-sol:GPT-5.6 Sol,openai/gpt-5.6-terra:GPT-5.6 Terra,"
    "openai/gpt-5.6-luna:GPT-5.6 Luna,openai/gpt-5.5:GPT-5.5,"
    "openai/gpt-5-mini:GPT-5 Mini"
)


def apply_thinking(kwargs, effort, max_tokens):
    """Attach thinking config for `effort` ("", low, medium, high) to an API kwargs dict.

    Modern models (4.6+) take adaptive thinking plus output_config.effort, and no sampling params at all, since
    Opus 4.7+ reject `temperature` whether or not thinking is on.
    Legacy models take the pre-4.6 fixed budget, which requires budget < max_tokens and also drops temperature.
    Mutates and returns kwargs.
    """
    legacy = kwargs["model"] in LEGACY_MODELS
    if not legacy:
        # Rejected on Opus 4.7/4.8 even with thinking off, so this is unconditional.
        kwargs.pop("temperature", None)
    if not effort:
        return kwargs
    if legacy:
        budget = LEGACY_EFFORT_BUDGETS[effort]
        kwargs["max_tokens"] = max(max_tokens, budget + DEFAULT_MAX_TOKENS)
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        kwargs.pop("temperature", None)
    else:
        # display=summarized: the default is "omitted", which streams empty thinking blocks and would blank the live trace in ChatPane.
        kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        kwargs["output_config"] = {"effort": effort}
        # Thinking spends from max_tokens, so a 4096 cap can be consumed entirely by it.
        kwargs["max_tokens"] = max(max_tokens, 32000)
    return kwargs


def split_model(mid):
    """"openai/gpt-5.6" -> ("openai", "gpt-5.6"); a bare id -> ("anthropic", id).

    Unprefixed means Anthropic permanently, the way a bare Docker image name means docker.io.
    Conversations saved before OpenAI support hold bare ids in IndexedDB and .env files still use them, so this
    stays true rather than becoming a migration step.
    rpartition, so a model id that itself contains a slash splits at the last one.
    """
    provider, _, name = mid.rpartition("/")
    return (provider or "anthropic"), name


def parse_models(raw):
    out, seen = [], set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        mid, _, label = entry.partition(":")
        mid = mid.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append({"id": mid, "label": label.strip() or mid, "provider": split_model(mid)[0]})
    return out


def field(obj, name):
    """Read a field off an SDK model or a plain dict.

    OpenAI annotation and action shapes vary between SDK versions.
    On a shape this doesn't recognise it returns None, which costs one trace event and leaves the stream running.
    """
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


CONFIGURED = {p for p, key in (("anthropic", API_KEY), ("openai", OPENAI_API_KEY)) if key}

ALL_MODELS = parse_models(BUILTIN_MODELS + "," + os.environ.get("MODELS", ""))
# Only offer what we hold a key for: an unusable option in the dropdown fails as a bare 503 on send, and silently (swallowed) when it's the utility model.
MODELS = [m for m in ALL_MODELS if m["provider"] in CONFIGURED]

# Config problems downgrade the app and let it start: with one key missing, the other provider still works.
# These ride along on /api/settings so the UI can name the cause of a missing model.
CONFIG_ERRORS = []


def _config_error(msg):
    CONFIG_ERRORS.append(msg)
    logging.warning(msg)


_dropped = [m["id"] for m in ALL_MODELS if m["provider"] not in CONFIGURED]
if _dropped:
    _missing = sorted({split_model(i)[0] for i in _dropped})
    _config_error(
        f"No API key for {', '.join(_missing)}. Hidden from the model list: {', '.join(_dropped)}"
    )
for _name, _mid in (("DEFAULT_MODEL", DEFAULT_MODEL), ("DEFAULT_UTILITY_MODEL", DEFAULT_UTILITY_MODEL)):
    if not any(m["id"] == _mid for m in MODELS):
        _config_error(f"{_name}={_mid} is not selectable (no API key for it, or not in MODELS)")

client = AsyncAnthropic(api_key=API_KEY, max_retries=API_MAX_RETRIES) if API_KEY else None
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=API_MAX_RETRIES) if OPENAI_API_KEY else None


async def complete(model_id, system, prompt, max_tokens=2048, effort="", spend=None):
    """One non-streaming call, returning text.

    The streaming path in main.py serves the chat UI; a research worker wants the finished answer.
    `spend` is anything with .add(model_id, input_tokens, output_tokens), which keeps cost accounting out of here.
    """
    provider, model = split_model(model_id)
    if provider == "anthropic":
        kwargs = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = system
        apply_thinking(kwargs, effort, max_tokens)
        # Streaming throughout, because the SDK refuses a non-streaming request whose max_tokens could outrun its 10-minute ceiling.
        # The report call is well past that threshold, and one path beats a size test that gets it wrong later.
        async with client.messages.stream(**kwargs) as stream:
            message = await stream.get_final_message()
        if spend:
            spend.add(model_id, message.usage.input_tokens, message.usage.output_tokens)
        return "".join(b.text for b in message.content if b.type == "text").strip()
    if provider == "openai":
        kwargs = dict(model=model, input=prompt, max_output_tokens=max_tokens)
        if system:
            kwargs["instructions"] = system
        if effort and model.startswith(OPENAI_REASONING_PREFIXES):
            kwargs["reasoning"] = {"effort": effort}
        response = await openai_client.responses.create(**kwargs)
        if spend and response.usage:
            spend.add(model_id, response.usage.input_tokens, response.usage.output_tokens)
        return (response.output_text or "").strip()
    raise ValueError(f"unknown provider: {provider}")


if __name__ == "__main__":  # self-check: python llm.py
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

    # Both providers share one effort vocabulary, so the lever needs no translation.
    assert set(EFFORT_VALUES) == set(LEGACY_EFFORT_BUDGETS), EFFORT_VALUES

    # field() reads SDK objects and plain dicts alike, and returns None on a shape it doesn't recognise.
    class _Obj:
        type = "url_citation"
    assert field({"type": "url_citation"}, "type") == "url_citation"
    assert field(_Obj(), "type") == "url_citation"
    assert field({"a": 1}, "missing") is None and field(_Obj(), "missing") is None

    print("llm selfcheck OK")
