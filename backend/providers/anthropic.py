"""Anthropic: the messages dialect, server-side search and fetch tools, and two thinking formats."""

import os

# The model invokes hosted search when a message warrants it; an empty value disables Anthropic hosted search.
SEARCH_TOOL = os.environ.get("WEB_SEARCH_TOOL_VERSION", "web_search_20250305")
# Server-side page opening uses this tool and beta header.
FETCH_TOOL = os.environ.get("WEB_FETCH_TOOL_VERSION", "web_fetch_20250910")
FETCH_BETA = os.environ.get("WEB_FETCH_BETA", "web-fetch-2025-09-10")

# These models use fixed token budgets and accept temperature. Other ids use adaptive thinking and reject temperature.
# Unknown ids follow the adaptive format. Add an id here when MODELS exposes another fixed-budget model.
LEGACY_MODELS = {
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-sonnet-4-0",
    "claude-opus-4-0",
    "claude-3-haiku-20240307",
}

# Legacy effort levels map to fixed budgets. Adaptive models size thinking from the qualitative effort value.
LEGACY_EFFORT_BUDGETS = {"low": 4000, "medium": 10000, "high": 24000}

# USD per million tokens, input then output, bare model id -> rate. Update when published rates change.
PRICES = {
    "claude-fable-5": (10, 50), "claude-mythos-5": (10, 50),
    "claude-opus-5": (5, 25), "claude-opus-4-8": (5, 25), "claude-opus-4-7": (5, 25),
    "claude-opus-4-6": (5, 25), "claude-sonnet-5": (3, 15), "claude-sonnet-4-6": (3, 15),
    "claude-haiku-4-5": (1, 5),
}

PROVIDER = {
    "dialect": "anthropic",
    "key_env": "ANTHROPIC_API_KEY",
    "search_tool": SEARCH_TOOL,
    "fetch_tool": FETCH_TOOL,
    "fetch_beta": FETCH_BETA,
    "prices": PRICES,
    # Bare model ids belong to Anthropic (see split_model).
    "models": (
        "claude-fable-5:Fable 5,"
        "claude-opus-5:Opus 5,claude-sonnet-5:Sonnet 5,claude-opus-4-8:Opus 4.8,"
        "claude-sonnet-4-6:Sonnet 4.6,claude-haiku-4-5:Haiku 4.5"
    ),
}
