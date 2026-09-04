"""OpenAI: the Responses dialect, one hosted tool covering both search and page opening."""

import os

# This tool covers search and page opening; an empty value disables OpenAI hosted search.
SEARCH_TOOL = os.environ.get("OPENAI_WEB_SEARCH_TOOL", "web_search")

# Matching models take reasoning.effort and reject temperature. Other ids receive temperature.
# Keep this prefix list aligned with the models exposed above.
REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

# USD per million tokens, input then output. Update when published rates change.
PRICES = {
    "gpt-5.6-sol": (4, 20), "gpt-5.6-terra": (2, 12), "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.5": (5, 30), "gpt-5-mini": (0.25, 2.0),
}

PROVIDER = {
    "dialect": "responses",
    "key_env": "OPENAI_API_KEY",
    "search_tool": SEARCH_TOOL,
    "reasoning_prefixes": REASONING_PREFIXES,
    "prices": PRICES,
    "models": (
        "openai/gpt-5.6-sol:GPT-5.6 Sol,openai/gpt-5.6-terra:GPT-5.6 Terra,"
        "openai/gpt-5.6-luna:GPT-5.6 Luna,openai/gpt-5.5:GPT-5.5,"
        "openai/gpt-5-mini:GPT-5 Mini"
    ),
}
