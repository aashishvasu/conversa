"""OpenAI: the Responses dialect, one hosted tool covering both search and page opening."""

import os

# One tool covers both searching and opening pages, so it stands in for Anthropic's two.
# Empty disables it, in chat and as a research finder both.
SEARCH_TOOL = os.environ.get("OPENAI_WEB_SEARCH_TOOL", "web_search")

# Reasoning models take reasoning.effort and reject temperature; older chat models are the inverse.
# Prefix match, hand-maintained like anthropic.py's LEGACY_MODELS.
REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

PROVIDER = {
    "dialect": "responses",
    "key_env": "OPENAI_API_KEY",
    "search_tool": SEARCH_TOOL,
    "reasoning_prefixes": REASONING_PREFIXES,
    "models": (
        "openai/gpt-5.6-sol:GPT-5.6 Sol,openai/gpt-5.6-terra:GPT-5.6 Terra,"
        "openai/gpt-5.6-luna:GPT-5.6 Luna,openai/gpt-5.5:GPT-5.5,"
        "openai/gpt-5-mini:GPT-5 Mini"
    ),
}
