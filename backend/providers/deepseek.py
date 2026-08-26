"""DeepSeek through its Responses API, with hosted web search, image input, and reasoning on every listed model."""

PROVIDER = {
    "dialect": "responses",
    "key_env": "DEEPSEEK_API_KEY",
    "base_url": "https://api.deepseek.com",
    "search_tool": "web_search",
    "models": "deepseek/deepseek-v4-pro:DeepSeek V4 Pro,deepseek/deepseek-v4-flash:DeepSeek V4 Flash",
}
