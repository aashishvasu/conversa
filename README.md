<p align="center">
  <img src="frontend/public/logo.png" alt="conversa" width="96" height="96" />
</p>

# conversa

A Claude chatbot where **everything except the API call lives in your browser**.
Your conversations, settings, cards, and templates never leave your machine —
they're stored in your browser. A small server holds the Anthropic API key and
relays messages, locked behind a password you set.

## Run it

The whole app ships as a single container image (built with Podman or Docker):

```sh
podman build -t conversa -f Containerfile .
podman run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e APP_PASSWORD=your-password \
  conversa
```

Open **http://localhost:8000** and unlock with your password.

### Run it as a systemd service (Podman Quadlet)

To have systemd start and supervise the container, first store your secrets with
`podman secret` so they stay out of the unit file:

```sh
printf 'sk-ant-...' | podman secret create conversa_api_key -
printf 'your-password' | podman secret create conversa_password -
```

Then drop a `.container` quadlet file at
`~/.config/containers/systemd/conversa.container`:

```ini
[Unit]
Description=conversa

[Container]
Image=localhost/conversa:latest
PublishPort=8000:8000
Secret=conversa_api_key,type=env,target=ANTHROPIC_API_KEY
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

> Build the image first (`podman build -t conversa -f Containerfile .`) so
> `localhost/conversa:latest` exists.

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

If you started it with plain `podman run`, stop the old container and start a new
one from the rebuilt image:

```sh
git pull
podman build -t conversa -f Containerfile .
podman rm -f conversa 2>/dev/null
podman run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e APP_PASSWORD=your-password \
  --name conversa \
  conversa
```

Your conversations, settings, cards, and templates live in the browser, so an
update never touches them.

## Configuration

Set these as environment variables when you start the container.

| Variable | Required | Default | What it does |
|----------|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | **yes** | — | Your Anthropic key. Stays on the server. |
| `APP_PASSWORD` | **yes** | — | The password used to log in. |
| `JWT_SECRET` | no | random | Signs login tokens. Leave unset and every restart logs everyone out; set it to keep sessions alive across restarts. |
| `TOKEN_TTL_SECONDS` | no | `604800` | How long a login lasts (default 7 days). |
| `DEFAULT_MODEL` | no | `claude-sonnet-4-6` | Model new conversations start with. |
| `DEFAULT_TEMPERATURE` | no | `1.0` | Creativity, 0–1. |
| `DEFAULT_NUM_MESSAGES` | no | `20` | How many recent messages are sent each turn. |
| `DEFAULT_SEND_SYSTEM_PROMPT` | no | `true` | Whether system messages are sent. |
| `DEFAULT_MAX_TOKENS` | no | `4096` | Cap on reply length. |
| `DEFAULT_UTILITY_MODEL` | no | `claude-haiku-4-5` | Cheap model used for auto-titling and memory. |
| `DEFAULT_USE_MEMORY` | no | `false` | Whether old turns get compressed into memory. |
| `DEFAULT_COMPRESSION_THRESHOLD` | no | `4000` | Characters of recent chat kept verbatim before older turns are summarized. |
| `MODELS` | no | Sonnet/Opus/Haiku | Models you can pick from, as `id:Label,id:Label`. |

Every default above is just a starting point — you can change any of them globally
(in **Global settings**) or per conversation (in **Settings**).

## How it works

Most of conversa is an ordinary chat window. Three features are worth knowing about.

### Context — what the assistant always sees

Think of the **context editor** as a corkboard the assistant glances at on every
reply. Two kinds of note live there:

- **System messages** — standing instructions ("You are a terse Rust expert").
- **Pinned messages** — any normal message you've pinned. Pinned messages skip the
  recent-messages limit and are always sent, so an important detail from 200
  messages ago won't get forgotten. Pin a message with the 📌 button, or manage
  everything together in the context editor.

### Cards — notes that appear only when relevant

A **card** is like an index card in a box. Each card has some **trigger words** and
a **note**. Before every reply, conversa scans your recent messages; if a card's
trigger word shows up, that card's note is quietly handed to the assistant for
that reply — and dropped again once the word stops coming up.

It's a lightweight way to give the assistant background knowledge ("when I say
*Aria*, that's my D&D character, a half-elf rogue…") without pasting it into every
message or burning tokens on context you don't currently need.

### Memory — so long chats don't get forgotten or expensive

Turn on **memory** and conversa keeps a running summary of the older parts of a
conversation (written by the cheap utility model) instead of re-sending every
message forever. Recent messages stay word-for-word; everything past the
threshold gets folded into the summary. You can read, edit, or clear that summary
in **Settings**.

### Templates

Set up a conversation the way you like — system messages, cards, settings, a few
seed messages — and save it as a **template**. Starting from a template clones all
of that into a fresh conversation. Templates live in the sidebar.

---

Built with Vue + FastAPI. For the stack, architecture, and local development,
see **[DEVELOPMENT.md](DEVELOPMENT.md)**.
