<p align="center">
  <img src="frontend/public/logo.png" alt="conversa" width="96" height="96" />
</p>

# conversa

*The small, private, multi-provider chat assistant for **you.***

**Multiple providers**: Conversa lets you chat with models from Anthropic, OpenAI, DeepSeek, and any other OpenAI completions API-compatible services in one place. Bring your own API key, choose a model, and keep your conversations in your browser, not the server.

**Small != barebones**: Add images and documents, search the web, or ask for a research report. A reply or research run can keep going while your browser is closed, ready for you to pick up when you return.

Want to create a shortcut on mobile devices? You can do that too.

## Your data

The server sends all the data it generates to your browser. Your conversations, images, settings, and other saved data stay browser-side. They will never automatically appear on your other devices, use export or transfer to move them.

Your messages and attachments are sent to the model provider you choose when you hit send.

| What | In your browser | On the server |
|------|-----------------|---------------|
| Every chat transcript and image | `✔️` | `❌` |
| Cards, workspaces, documents, templates | `✔️` | `❌` |
| A normal chat reply | `✔️` | `🟡` Until fully sent to browser, expiry, or server restart |
| A finished research report | `✔️` | `🟡` Until collected by browser, eviction, or server restart |
| Your provider API key | `❌` | `✔️` |
| Websites that chat or research searched/fetched | `❌` | `🟡` Until cache expiry, eviction, or server restart |
| Your password | `❌` | `✔️` |

The server can also temporarily hold data during device to device chat transfers.

## Run it

Conversa runs as a container. You need Podman or Docker (I prefer podman), a password of your choice, and at least one model provider's API key. For example, with Podman and Anthropic:

```sh
git clone https://github.com/aashishvasu/conversa.git
cd conversa
podman build -t conversa -f Containerfile .
podman run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e APP_PASSWORD=your-password \
  --name conversa \
  conversa
```

Open **http://localhost:8000** and unlock it with your password. You can configure more than one provider and choose between their models in each conversation.

### Run it as a systemd service (via Podman Quadlet)

Build the image first, then store your secrets with `podman secret` so they stay out of the unit file. Configure at least one provider key:

```sh
printf 'sk-ant-...' | podman secret create conversa_api_key -
printf 'sk-...' | podman secret create conversa_openai_key -
printf 'your-password' | podman secret create conversa_password -
```

Create `~/.config/containers/systemd/conversa.container`:

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

Remove a provider's `Secret` line if you haven't configured its key. Then reload and start the service:

```sh
systemctl --user daemon-reload
systemctl --user start conversa
```

For local development, see [DEVELOPMENT.md](DEVELOPMENT.md).

### Configuration

Set environment variables on the backend container. The full list is in [Environment Variables](docs/Environment%20Variables.md), and a template is in `backend/.env.example`.

| Variable | Required | Default | What it does |
|----------|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | one provider | _(none)_ | Anthropic key. |
| `OPENAI_API_KEY` | one provider | _(none)_ | OpenAI key. |
| `DEEPSEEK_API_KEY` | one provider | _(none)_ | DeepSeek key. |
| `APP_PASSWORD` | yes | _(none)_ | Password used to log in. |
| `EXA_API_KEY` | no | _(none)_ | Exa key for web search. |
| `DEFAULT_MODEL` | no | `claude-sonnet-5` | Model new conversations start with. |

## Features

### Chat and providers

Choose a model for each conversation. Add images from the picker, clipboard, or by dragging and dropping them. Attach documents to give the model more context.

### Tools

Choose which tools the model can use in **Global settings > Tools**, with per-conversation overrides in **Conversation settings > Tools**. Changes apply to your next message. Generic compatible models do not support tools.

| Tool | What it does |
|------|--------------|
| Web search | Finds current sources and returns links. |
| Read URLs | Reads pages you provide or a search finds. |
| Date and time | Works with dates, times, and time zones. |
| Calculator and unit conversion | Evaluates expressions and converts units. |
| Random selection | Generates numbers, samples items, or shuffles a list. |

### Cards, memory, recall, and templates

Four ways to bring context back without retyping it:

| Feature | What it does |
|---------|--------------|
| Cards | Add instructions when a conversation mentions your chosen trigger phrases. Use commas for any-of triggers and `&` for phrases that must appear together. |
| Memory | Keeps a summary of earlier turns available to the model. |
| Recall | Finds relevant earlier turns and sends them with your message. |
| Templates | Copy a conversation, including its cards, messages, and documents, as a starting point. |

### Research

Ask a question and Conversa can search the web, read sources, and prepare a report saved with your conversation. It may ask you to clarify the request before starting. You can close the browser and return while the run is in progress or after it finishes. The research stays on the server only during progress and while it's waiting to be shown in the browser. After its stored in your browser session, its removed from the server.

### Workspaces

Group conversations around shared instructions, cards, and documents. Each conversation can turn shared cards on or off without changing them for the rest of the workspace.

### Import, export, and transfer

| Action | What it does |
|--------|--------------|
| Export | Download a backup of everything or a single conversation. |
| Import | Add an export to your browser without replacing existing items with the same IDs. |
| Restore | Replace your browser's saved data with a snapshot, after confirmation. |
| Transfer | Use a five-word phrase to move data to another browser within one hour. |

Conversa also imports chat histories and mask templates from [NextChat](https://github.com/ChatGPTNextWeb/NextChat) backups. Imports run in your browser and ignore API keys and access codes set for NextChat in the backup.

> [!WARNING]
> Clearing browser data or cache clears Conversa storage. Keep regular backups of conversations that are important. Similarly, because the server does not store any chats permanently, if it restarts during an operation (research, chat), that operation is lost.

## Updating

For the podman quadlet/systemd service, pull the latest code, rebuild the image, and restart it:

```sh
git pull
podman build -t conversa -f Containerfile .
systemctl --user restart conversa
```

For the plain Podman setup above, replace the container:

```sh
git pull
podman build -t conversa -f Containerfile .
podman rm -f conversa
podman run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e APP_PASSWORD=your-password \
  --name conversa \
  conversa
```

Use the same provider keys and password as before. Your saved conversations and settings stay in your browser during the update.

[MIT licensed](LICENSE). Built with Vue and FastAPI.
