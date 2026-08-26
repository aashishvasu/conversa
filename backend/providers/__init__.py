"""Provider layer: the provider registry, clients, and the three shapes of a model call.

Everything that knows an API key or a model id lives here.
main.py owns the web app, research.py the gather stage, and runs.py the run loop; all three import this, which is what keeps them from importing each other.

One module per provider beside this one, each exporting a `PROVIDER` dict; adding a provider on an
existing dialect is that file plus its key in .env, and nothing in this package is edited.
Self-check: `python -m providers` (see __main__.py).
"""

import importlib
import logging
import os
import pkgutil

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Idempotent, and it has to run here too: importing this module before main reads the env otherwise finds nothing.
# Before the provider modules are imported, too: their tool versions and keys are read at import time.
load_dotenv()


DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-sonnet-5")
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "1.0"))
DEFAULT_MAX_TOKENS = int(os.environ.get("DEFAULT_MAX_TOKENS", "4096"))
# Thinking effort: "" (off), "low", "medium", "high".
# See apply_thinking() for how it reaches the API.
# The wire format differs between model generations.
DEFAULT_EFFORT = os.environ.get("DEFAULT_EFFORT", "")
# Cheap model for auxiliary tasks: title generation and history compression.
DEFAULT_UTILITY_MODEL = os.environ.get("DEFAULT_UTILITY_MODEL", "claude-haiku-4-5")

# A research run makes ~30 calls, so a transient 429 or 529 during one of them should be expected.
# The SDKs retry 408/409/429/5xx and connection errors with exponential backoff; the default of 2 is too few for that.
API_MAX_RETRIES = int(os.environ.get("API_MAX_RETRIES", "5"))

# The effort vocabulary the frontend offers (store.js EFFORT_LEVELS).
# Anthropic takes it as output_config.effort, OpenAI as reasoning.effort, so the lever needs no translation.
EFFORT_VALUES = ("low", "medium", "high")

# WHY: the Anthropic dialect driver reads Anthropic's own id sets directly, since it is the only
# consumer and there is one provider on that dialect. A second Anthropic-compatible provider with a
# different generation split moves these onto its entry.
from .anthropic import LEGACY_EFFORT_BUDGETS, LEGACY_MODELS  # noqa: E402

# Providers are data; dialects are code.
# `dialect` picks the wire protocol, and so both the branch in complete() and the stream generator in main.py.
#
# Entry fields: dialect (anthropic | responses | chat_completions), key_env, models, and optionally
# base_url (required away from the first-class endpoints), search_tool (hosted web search; absent = none),
# reasoning_prefixes (which ids take the dialect's thinking lever; absent = all of them), plus whatever
# else one dialect needs (Anthropic's fetch_tool and fetch_beta).
# Model ids in `models` carry their own provider prefix, except Anthropic's, which are bare (see split_model).
DIALECTS = ("anthropic", "responses", "chat_completions")


def _discover():
    """Every sibling module exporting a PROVIDER dict, keyed by module name.

    Dropping a file in registers it, which is the point: the registry has no list to edit and so no
    line for two people to collide on. Alphabetical, which is the order the model dropdown groups by.
    """
    found = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):  # __main__ carries the self-check, not a provider
            continue
        entry = getattr(importlib.import_module(f"{__name__}.{info.name}"), "PROVIDER", None)
        if entry:
            found[info.name] = entry
    return found


PROVIDERS = _discover()

KEYS = {name: os.environ.get(p["key_env"]) for name, p in PROVIDERS.items()}

# Selectable models, labelled.
# Format: "provider/id:Label,id2:Label2" (label optional, provider optional).
# Built-ins come from the registry above and are always offered; the MODELS env var appends extra ids.
# First occurrence of an id wins.
BUILTIN_MODELS = ",".join(p["models"] for p in PROVIDERS.values())


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
    """Split "openai/gpt-5.6" into ("openai", "gpt-5.6"); a bare id -> ("anthropic", id).

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


def takes_reasoning(provider, model):
    """Whether this model takes the Responses dialect's `reasoning` parameter (and so rejects temperature).

    OpenAI splits its lineup, reasoning models one way and chat models the other.
    A provider that lists no prefixes reasons on every model it offers, which is DeepSeek.
    """
    prefixes = PROVIDERS[provider].get("reasoning_prefixes")
    return model.startswith(prefixes) if prefixes else True


def join_system(system):
    """Collapse buildPayload's [stable, volatile] halves into the single system string every non-Anthropic dialect takes.

    The cache split is Anthropic-only: OpenAI-compatible APIs cache long prefixes themselves, or not at all.
    """
    return "\n\n".join(s for s in system if s) if isinstance(system, list) else system


def chat_completions_kwargs(model, messages, system, max_tokens, temperature=None):
    """Request body for the chat.completions dialect, shared by complete() and main.py's stream.

    No thinking lever: the dialect has no standard one, and Moonshot, the only provider here, picks
    thinking depth by model id. A provider with its own parameter name adds it as registry data.
    """
    if system:
        messages = [{"role": "system", "content": join_system(system)}, *messages]
    kwargs = dict(model=model, messages=messages, max_tokens=max_tokens)
    if temperature is not None:
        kwargs["temperature"] = temperature
    return kwargs


def field(obj, name):
    """Read a field off an SDK model or a plain dict.

    OpenAI annotation and action shapes vary between SDK versions.
    On a shape this doesn't recognise it returns None, which costs one trace event and leaves the stream running.
    """
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


CONFIGURED = {name for name, key in KEYS.items() if key}

ALL_MODELS = parse_models(BUILTIN_MODELS + "," + os.environ.get("MODELS", ""))
# Only offer what we hold a key for: an unusable option in the dropdown fails as a bare 503 on send, and silently (swallowed) when it's the utility model.
MODELS = [m for m in ALL_MODELS if m["provider"] in CONFIGURED]

# Config problems downgrade the app and let it start: with one key missing, the other provider still works.
# These ride along on /api/settings so the UI can name the cause of a missing model.
CONFIG_ERRORS = []


def _config_error(msg):
    CONFIG_ERRORS.append(msg)
    logging.warning(msg)


# Only ids the operator asked for by name are worth a banner.
# A registry provider with no key is an offer nobody took up, so it is hidden without comment.
_dropped = [m["id"] for m in parse_models(os.environ.get("MODELS", "")) if m["provider"] not in CONFIGURED]
if _dropped:
    _missing = sorted({split_model(i)[0] for i in _dropped})
    _config_error(
        f"No API key for {', '.join(_missing)}. Hidden from the model list: {', '.join(_dropped)}"
    )
for _name, _mid in (("DEFAULT_MODEL", DEFAULT_MODEL), ("DEFAULT_UTILITY_MODEL", DEFAULT_UTILITY_MODEL)):
    if not any(m["id"] == _mid for m in MODELS):
        _config_error(f"{_name}={_mid} is not selectable (no API key for it, or not in MODELS)")

def _build_client(name):
    key = KEYS[name]
    if not key:
        return None
    entry = PROVIDERS[name]
    if entry["dialect"] == "anthropic":
        return AsyncAnthropic(api_key=key, max_retries=API_MAX_RETRIES)
    # The openai SDK speaks both remaining dialects; base_url is what points it at a compatible provider.
    return AsyncOpenAI(api_key=key, base_url=entry.get("base_url"), max_retries=API_MAX_RETRIES)


CLIENTS = {name: _build_client(name) for name in PROVIDERS}


async def complete(model_id, system, prompt, max_tokens=2048, effort="", spend=None):
    """One non-streaming call, returning text.

    The streaming path in main.py serves the chat UI; a research worker wants the finished answer.
    `spend` is anything with .add(model_id, input_tokens, output_tokens), which keeps cost accounting out of here.
    """
    provider, model = split_model(model_id)
    entry = PROVIDERS.get(provider)
    if entry is None:
        raise ValueError(f"unknown provider: {provider}")
    api = CLIENTS[provider]
    if api is None:
        raise ValueError(f"server {entry['key_env']} not configured")
    dialect = entry["dialect"]
    if dialect == "anthropic":
        kwargs = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = system
        apply_thinking(kwargs, effort, max_tokens)
        # Streaming throughout, because the SDK refuses a non-streaming request whose max_tokens could outrun its 10-minute ceiling.
        # The report call is well past that threshold, and one path beats a size test that gets it wrong later.
        async with api.messages.stream(**kwargs) as stream:
            message = await stream.get_final_message()
        if spend:
            spend.add(model_id, message.usage.input_tokens, message.usage.output_tokens)
        return "".join(b.text for b in message.content if b.type == "text").strip()
    if dialect == "responses":
        kwargs = dict(model=model, input=prompt, max_output_tokens=max_tokens)
        if system:
            kwargs["instructions"] = join_system(system)
        if effort and takes_reasoning(provider, model):
            kwargs["reasoning"] = {"effort": effort}
        response = await api.responses.create(**kwargs)
        if spend and response.usage:
            spend.add(model_id, response.usage.input_tokens, response.usage.output_tokens)
        return (response.output_text or "").strip()
    kwargs = chat_completions_kwargs(model, [{"role": "user", "content": prompt}], system, max_tokens)
    response = await api.chat.completions.create(**kwargs)
    if spend and response.usage:
        spend.add(model_id, response.usage.prompt_tokens, response.usage.completion_tokens)
    return (response.choices[0].message.content or "").strip()
