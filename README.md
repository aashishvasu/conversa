<p align="center">
  <img src="frontend/public/logo.png" alt="conversa" width="96" height="96" />
</p>

# conversa

A Claude chatbot where **everything except the API call lives in your browser**.
Your conversations, settings, cards, workspaces, and templates never leave your
machine — they're stored in your browser. A small server holds the Anthropic API
key and relays messages, locked behind a password you set.

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

Your conversations, settings, cards, workspaces, and templates live in the
browser, so an update never touches them.

## Configuration

Set these as environment variables when you start the container.

| Variable | Required | Default | What it does |
|----------|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | **yes** | — | Your Anthropic key. Stays on the server. |
| `APP_PASSWORD` | **yes** | — | The password used to log in. |
| `JWT_SECRET` | no | random | Signs login tokens. Leave unset and every restart logs everyone out; set it to keep sessions alive across restarts. |
| `TOKEN_TTL_SECONDS` | no | `604800` | How long a login lasts (default 7 days). |
| `DEFAULT_MODEL` | no | `claude-sonnet-5` | Model new conversations start with. |
| `DEFAULT_TEMPERATURE` | no | `1.0` | Creativity, 0–1. |
| `DEFAULT_NUM_MESSAGES` | no | `20` | How many recent messages are sent each turn. |
| `DEFAULT_SEND_SYSTEM_PROMPT` | no | `true` | Whether system messages are sent. |
| `DEFAULT_MAX_TOKENS` | no | `4096` | Cap on reply length. |
| `DEFAULT_EFFORT` | no | *(off)* | Thinking effort new conversations start with: empty, `low`, `medium`, or `high`. |
| `DEFAULT_UTILITY_MODEL` | no | `claude-haiku-4-5` | Cheap model used for auto-titling and memory. |
| `DEFAULT_USE_MEMORY` | no | `false` | Whether older turns get summarized into memory. |
| `DEFAULT_SUMMARIZE_N` | no | `20` | How many turns just above the send window get summarized into memory. |
| `DEFAULT_USE_RECALL` | no | `false` | Whether relevant dropped turns get resent verbatim. |
| `MODELS` | no | _(none)_ | **Extra** models to offer, as `id:Label,id:Label` — appended to the built-in Sonnet/Opus/Haiku list, which is always available. Models older than Claude 4.6 need their id added to `LEGACY_MODELS` in `backend/main.py` — they use an older thinking format. |
| `WEB_SEARCH_TOOL_VERSION` | no | `web_search_20250305` | Anthropic web-search tool version; the model searches on its own when a message needs it. Empty disables it. |
| `WEB_FETCH_TOOL_VERSION` | no | `web_fetch_20250910` | Anthropic web-fetch tool version; lets the model open a URL you paste in chat. Empty disables it. |
| `WEB_FETCH_BETA` | no | `web-fetch-2025-09-10` | Beta header the web-fetch tool requires. |

Every default above is just a starting point — you can change any of them globally
(in **Global settings**) or per conversation (in **Conversation settings**).

## How it works

Most of conversa is an ordinary chat window. A few features are worth knowing about.

### Context: what the assistant always sees

Think of the **context editor** as a corkboard the assistant glances at on every
reply. Two kinds of note live there:

- **System messages** — standing instructions ("You are a terse Rust expert").
- **Pinned messages** — any normal message you've pinned. Pinned messages skip the
  recent-messages limit and are always sent, so an important detail from 200
  messages ago won't get forgotten. Pin a message with the 📌 button, or manage
  everything together in the context editor.

### Cards: notes that appear only when relevant

A **card** is like an index card in a box. Each card has some **trigger phrases** and
a **note**. Before every reply, conversa scans your recent messages; if a card's
trigger phrase shows up, that card's note is quietly handed to the assistant for
that reply — and dropped again once the word stops coming up.

It's a lightweight way to give the assistant background knowledge ("when I say
*Aria*, that's my D&D character, a half-elf rogue…") without pasting it into every
message or burning tokens on context you don't currently need.

Triggers are comma-separated, and commas mean *or* — any one phrase fires the
card. Use `&` when a card should only fire if several words all appear:
`dragon & red, wyrm` triggers on "wyrm", or on "dragon" and "red" both showing
up in recent messages.

You can override the trigger matching per card with two buttons on the card's
row: **force include** (✓) always sends the card regardless of triggers, and
**force skip** (⃠) never sends it. Click again to clear the override and return
to normal trigger matching. Forced-include and triggered cards show green;
force-skip shows yellow. To keep cards tidy, give a card a **folder** name and
it'll group under that heading — purely visual, it has no effect on triggering.

### Memory: so long chats don't get forgotten or expensive

Turn on **Compress history into memory** and conversa keeps a summary of the
messages just above the recent-messages window (written by the cheap utility
model) instead of re-sending them verbatim. The summary refreshes in the
background after each reply, so sending never waits on it. Recent messages stay
word-for-word; anything older than both windows drops out (recall below brings
it back when relevant). You can read, edit, or clear the summary in
**Conversation settings**.

### Recall: old messages that suddenly matter again

Turn on **Recall relevant old messages** and, before each reply, conversa looks at the
turns that fell outside the recent-messages limit and re-sends the few that overlap
most with what you just asked — verbatim, as reference. Ask "what was the dragon
called again?" 200 messages later and the turn that names it comes back.

Recall rewrites nothing — the turns come back verbatim. The two work fine together.

### Thinking effort

The brain picker in the composer toolbar (also in **Conversation settings** and
**Global settings**) turns on extended thinking: **Off**, **Low**, **Medium**,
**High**. More effort means the model reasons longer before answering, at the cost of
tokens and latency. Note that on Claude 4.6 and newer, turning thinking on means the
model ignores the temperature setting — that's an API restriction, not a conversa one.

The model's thinking — and any web searches it decides to run — stream above the reply
as a live trace you can collapse. The trace is ephemeral: it isn't saved with the
conversation and a reload clears it.

### Workspaces: shared context for a group of conversations

A **workspace** bundles a shared system prompt, shared cards, and plain-text
documents (`.txt`/`.md`), and any number of conversations can point at it. Every
reply in a member conversation carries the workspace's prompt, its documents in
full, and whichever of its cards trigger, on top of the conversation's own system
messages and cards. Where the same topic has a card in both, the workspace card is
sent first and the conversation card after it, so a conversation can refine the
shared note.

Workspaces live at the top of the sidebar's conversation list: each workspace row
heads its member conversations, the + next to the **Workspaces** label creates
one, clicking a row opens its editor (name, prompt, documents, cards), and
everything unassigned sits below under **Conversations**. A conversation joins or
leaves through **Conversation settings**; membership is a single link, so joining,
leaving, or deleting the workspace leaves the conversation's own cards and
messages exactly as they were. In a member conversation the card panel lists the
workspace's cards read-only, with the same live "active" dots as its own; editing
them happens in the workspace so a change to shared context is always a deliberate
act.

Documents are sent whole with every request and count as input tokens, so keep
them to what the conversations actually need.

### Templates

Set up a conversation the way you like — system messages, cards, settings, a few
seed messages — and save it as a **template**. Starting from a template clones all
of that into a fresh conversation. Templates live in the sidebar.

Templates keep their workspace link: save a workspace conversation as a template
and every conversation started from it joins that workspace automatically.

---

Built with Vue + FastAPI. For the stack, architecture, and local development,
see **[DEVELOPMENT.md](DEVELOPMENT.md)**.
