<p align="center">
  <img src="frontend/public/logo.png" alt="conversa" width="96" height="96" />
</p>

# conversa

A chat client for Claude and GPT where **your data lives in your browser**, not on someone's server.

Conversations, settings, cards, workspaces, templates and research runs are all stored locally and stay there. A small server holds the provider API keys behind a password you set, relays chat, and does the two things a browser cannot: fetch pages that CORS puts out of reach, and run research jobs that keep going after you close the tab.

Who ends up holding what:

| What | In your browser | On the server |
|------|-----------------|---------------|
| Every chat transcript | ✔️ | ❌ |
| Cards, workspaces, templates | ✔️ | ❌ |
| A finished research report | ✔️ | 🟡 (Until you keep it. Then deleted) |
| Your provider API key | ❌ | ✔️ (This is the whole reason it exists) |
| The pages a research run reads | ❌ | 🟡 (A minute or two, then forgotten) |
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

Either provider key on its own is enough.
Set both to pick between Claude and GPT models per conversation.
Models belonging to a provider you have no key for are left out of the model picker, and the app says so in a banner on first load.

### Run it as a systemd service (Podman Quadlet)

To have systemd start and supervise the container, first store your secrets with `podman secret` so they stay out of the unit file:

```sh
printf 'sk-ant-...' | podman secret create conversa_api_key -
printf 'sk-...' | podman secret create conversa_openai_key -   # optional
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

Your conversations, settings, cards, workspaces, and templates live in the browser, so an update leaves all of them intact.

## Configuration

Set these as environment variables when you start the container.

| Variable | Required | Default | What it does |
|----------|----------|---------|--------------|
| `ANTHROPIC_API_KEY` | one of the two | _(none)_ | Your Anthropic key. Stays on the server. |
| `OPENAI_API_KEY` | one of the two | _(none)_ | Your OpenAI key. Stays on the server. |
| `APP_PASSWORD` | **yes** | _(none)_ | The password used to log in. |
| `JWT_SECRET` | no | random | Signs login tokens. Leave unset and every restart logs everyone out; set it to keep sessions alive across restarts. |
| `TOKEN_TTL_SECONDS` | no | `604800` | How long a login lasts (default 7 days). |
| `DEFAULT_MODEL` | no | `claude-sonnet-5` | Model new conversations start with. |
| `DEFAULT_TEMPERATURE` | no | `1.0` | Creativity, 0 to 1. Ignored by the Claude and GPT reasoning models, which reject it. |
| `DEFAULT_NUM_MESSAGES` | no | `20` | How many recent messages are sent each turn. |
| `DEFAULT_SEND_SYSTEM_PROMPT` | no | `true` | Whether system messages are sent. |
| `DEFAULT_MAX_TOKENS` | no | `4096` | Cap on reply length. |
| `DEFAULT_EFFORT` | no | *(off)* | Thinking effort new conversations start with: empty, `low`, `medium`, or `high`. |
| `DEFAULT_UTILITY_MODEL` | no | `claude-haiku-4-5` | Cheap model used for auto-titling and memory. |
| `DEFAULT_USE_MEMORY` | no | `false` | Whether older turns get summarized into memory. |
| `DEFAULT_SUMMARIZE_N` | no | `20` | How many turns just above the send window get summarized into memory. |
| `DEFAULT_USE_RECALL` | no | `false` | Whether relevant dropped turns get resent verbatim. |
| `DEFAULT_USE_CACHE` | no | `false` | Whether the stable part of the prompt is cached by the provider. Off by default because it only pays back in long conversations with a large shared context. |
| `MODELS` | no | _(none)_ | **Extra** models to offer, as `provider/id:Label,id:Label`, appended to the built-in list. The label is optional. The provider is optional and defaults to `anthropic`, so `claude-opus-5` and `anthropic/claude-opus-5` mean the same model; OpenAI ids need the `openai/` prefix. Models older than Claude 4.6 use an earlier thinking format, so add their id to `LEGACY_MODELS` in `backend/llm.py`. |
| `WEB_SEARCH_TOOL_VERSION` | no | `web_search_20250305` | Anthropic web-search tool version; the model searches on its own when a message needs it. Empty disables it. |
| `WEB_FETCH_TOOL_VERSION` | no | `web_fetch_20250910` | Anthropic web-fetch tool version; lets the model open a URL you paste in chat. Empty disables it. |
| `WEB_FETCH_BETA` | no | `web-fetch-2025-09-10` | Beta header the web-fetch tool requires. |
| `DEFAULT_RESEARCH_SEARCH_MODEL` | no | `DEFAULT_MODEL` | Model that runs the searches in a research run. |
| `DEFAULT_RESEARCH_NOTE_MODEL` | no | `DEFAULT_UTILITY_MODEL` | Model that reads pages and takes notes. Around 78% of a run's input tokens, so a cheap model belongs here. |
| `DEFAULT_RESEARCH_REPORT_MODEL` | no | `DEFAULT_MODEL` | Model that plans the subquestions and writes the report. |
| `DEFAULT_RESEARCH_DEPTH` | no | `5` | Sources read per subquestion. |
| `API_MAX_RETRIES` | no | `5` | Provider retries on 429, 5xx and connection errors. A run makes ~30 calls, so the SDK default of 2 is too few. |
| `OPENAI_WEB_SEARCH_TOOL` | no | `web_search` | OpenAI's hosted search tool. One tool covers both searching and opening pages, so it does the job of the two Anthropic ones. Empty disables it. |

Every default above is a starting point.
Change any of them globally (in **Global settings**) or per conversation (in **Conversation settings**).

## How it works

Most of conversa is an ordinary chat window.
A few features are worth knowing about.

### Context: what the assistant always sees

Think of the **context editor** as a corkboard the assistant glances at on every reply.
Two kinds of note live there:

- **System messages**: standing instructions ("You are a terse Rust expert").
- **Pinned messages**: any normal message you've pinned.
  Pinned messages skip the recent-messages limit and go every turn, so an important detail from 200 messages ago stays in context.
  Pin a message with the 📌 button, or manage everything together in the context editor.

Paste a URL into the context editor's fetch box and the page comes back as clean markdown, pinned to the board as a system message you can edit or delete.
The server fetches it, because your browser is blocked from most pages by CORS.

### Research: a run that reads the web and writes you a report

Press **Research** beside **New chat** in the sidebar.
A run is its own thing, listed alongside your conversations rather than living inside one.

Give it a brief.
Before starting, you can have it ask you a few scoping questions: how deep to go, which time period, who is reading.
Your answers go to the planner with the brief, which is what decides how wide a net the run casts.

The run then breaks the brief into subquestions, searches for each, reads what it finds, and writes a cited report.
It keeps going if you close the tab, and reopening picks the stream back up where you left it.
A counter shows tokens and estimated cost as it goes, and stop ends it immediately.

The result lands in a workspace: the report as a reference document, and each subquestion's underlying notes as a card you pull in by typing `q1`, `q2` and so on.
Open the workspace to read the report, or download it as a markdown file.
That way the report is always in context and the raw notes are one keystroke away without costing anything on the turns you do not ask for them.

Three models are set separately, because the stages differ: one searches, one reads pages and takes notes (this is most of the spend, so a cheap model belongs here), and one plans and writes the report.

### Cards: notes that appear only when relevant

A **card** is like an index card in a box.
Each card has some **trigger phrases** and a **note**.
Before every reply, conversa scans your recent messages; if a card's trigger phrase shows up, that card's note is quietly handed to the assistant for that reply, then dropped again once the word stops coming up.

It's a lightweight way to give the assistant background knowledge ("when I say *Aria*, that's my D&D character, a half-elf rogue...") that costs you tokens only on the turns that mention it.

Triggers are comma-separated, and commas mean *or*: any one phrase fires the card.
Use `&` when a card should only fire if several words all appear: `dragon & red, wyrm` triggers on "wyrm", or on "dragon" and "red" both showing up in recent messages.

You can override the trigger matching per card with two buttons on the card's row: **force include** (✓) always sends the card regardless of triggers, and **force skip** (⃠) never sends it.
Click again to clear the override and return to normal trigger matching.
Forced-include and triggered cards show green; force-skip shows yellow.
To keep cards tidy, give a card a **folder** name and it'll group under that heading.
A folder is a display heading; triggering runs off the phrases alone.

### Memory: so long chats don't get forgotten or expensive

Turn on **Compress history into memory** and conversa keeps a summary of the messages just above the recent-messages window (written by the cheap utility model) instead of re-sending them verbatim.
The summary refreshes in the background after each reply, so sending never waits on it.
Recent messages stay word-for-word; anything older than both windows drops out (recall below brings it back when relevant).
You can read, edit, or clear the summary in **Conversation settings**.

### Recall: old messages that suddenly matter again

Turn on **Recall relevant old messages** and, before each reply, conversa looks at the turns that fell outside the recent-messages limit and re-sends the few that overlap most with what you just asked, verbatim, as reference.
Ask "what was the dragon called again?" 200 messages later and the turn that names it comes back.

Recall returns the original turns word for word, where memory summarizes.
The two work well together.

### Models

The model picker in the composer toolbar (also in **Conversation settings** and **Global settings**) groups models under their provider.
Every feature works the same on either: cards, memory, recall, workspaces, templates, thinking effort, web search, research runs, and the utility model that writes titles and memory summaries.
You can point the utility model at one provider while chatting with the other.

### Thinking effort

The brain picker turns on extended thinking: **Off**, **Low**, **Medium**, **High**.
More effort means the model reasons longer before answering, at the cost of tokens and latency.
The same four levels drive Anthropic's `effort` and OpenAI's `reasoning_effort`.

Two API behaviours to expect.
On Claude 4.6 and newer, turning thinking on makes the model ignore the temperature setting.
And effort is a hint: at **Low**, GPT models often answer an easy question with no reasoning at all, which shows up as an empty trace.

The model's thinking, and any web searches it runs, stream above the reply as a live trace you can collapse.
The trace is ephemeral: it lives in memory for the current turn, and a reload clears it.

### Workspaces: shared context for a group of conversations

A **workspace** bundles a shared system prompt, shared cards, and plain-text documents (`.txt`/`.md`), and any number of conversations can point at it.
Documents can be uploaded, and research runs write their reports here too.
Every reply in a member conversation carries the workspace's prompt, its documents in full, and whichever of its cards trigger, on top of the conversation's own system messages and cards.
Where the same topic has a card in both, the workspace card is sent first and the conversation card after it, so a conversation can refine the shared note.

Workspaces head the sidebar's conversation list, below the new-chat and research buttons and any research runs: each workspace row heads its member conversations, the + next to the **Workspaces** label creates one, clicking a row opens its editor (name, prompt, documents, cards), and everything unassigned sits below under **Conversations**.
A conversation joins or leaves through **Conversation settings**; membership is a single link, so joining, leaving, or deleting the workspace leaves the conversation's own cards and messages exactly as they were.
In a member conversation the card panel lists the workspace's cards read-only, with the same live "active" dots as its own; editing them happens in the workspace so a change to shared context is always a deliberate act.
The include and exclude buttons on a workspace card are the exception: they are stored on the conversation, so one conversation can force a shared card to send every turn, or silence it, while the rest of the workspace keeps it as is.

Documents are sent whole with every request and count as input tokens, so keep them to what the conversations actually need.
Click a document in the workspace editor to read it rendered, or use the download button to save it as a file.
That is how a research report gets out of the browser.

### Prompt caching: pay for a big workspace once

Turn on **Cache the workspace prompt & docs** and the provider caches the stable part of your prompt: the workspace prompt, your system messages, and the workspace documents. A big shared context then gets billed once per cache window instead of on every turn.

It is off by default because it is a bet. A cache write costs 25% more than an ordinary one and expires after a few minutes, so it wants a lot of stable text and a steady back-and-forth.

Caching is prefix-match: change one byte and everything after it is re-billed. That makes conversa's own assembly order the thing that decides what you actually save.

> [!TIP]
> Cards cost you nothing here. They are assembled last, after the cache breakpoint, so a card firing on turn seven rewrites only the uncached tail while the workspace prompt and documents above it stay cached.

> [!NOTE]
> Memory and recall sit outside the cache on purpose.
> The summary is rewritten after every reply and recall re-picks which old turns to resend each turn, so caching either would invalidate the block constantly. You re-pay for both every turn.

> [!WARNING]
> The messages array is never cached at all. The send window drops old turns off the front as it slides, so the message prefix changes on most turns. Only the system prompt benefits from this setting, which is why it needs workspace documents to be worth turning on.

### Templates

Set up a conversation the way you like (system messages, cards, settings, a few seed messages) and save it as a **template**. Starting from a template clones all of that into a fresh conversation.
Templates live in the sidebar.

Templates keep their workspace link: save a workspace conversation as a template and every conversation started from it joins that workspace automatically.

---

Built with Vue + FastAPI.
For the stack, architecture, and local development, see **[DEVELOPMENT.md](DEVELOPMENT.md)**.
