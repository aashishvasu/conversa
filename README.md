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
| Every chat transcript and image | `✔️` | `❌` |
| Cards, workspaces, documents, templates | `✔️` | `❌` |
| A finished research report | `✔️` | `🟡` (Until collected, eviction, or restart) |
| Your provider API key | `❌` | `✔️` (This is the whole reason it exists) |
| The public pages chat and research read | `❌` | `🟡` (Up to `FETCH_CACHE_TTL_SECONDS`, size eviction, or restart) |
| Your password | `❌` | `✔️` |



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

Conversa is configured with environment variables set on the backend container. Here are the essentials. The full list lives in [Environment Variables](docs/Environment%20Variables.md) and the ready-to-copy template is `backend/.env.example`.

| Variable | Required | Default | What it does |
|----------|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | one provider | _(none)_ | Anthropic key. Stays on the server. |
| `OPENAI_API_KEY` | one provider | _(none)_ | OpenAI key. Stays on the server. |
| `DEEPSEEK_API_KEY` | one provider | _(none)_ | DeepSeek key. Stays on the server. |
| `APP_PASSWORD` | **yes** | _(none)_ | The password used to log in. |
| `EXA_API_KEY` | no | _(none)_ | [Exa](https://exa.ai) key. Chat and research searches try Exa first. |
| `DEFAULT_MODEL` | no | `claude-sonnet-5` | Model new conversations start with. |

You need at least one provider key and `APP_PASSWORD`. Everything else has a working default.

## Features

Conversa is a chat app at its core. Pick a model and start talking. Conversations can include images and documents, search the web, and keep the context that matters from older turns.

### Local first

Every conversation transcript, image, card, workspace, document, template, setting, and usage record lives in IndexedDB in your browser. The server only holds your provider keys, your password, active research runs, and transfer payloads, all of which are ephemeral. The rule of thumb is: 

>*"If its something durable to be stored, the client stores it."*

### Providers

Every conversation picks its own model from the providers you configure. Set one key or several, and the picker shows what is on offer.

| Dialect | Providers | API |
|---------|-----------|-----|
| `anthropic` | Anthropic | Messages |
| `responses` | OpenAI, DeepSeek | Responses |
| `chat_completions` | `compatible` | Chat Completions |

### Tools

Choose which tools the model can use in **Global settings > Tools**. Each conversation can override those choices in **Conversation settings > Tools**. Turning tools off keeps your individual choices for later, and changes apply to your next message.

| Tool | What it does |
|------|--------------|
| Web search | Finds current sources and returns links. |
| Read URLs | Reads the relevant sections of a page you provide or a search finds. |
| Date and time | Gets the current time in a named time zone, adds calendar or elapsed time, and compares dates. |
| Calculator and unit conversion | Evaluates bounded mathematical expressions and converts common units. |
| Random selection | Generates integers, samples items, or shuffles a list. An optional seed makes a result repeatable. |

Web search and URL reading can use a matching tool from the selected provider if conversa's own service is unavailable. A URL rejected by conversa's network policy does not fall back. Generic compatible models do not support tools.

### Cards, memory, recall, and templates

Four ways to bring context back without retyping it. Cards flip open at the right moment, memory keeps the gist, recall finds the old turn that matters now, and templates copy a whole conversation as a starting point.

| Feature | What it does |
|---------|--------------|
| Cards | Think flash cards for the model. Write a trigger phrase, and when the chat mentions it the card flips open and adds its instructions to the prompt. List triggers with commas for any-of, and `&` for phrases that must appear together. |
| Memory | A running summary the model keeps seeing, like a sticky note holding the gist of turns that have scrolled out of view. |
| Recall | Flips back through dropped turns and resends the few that matter now, up to three, picked by how closely they match what you just asked. |
| Templates | Copies a conversation with its cards, messages, and documents so you can start a new one from it or keep it to reuse later. |

### Research

Hand the model a question and it plays research assistant: breaks it into subquestions, searches the web, reads the pages, takes notes, and comes back with a report saved with the conversation. The run lives on the server, so it keeps going after you close the browser, and you return to a finished report.

| Phase | What happens |
|------|--------------|
| plan | Turn the goal into a list of subquestions. |
| gather | Search the web, read pages, and take notes for each subquestion. |
| gap | Plan again to fill any gaps the notes leave. |
| report | Write the report and save it as a document on the conversation. |

### Workspaces

A workspace is a shared notebook of instructions, cards, and documents that every conversation in a group reads from. Each conversation can still turn one shared card on or off for itself without touching the others.

### Import, export, and transfer

Pack up your data as JSON files or short-lived phrase codes.

| Action | What it does |
|--------|--------------|
| Export | Download a JSON file with everything, or just one conversation. |
| Import | Merge an export into your browser, keeping what you already have when ids collide. |
| Restore | Replace everything in your browser with a snapshot, after you confirm. |
| Transfer | Create a five-word phrase code another browser can retrieve within one hour. |

Conversa also imports backups from [NextChat](https://github.com/ChatGPTNextWeb/NextChat) (formerly ChatGPT-Next-Web), bringing over your chat histories and mask templates. Imports run locally in your browser and ignore any API keys or access codes the backup contains.

[MIT licensed](LICENSE). Built with Vue and FastAPI. See [DEVELOPMENT.md](DEVELOPMENT.md) for the architecture and local development setup.