"""Anthropic: the messages dialect, server-side search and fetch tools, and two thinking formats."""

import os

# Model-invoked: it searches only when a message warrants it.
# Empty disables it, in chat and as a research finder both.
SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL_VERSION", "web_search_20250305")
# Lets the model open a URL the user pastes. Beta-gated, hence the header below.
FETCH_TOOL = os.environ.get("WEB_FETCH_TOOL_VERSION", "web_fetch_20250910")
FETCH_BETA = os.environ.get("WEB_FETCH_BETA", "web-fetch-2025-09-10")

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

PROVIDER = {
    "dialect": "anthropic",
    "key_env": "ANTHROPIC_API_KEY",
    "search_tool": SEARCH_TOOL,
    "fetch_tool": FETCH_TOOL,
    "fetch_beta": FETCH_BETA,
    # Bare ids, no prefix: unprefixed means Anthropic permanently (see split_model).
    "models": (
        "claude-fable-5:Fable 5,"
        "claude-opus-5:Opus 5,claude-sonnet-5:Sonnet 5,claude-opus-4-8:Opus 4.8,"
        "claude-sonnet-4-6:Sonnet 4.6,claude-haiku-4-5:Haiku 4.5"
    ),
}
