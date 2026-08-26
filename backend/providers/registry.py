"""Provider configuration, model ids, clients, and defaults."""

import logging
import os

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Provider modules read env values at import time, so load .env first.
load_dotenv()

from .anthropic import PROVIDER as ANTHROPIC  # noqa: E402
from .compatible import PROVIDER as COMPATIBLE  # noqa: E402
from .deepseek import PROVIDER as DEEPSEEK  # noqa: E402
from .openai import PROVIDER as OPENAI  # noqa: E402

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "claude-sonnet-5")
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "1.0"))
DEFAULT_MAX_TOKENS = int(os.environ.get("DEFAULT_MAX_TOKENS", "4096"))
DEFAULT_EFFORT = os.environ.get("DEFAULT_EFFORT", "")
DEFAULT_UTILITY_MODEL = os.environ.get("DEFAULT_UTILITY_MODEL", "claude-haiku-4-5")
API_MAX_RETRIES = int(os.environ.get("API_MAX_RETRIES", "5"))
EFFORT_VALUES = ("low", "medium", "high")
DIALECTS = ("anthropic", "responses", "chat_completions")

# Explicit imports make registration visible.
PROVIDERS = {
    "anthropic": ANTHROPIC,
    "compatible": COMPATIBLE,
    "deepseek": DEEPSEEK,
    "openai": OPENAI,
}


def split_model(mid: str) -> tuple[str, str]:
    """Split `openai/gpt-5.6` into (`openai`, `gpt-5.6`); a bare id belongs to Anthropic.

    Persisted conversations from before multi-provider support hold bare ids, so that default is permanent.
    Splitting at the last slash preserves the existing behavior for fine-tuned ids containing a slash.
    """
    provider, _, name = mid.rpartition("/")
    return (provider or "anthropic"), name


def parse_models(raw: str) -> list[dict[str, str]]:
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


def _missing(name: str) -> list[str]:
    entry = PROVIDERS[name]
    missing = []
    if not os.environ.get(entry["key_env"]):
        missing.append(entry["key_env"])
    if entry.get("base_url_env") and not entry.get("base_url"):
        missing.append(entry["base_url_env"])
    return missing


CONFIGURED = {name for name in PROVIDERS if not _missing(name)}
BUILTIN_MODELS = ",".join(entry["models"] for entry in PROVIDERS.values())
ALL_MODELS = parse_models(BUILTIN_MODELS + "," + os.environ.get("MODELS", ""))
MODELS = [model for model in ALL_MODELS if model["provider"] in CONFIGURED]
CONFIG_ERRORS = []


def _config_error(message: str) -> None:
    CONFIG_ERRORS.append(message)
    logging.warning(message)


_requested = parse_models(os.environ.get("MODELS", ""))
for _provider in sorted({model["provider"] for model in _requested if model["provider"] not in CONFIGURED}):
    if _provider in PROVIDERS:
        _config_error(f"Provider {_provider} is not configured (set {', '.join(_missing(_provider))})")
    else:
        _config_error(f"Unknown provider {_provider}")
for _name, _model_id in (("DEFAULT_MODEL", DEFAULT_MODEL), ("DEFAULT_UTILITY_MODEL", DEFAULT_UTILITY_MODEL)):
    if not any(model["id"] == _model_id for model in MODELS):
        _config_error(f"{_name}={_model_id} is not selectable (provider not configured, or model not in MODELS)")


def _build_client(name: str) -> AsyncAnthropic | AsyncOpenAI | None:
    if name not in CONFIGURED:
        return None
    entry = PROVIDERS[name]
    key = os.environ[entry["key_env"]]
    if entry["dialect"] == "anthropic":
        return AsyncAnthropic(api_key=key, max_retries=API_MAX_RETRIES)
    kwargs = {"api_key": key, "max_retries": API_MAX_RETRIES}
    if entry.get("base_url"):
        kwargs["base_url"] = entry["base_url"]
    return AsyncOpenAI(**kwargs)


CLIENTS = {name: _build_client(name) for name in PROVIDERS}


def resolve_model(model_id: str) -> tuple[str, str]:
    provider, model = split_model(model_id)
    entry = PROVIDERS.get(provider)
    if entry is None:
        raise LookupError(f"unknown provider: {provider}")
    if CLIENTS[provider] is None:
        raise RuntimeError(f"provider {provider} is not configured (set {', '.join(_missing(provider))})")
    return provider, model
