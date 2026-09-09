"""DeepSeek through its Responses API, with hosted web search, image input, and reasoning on every listed model."""

# USD per million tokens, input then output, peak-hours cache-miss rate. Update when published rates change.
# DeepSeek discounts cache-hit input to roughly 3-5% of this rate and halves both rates off-peak; cost()
# has no per-provider cache multiplier or time-of-day rate yet, so both discounts currently read as spend.
PRICES = {
    "deepseek-v4-pro": (1.32, 3.96),
    "deepseek-v4-flash": (0.44, 1.32),
}

PROVIDER = {
    "dialect": "responses",
    "key_env": "DEEPSEEK_API_KEY",
    "base_url": "https://api.deepseek.com",
    "search_tool": "web_search",
    "prices": PRICES,
    "models": "deepseek/deepseek-v4-pro:DeepSeek V4 Pro,deepseek/deepseek-v4-flash:DeepSeek V4 Flash",
}
