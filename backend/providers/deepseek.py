"""DeepSeek, on the Responses dialect.

It serves all three dialects (api-docs.deepseek.com, read 2026-08-26), and Responses is the one
carrying hosted web search and image input; its chat.completions endpoint takes function tools only.
Every model it offers reasons, so there are no reasoning_prefixes to list.
"""

PROVIDER = {
    "dialect": "responses",
    "key_env": "DEEPSEEK_API_KEY",
    "base_url": "https://api.deepseek.com",
    "search_tool": "web_search",
    "models": "deepseek/deepseek-v4-pro:DeepSeek V4 Pro,deepseek/deepseek-v4-flash:DeepSeek V4 Flash",
}
