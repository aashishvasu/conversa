<p align="center">
  <img src="frontend/public/logo.png" alt="conversa" width="96" height="96" />
</p>

# conversa

*The small, private, multi-provider, chat assistant for **you.***

All conversation data lives in the browser.

All you need are provider API keys (currently Anthropic, OpenAI and DeepSeek are supported), and set a password. The server sets up the frontend, streams chats, relays model streams, fetches pages, and keeps research runs going after the browser closes. Everything else lands in your browser, gets stored locally.

Want to create a shortcut on mobile devices? You can do that too.

Who ends up holding what:

| What | In your browser | On the server |
|------|-----------------|---------------|
| Every chat transcript and image | ✔️ | ❌ |
| Cards, workspaces, documents, templates | ✔️ | ❌ |
| A finished research report | ✔️ | 🟡 (Until collected, eviction, or restart) |
| Your provider API key | ❌ | ✔️ (This is the whole reason it exists) |
| The public pages chat and research read | ❌ | 🟡 (Up to `FETCH_CACHE_TTL_SECONDS`, size eviction, or restart) |
| Your password | ❌ | ✔️ (As the env var you set it to) |



## Run it

The whole app ships as a single container image (built with Podman or Docker):

```sh
podman build -t conversa -f Containerfile .
podman run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e OPENAI_API_KEY=sk-... \
  -e APP_PASSWORD=your-password \
  conversa
```

Open **http://localhost:8000** and unlock with your password.

Any configured provider is enough.
Set several to pick between their models per conversation.
The model picker contains models from configured providers. A `MODELS` entry with incomplete provider configuration produces a banner on first load.

Conversa supports Anthropic's Messages API, OpenAI's Responses API, and DeepSeek's Responses API.
The `compatible` entry serves one chat.completions endpoint at a time. Set its key and base URL, then list models with the `compatible/` prefix. It sends text and image messages, and reads text plus `reasoning_content`. Research through this entry uses Exa, Brave, or SearXNG.

Attach images from the picker, clipboard, or a drag-drop. Conversa keeps them in your browser, and sends them with the chat turn.

### Run it as a systemd service (Podman Quadlet)

To have systemd start and supervise the container, first store your secrets with `podman secret` so they stay out of the unit file:

```sh
printf 'sk-ant-...' | podman secret create conversa_api_key -
printf 'sk-...' | podman secret create conversa_openai_key -
printf 'your-password' | podman secret create conversa_password -
```

Then drop a `.container` quadlet file at `~/.config/containers/systemd/conversa.container`:

```ini
[Unit]
Description=conversa

[Container]
Image=localhost/conversa:latest
PublishPort=8000:8000
Secret=conversa_api_key,type=env,target=ANTHROPIC_API_KEY
Secret=conversa_openai_key,type=env,target=OPENAI_API_KEY
Secret=conversa_password,type=env,target=APP_PASSWORD

[Service]
Restart=always

[Install]
WantedBy=default.target
```

Then reload and start it:

```sh
systemctl --user daemon-reload
systemctl --user start conversa
```

> Build the image first (`podman build -t conversa -f Containerfile .`) so `localhost/conversa:latest` exists.

> Want to run the frontend and backend separately for development?
> See [DEVELOPMENT.md](DEVELOPMENT.md).

## Updating

Pull the latest code, rebuild the image, and restart the container.

If you run it under systemd (Quadlet):

```sh
git pull
podman build -t conversa -f Containerfile .
systemctl --user restart conversa
```

If you started it with plain `podman run`, stop the old container and start a new one from the rebuilt image:

```sh
git pull
podman build -t conversa -f Containerfile .
podman rm -f conversa 2>/dev/null
podman run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e OPENAI_API_KEY=sk-... \
  -e APP_PASSWORD=your-password \
  --name conversa \
  conversa
```

Your conversations, settings, cards, workspaces, documents, and templates live in the browser, so an update leaves all of them intact.

## Configuration

Set these as environment variables when you start the container.

| Variable | Required | Default | What it does |
|----------|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | one key | _(none)_ | Your Anthropic key. Stays on the server. |
| `OPENAI_API_KEY` | one key | _(none)_ | Your OpenAI key. Stays on the server. |
| `DEEPSEEK_API_KEY` | one key | _(none)_ | Your DeepSeek key. DeepSeek models and hosted web search appear once it is set. |
| `OPENAI_COMPATIBLE_API_KEY` | one key | _(none)_ | Key for one generic chat.completions endpoint. Requires `OPENAI_COMPATIBLE_BASE_URL`. |
| `OPENAI_COMPATIBLE_BASE_URL` | with compatible key | _(none)_ | Base URL for that endpoint, for example `https://api.moonshot.ai/v1`. |
| `APP_PASSWORD` | **yes** | _(none)_ | The password used to log in. |
| `JWT_SECRET` | no | random | Signs login tokens. A fixed value keeps sessions valid across restarts; the random default gives each process a new signing key. |
| `TOKEN_TTL_SECONDS` | no | `604800` | How long a login lasts (default 7 days). |
| `DEFAULT_MODEL` | no | `claude-sonnet-5` | Model new conversations start with. |
| `DEFAULT_TEMPERATURE` | no | `1.0` | Creativity, 0 to 1. Claude 4.6+ and Responses reasoning models receive no temperature; older Claude models receive it when thinking is off. |
| `DEFAULT_NUM_MESSAGES` | no | `20` | How many recent messages are sent each turn. |
| `DEFAULT_SEND_SYSTEM_PROMPT` | no | `true` | Whether system messages are sent. |
| `DEFAULT_MAX_TOKENS` | no | `4096` | Cap on reply length. |
| `DEFAULT_EFFORT` | no | *(off)* | Thinking effort new conversations start with: empty, `low`, `medium`, or `high`. |
| `DEFAULT_UTILITY_MODEL` | no | `claude-haiku-4-5` | Cheap model used for auto-titling and memory. |
| `DEFAULT_USE_MEMORY` | no | `false` | Whether older turns get summarized into memory. |
| `DEFAULT_SUMMARIZE_N` | no | `20` | How many turns just above the send window get summarized into memory. |
| `DEFAULT_USE_RECALL` | no | `false` | Whether relevant dropped turns get resent verbatim. |
| `DEFAULT_USE_CACHE` | no | `false` | Whether the stable part of the prompt is cached by the provider. Off by default because it only pays back in long conversations with a large shared context. |
| `MODELS` | no | _(none)_ | **Extra** models to offer, as `provider/id:Label,id:Label`, appended to the built-in list. The label is optional. The provider is optional and defaults to `anthropic`, so `claude-opus-5` and `anthropic/claude-opus-5` mean the same model; every other provider's ids need its prefix (`openai/`, `deepseek/`, `compatible/`). Models older than Claude 4.6 use an earlier thinking format, so add their id to `LEGACY_MODELS` in `backend/providers/anthropic.py`. |
| `WEB_SEARCH_TOOL_VERSION` | no | `web_search_20250305` | Anthropic hosted-search version used when app search is unavailable. Set empty to disable that fallback. |
| `WEB_FETCH_TOOL_VERSION` | no | `web_fetch_20250910` | Anthropic hosted-fetch version used when app fetching is unavailable. Set empty to disable that fallback. |
| `WEB_FETCH_BETA` | no | `web-fetch-2025-09-10` | Beta header the hosted-fetch fallback requires. |
| `EXA_API_KEY` | no | _(none)_ | [Exa](https://exa.ai) key. Chat and research searches try Exa first. |
| `BRAVE_API_KEY` | no | _(none)_ | [Brave Search](https://brave.com/search/api/) key. Used when Exa is absent or fails. |
| `SEARXNG_URL` | no | _(none)_ | Base URL of a self-hosted SearXNG instance (`format=json` must be enabled in its settings.yml). Used after Exa and Brave. |
| `FETCH_CACHE_TTL_SECONDS` | no | `1800` | How long an extracted public page stays in the bounded process-local cache. Zero disables caching. |
| `DEFAULT_RESEARCH_SEARCH_MODEL` | no | `DEFAULT_MODEL` | Model that runs the searches in a research run when no app search key above is set, and the fallback when one fails. |
| `DEFAULT_RESEARCH_NOTE_MODEL` | no | `DEFAULT_UTILITY_MODEL` | Model that reads pages and takes notes. Around 78% of a run's input tokens, so a cheap model belongs here. |
| `DEFAULT_RESEARCH_REPORT_MODEL` | no | `DEFAULT_MODEL` | Model that plans the subquestions and writes the report. |
| `DEFAULT_RESEARCH_DEPTH` | no | `5` | Sources read per subquestion. |
| `API_MAX_RETRIES` | no | `5` | Provider retries on 429, 5xx and connection errors. A research run makes about 30 model calls. |
| `OPENAI_WEB_SEARCH_TOOL` | no | `web_search` | OpenAI's hosted search and page-opening tool. Set empty to disable OpenAI hosted search. |

Change any of them globally (in **Global settings**) or per conversation (in **Conversation settings**).

## Features

Conversa starts as a normal chat app. Pick a model and talk. Conversations can include images and documents, search the web, and keep useful context from older turns.

- Anthropic, OpenAI, DeepSeek, and compatible chat-completions providers
- Research that gathers sources and returns a report in the conversation
- Workspaces for context shared across related chats
- Cards, memory, recall, and templates for context you want to reuse
- Browser-local conversations, documents, settings, and usage history
- Backups and short-lived transfers between devices

[MIT licensed](LICENSE). Built with Vue and FastAPI. See [DEVELOPMENT.md](DEVELOPMENT.md) for the architecture and local development setup.