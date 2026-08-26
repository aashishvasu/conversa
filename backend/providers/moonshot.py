"""Moonshot (Kimi), chat.completions only.

Thinking depth rides the model id, so there is no effort lever to send.
Its $web_search is a builtin_function needing a tool_calls round trip, which conversa's single-pass
streams do not run, so no search_tool: research falls to the app finders.
"""

PROVIDER = {
    "dialect": "chat_completions",
    "key_env": "MOONSHOT_API_KEY",
    "base_url": "https://api.moonshot.ai/v1",
    "models": "moonshot/kimi-k2-thinking:Kimi K2 Thinking",
}
