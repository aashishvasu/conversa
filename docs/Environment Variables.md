# Environment variables

Set these as environment variables when you start the backend container or local server. Apart from one provider API key, rest are optional. Conversa chooses its own defaults if not provided.

| Variable | Required | Default | What it does |
|----------|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | one provider | _(none)_ | Anthropic key. Stays on the server. |
| `OPENAI_API_KEY` | one provider | _(none)_ | OpenAI key. Stays on the server. |
| `DEEPSEEK_API_KEY` | one provider | _(none)_ | DeepSeek key. Stays on the server. |
| `OPENAI_COMPATIBLE_API_KEY` | one provider | _(none)_ | Key for one generic chat.completions endpoint. Requires `OPENAI_COMPATIBLE_BASE_URL`. |
| `OPENAI_COMPATIBLE_BASE_URL` | with compatible key | _(none)_ | Base URL for that endpoint, for example `https://api.moonshot.ai/v1`. |
| `APP_PASSWORD` | **yes** | _(none)_ | The password used to log in. |
| `JWT_SECRET` | no | random | Signs login tokens. A fixed value keeps sessions valid across restarts. |
| `TOKEN_TTL_SECONDS` | no | `604800` | How long a login lasts. |
| `LOGIN_RATE_LIMIT` | no | `5/minute` | Login attempts allowed per client IP. Format: `<count>/<second|minute|hour|day>`. |
| `DEFAULT_MODEL` | no | `claude-sonnet-5` | Model new conversations start with. |
| `DEFAULT_TEMPERATURE` | no | `1.0` | Creativity, 0 to 1. Claude 4.6+ and Responses reasoning models receive no temperature; older Claude models receive it when thinking is off. |
| `DEFAULT_NUM_MESSAGES` | no | `20` | How many recent messages are sent each turn. |
| `DEFAULT_SEND_SYSTEM_PROMPT` | no | `true` | Whether system messages are sent. |
| `DEFAULT_STRUCTURE_SYSTEM_PROMPT` | no | `false` | Whether the system prompt is sent as named parts for the server to render into tagged text. |
| `DEFAULT_MAX_TOKENS` | no | `4096` | Cap on reply length. |
| `DEFAULT_EFFORT` | no | *(off)* | Thinking effort new conversations start with: empty, `low`, `medium`, or `high`. |
| `DEFAULT_UTILITY_MODEL` | no | `claude-haiku-4-5` | Cheap model used for auto-titling and memory. |
| `DEFAULT_USE_MEMORY` | no | `false` | Whether older turns get summarized into memory. |
| `DEFAULT_SUMMARIZE_N` | no | `20` | How many turns just above the send window get summarized into memory. |
| `DEFAULT_USE_RECALL` | no | `false` | Whether relevant dropped turns get resent verbatim. |
| `DEFAULT_USE_CACHE` | no | `false` | Whether the stable prompt block is cached when the selected provider supports it. |
| `DEFAULT_TOOLS_ENABLED` | no | `true` | Master switch for the model-callable tools below. Off omits all of them from the provider schema. |
| `DEFAULT_TOOL_WEB_SEARCH` | no | `true` | Whether `search_web` is offered. |
| `DEFAULT_TOOL_FETCH_URL` | no | `true` | Whether `fetch_url` is offered. |
| `DEFAULT_TOOL_DATETIME` | no | `true` | Whether `datetime` is offered. |
| `DEFAULT_TOOL_CALCULATOR` | no | `true` | Whether `calculator` is offered. |
| `DEFAULT_TOOL_RANDOM` | no | `true` | Whether `random` is offered. |
| `DEFAULT_TOOL_MAX_ROUNDS` | no | `4` | Max model responses with tool calls per chat turn. |
| `DEFAULT_TOOL_MAX_CALLS` | no | `16` | Max total tool calls per chat turn. |
| `WEB_SEARCH_TOOL_VERSION` | no | `web_search_20250305` | Anthropic hosted-search version used when app search is unavailable. Set empty to disable that fallback. |
| `WEB_FETCH_TOOL_VERSION` | no | `web_fetch_20250910` | Anthropic hosted-fetch version used when app fetching is unavailable. Set empty to disable that fallback. |
| `WEB_FETCH_BETA` | no | `web-fetch-2025-09-10` | Beta header the hosted-fetch fallback requires. |
| `OPENAI_WEB_SEARCH_TOOL` | no | `web_search` | OpenAI's hosted search and page-opening tool. Set empty to disable OpenAI hosted search. |
| `EXA_API_KEY` | no | _(none)_ | [Exa](https://exa.ai) key. Chat and research searches try Exa first. |
| `BRAVE_API_KEY` | no | _(none)_ | [Brave Search](https://brave.com/search/api/) key. Used when Exa is absent or fails. |
| `SEARXNG_URL` | no | _(none)_ | Base URL of a self-hosted SearXNG instance (`format=json` must be enabled in its settings.yml). Used after Exa and Brave. |
| `FETCH_CACHE_TTL_SECONDS` | no | `1800` | How long an extracted public page stays in the bounded process-local cache. Zero disables caching. |
| `DEFAULT_RESEARCH_SEARCH_MODEL` | no | `DEFAULT_MODEL` | Model that runs searches when no app search key is set, and the fallback when one fails. |
| `DEFAULT_RESEARCH_NOTE_MODEL` | no | `DEFAULT_UTILITY_MODEL` | Model that reads pages and takes notes. Around 78% of a run's input tokens, so a cheap model belongs here. |
| `DEFAULT_RESEARCH_REPORT_MODEL` | no | `DEFAULT_MODEL` | Model that plans subquestions and writes the report. |
| `DEFAULT_RESEARCH_DEPTH` | no | `5` | Sources read per subquestion. |
| `RESEARCH_MIN_SOURCES` | no | `8` | Minimum source count target for a research run. |
| `RESEARCH_MAX_SOURCES` | no | `24` | Maximum source count for a research run. |
| `RESEARCH_MIN_EVIDENCE` | no | `8` | Minimum evidence count used before report writing. |
| `RESEARCH_MAX_SECONDS` | no | `900` | Minimum elapsed-time budget in seconds. Large source budgets can raise it. |
| `RESEARCH_MAX_WAVES` | no | `8` | Max research coordination waves. |
| `RESEARCH_MAX_TASKS` | no | `18` | Max research tasks. |
| `RESEARCH_MAX_CALLS` | no | computed | Optional hard model-call cap for a research run. Empty computes it from source, task, wave, and report limits. |
| `MAX_ACTIVE_RUNS` | no | `2` | Concurrent research runs allowed on the server. |
| `RESEARCH_RESULT_TTL` | no | `3600` | Seconds a finished server-side research result remains available for collection. |
| `API_MAX_RETRIES` | no | `5` | Provider retries on 429, 5xx, and connection errors. |
| `TRANSFER_TTL_SECONDS` | no | `3600` | Seconds a transfer phrase remains retrievable. |
| `TRANSFER_MAX_ENTRY_BYTES` | no | `10000000` | Max bytes for one transfer payload. |
| `TRANSFER_MAX_TOTAL_BYTES` | no | `50000000` | Max bytes held across all transfer payloads. |
| `TRANSFER_MAX_ENTRIES` | no | `32` | Max transfer payloads held at once. |
| `MODELS` | no | _(none)_ | **Extra** models to offer, as `provider/id:Label,id:Label`, appended to the built-in list. The label is optional. The provider is optional and defaults to `anthropic`, so `claude-opus-5` and `anthropic/claude-opus-5` mean the same model; every other provider's ids need its prefix (`openai/`, `deepseek/`, `compatible/`). Models older than Claude 4.6 use an earlier thinking format, so add their id to `LEGACY_MODELS` in `backend/providers/anthropic.py`. |
| `CORS_ORIGINS` | no | `*` | Dev-only comma-separated origins allowed by the backend. Production serves the SPA and API from one origin. |

The `DEFAULT_*` conversation and research defaults can also be changed in **Global settings** or per conversation in **Conversation settings**.
