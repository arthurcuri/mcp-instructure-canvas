# Optional Telegram agents

The local agent lets the owner of a private Telegram chat ask Codex or Claude Code for help with Canvas assignments. It is separate from the MCP server and deadline reminders. It uses the account authenticated in the selected CLI, creates its own conversation, and does not import existing web chats.

Use a source checkout with dependencies installed, a configured Canvas `.env`, and a dedicated Telegram bot. Follow [Telegram setup](../automation/README.md#telegram) first. Keep one update consumer per bot: stop other receivers before switching providers or running chat discovery.

## Choose the provider and account

```sh
uv run canvas-agent setup
```

Setup is interactive. It asks you to choose Codex or Claude, review an existing subscription account or explicitly open native login, choose manual/automatic mode, and review saving or starting services. It only saves provider/mode choices to `.env`, preserving tokens and private notes. No provider is selected implicitly.

You can save without starting. Existing services then keep their old configuration until explicitly restarted. `--provider codex` or `--provider claude` overrides the saved provider for one command without saving a preference.

```sh
uv run canvas-agent status
uv run canvas-agent start
uv run canvas-agent stop
```

On macOS, Codex `start` installs a local LaunchAgent. The computer must be awake, signed in, and online; no open Terminal is required. On other systems, use `canvas-agent run --provider codex` in the foreground or manage it with your own supervisor. The runtime does not install a Linux service automatically.

## Codex with ChatGPT

Install Codex CLI and authenticate using your ChatGPT account through setup or `codex login`. The agent rejects API-key authentication. Setup reads native account metadata without starting a model task.

```sh
uv run canvas-agent setup --provider codex
# Foreground alternative after account/configuration setup:
uv run canvas-agent run --provider codex
```

The receiver uses Codex App Server over stdio, with normal provider permissions and owner-only polling. It accepts text and quoted messages, returns final text, and can attach requested coursework files. Incoming file, audio, and image messages are not supported by this receiver.

| Bot command or message | Behavior |
|---|---|
| `/start`, `/help` | Show help without model calls |
| `/status` | Show state and pending approvals without model calls |
| `/cancel` | Request interruption of the active turn |
| `/reset` | Start another conversation on the next request; retain coursework files |
| `/approve CODE`, `/deny CODE` | Answer the corresponding current permission request |
| `Yes` / `No` | Answer a single pending simple confirmation; Portuguese replies remain accepted |
| `/answer CODE response` | Answer a question; real forms still require the requested fields |
| Text during an active task | Add context/corrections to the same turn |
| A new text request | Start model work using the provider's quota |

Approvals expire after 15 minutes. If several requests are pending, reply to the specific Telegram request or use its code. Arbitrary text is never treated as permission. Receiver tasks have a 30-minute limit; interrupted requests are not replayed after restart.

The bot keeps the native conversation and a private assignment reference. Current owner corrections take priority over older references and the default course. A cloud reminder is not an inbound agent message: use **Reply** on it or send the assignment link. For an unquoted “this assignment,” the receiver reads current deadlines across courses; if several match, the agent must ask which one. Reference data never grants write authorization.

Requested attachments must be inside `.local/activities/`. The English marker `[[file: relative/path]]` and legacy `[[arquivo: relative/path]]` are supported. Configuration files, credentials, paths outside that directory, and oversized files are rejected.

## Claude Code with Claude

Install Claude Code and Bun. Open `claude` in the project and accept its workspace trust prompt. Authenticate through setup or the official CLI flow. The agent uses subscription authentication and normal permissions.

Install the official Channels plugin:

```sh
claude plugin install telegram@claude-plugins-official --scope local
uv run canvas-agent setup --provider claude
uv run canvas-agent status
```

Claude replies and approvals use the official plugin. Team/Enterprise administrators must allow Channels; organization policy cannot be bypassed. See [Claude Channels](https://code.claude.com/docs/en/channels). This integration has mocked coverage, but live verification in the maintainer's Team account was blocked by organization policy.

For foreground use, run `uv run canvas-agent run --provider claude`. Idle background sessions may stop; inspect `claude agents` and pin the session when needed. Preparation writes private state under `.local/agent/`, including the Telegram credential copy required by the plugin. After changing credentials or mode, explicitly stop/start to refresh the runtime copy.

## Manual and automatic mode

Manual mode is the default:

```dotenv
CANVAS_AGENT_AUTO=false
```

The agent waits for an owner request. Preparing an explanation or file does not authorize a Canvas submission; request submission explicitly and identify the assignment and content.

Setting `CANVAS_AGENT_AUTO=true` is advance authorization for a **separate local worker** to prepare and submit eligible pending assignments. It requires `CANVAS_READ_ONLY=false`. Choose it in setup and review activation, or deliberately edit `.env` and restart the selected provider. Installation does not enable it.

On macOS, automatic mode installs an 08:00 daily job in the **system timezone**. `CANVAS_TIMEZONE` affects report dates, not the local scheduler's clock. On Linux, schedule the worker yourself. The worker can run without a bot receiver and does not consume inbound updates.

```sh
uv run canvas-agent auto-run --provider codex
# Alternative provider:
uv run canvas-agent auto-run --provider claude
```

With automatic mode disabled, these commands exit without reading assignments or calling models. To disable an installed worker, restore `false` and explicitly stop/start the service.

The worker scans all active courses and processes supported, available text/file/URL assignments sequentially, including undated or overdue work when submission remains open. Quizzes, external tools, paper assignments, and locked tasks are excluded. Missing personal data, empirical results, or additional permissions require attention; fabricated evidence and placeholder submissions are not acceptable.

Each attempt is claimed in `.local/agent-auto/ledger.json` **before inference**. A separate Canvas API read verifies submission afterward; model text is not proof. Attempted, failed, and uncertain tasks are not retried automatically. Inspect Canvas before requesting continuation. Provider permissions and quota limits still apply. Cloud reminder jobs only read Canvas and do not call these agents.

## Troubleshooting

| Symptom | Action |
|---|---|
| No provider selected | Run `canvas-agent setup` or pass an explicit provider |
| Bot does not answer `/start` | Check service status, private chat, network, and a single poller |
| Telegram HTTP 409 | Another poller or webhook is using the bot |
| Approval still waiting | Use the current request/code; simple confirmations accept Yes/No, forms need fields |
| Wrong assignment selected | Reply to the current reminder or send the current assignment URL |
| Missing real conversation history | Use `/reset` to start another thread; files remain; inspect Canvas before repeating submissions |
| Claude `blocked_by_organization` | Administrator must enable Channels before receiving messages |
| Changed mode not reflected | Stop/start to refresh the private runtime configuration |
| Automatic worker inactive | Check opt-in, write mode, provider login, installed job, and system timezone |
| `needs_attention` in ledger | Read the reason and inspect Canvas; supply missing information or request continuation |
| Provider quota/login expired | Stop, renew native login, and start again |

State/logs under `.local/codex-agent/`, `.local/agent/`, and `.local/agent-auto/` are private and ignored. Old updates are discarded on first installation; send a fresh request. Telegram retains updates for a limited time, so prolonged downtime can lose messages. Outbound messages and Canvas writes are never retried automatically after uncertain delivery.
