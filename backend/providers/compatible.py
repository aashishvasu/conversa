"""One configurable OpenAI-compatible chat.completions endpoint.

Set OPENAI_COMPATIBLE_API_KEY and OPENAI_COMPATIBLE_BASE_URL, then list models under the `compatible/` prefix in MODELS.
This entry sends text and reads text plus optional reasoning_content. It has no hosted tools or explicit cache controls.
"""

import os

PROVIDER = {
    "dialect": "chat_completions",
    "key_env": "OPENAI_COMPATIBLE_API_KEY",
    "base_url_env": "OPENAI_COMPATIBLE_BASE_URL",
    "base_url": os.environ.get("OPENAI_COMPATIBLE_BASE_URL"),
    "models": "",
}
