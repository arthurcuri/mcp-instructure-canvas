# Installation and client setup

Start with the [README quick start](../README.md#quick-start). This guide covers the configuration and client details. Shell examples target macOS/Linux; Windows service management is not currently provided.

## Personal Canvas token

1. Sign in to your institution's Canvas website.
2. Open **Account → Settings → Approved Integrations**.
3. Choose **New Access Token**, if available, and enter a purpose and institution-required expiration.
4. Copy the generated token directly into your private `.env`. Canvas does not show the value again.
5. Keep expiration notes in `.env` or `.local/`, both ignored by Git.

If token creation is unavailable, ask your Canvas administrator about API access. Your portal password is not an API token. Tokens retain the permissions of the issuing account. See the [official authentication guide](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth).

This project uses a personal access token per installation. It does not implement multiuser OAuth or LTI registration. Some catalog operations need additional credentials, roles, or institution features.

## Private configuration

Copy `.env.example` only if `.env` does not already exist, then edit it locally. Never put credentials in client configuration files, shell commands, issues, or screenshots.

| Variable | Purpose |
|---|---|
| `CANVAS_API_URL` | Required HTTPS institution origin, with or without `/api/v1`, such as `https://canvas.example.edu/api/v1` |
| `CANVAS_API_TOKEN` | Required personal Canvas token |
| `CANVAS_DEFAULT_COURSE_ID` | Optional positive course ID, taken from `/courses/12345` in a course URL |
| `CANVAS_TIMEZONE` | IANA timezone for displayed dates, such as `UTC` or `America/Sao_Paulo`; runtime fallback is `America/Sao_Paulo` |
| `CANVAS_TOKEN_EXPIRES_AT` | Optional private reminder in `YYYY-MM-DD`; does not change or verify expiration in Canvas |
| `CANVAS_READ_ONLY` | `true` hides four mutation tools and rejects writes in the HTTP client; the example enables it, while the runtime fallback remains `false` for compatibility |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Only needed for Telegram reminders or an agent |
| `CANVAS_AGENT_PROVIDER` | Optional `codex` or `claude`, explicitly chosen during agent setup |
| `CANVAS_AGENT_AUTO` | `false` by default; `true` authorizes the separate local worker to prepare and submit eligible assignments |

Process environment variables override `.env`. Use an absolute `--env-file` path when registering an MCP client, because clients may launch outside the repository directory.

```sh
uv run canvas-mcp-server --test
uv run canvas-mcp-server --config
uv run canvas-mcp-server --version
```

`--test` reads your profile and, when configured, the default course and assignments. `--config` prints sanitized configuration without the token. Neither command starts a persistent server.

## MCP client configuration

The server uses local **stdio**, not a remote URL. Run it as a child process of your MCP client. Use an absolute executable and `.env` path. The label `canvas` below is arbitrary; the repository's personal agent uses `canvas-pucminas` internally for compatibility.

### Claude Code

From the checkout root:

```sh
claude mcp add --scope local --transport stdio canvas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
claude mcp get canvas
```

This creates a private project-associated registration in `~/.claude.json`. Start a new session and inspect `/mcp`. The optional [JSON template](../examples/mcp.json) can instead be adapted into an ignored `.mcp.json`; avoid duplicate registrations. See [.claude/README.md](../.claude/README.md) for contribution guidance.

### Codex

From the checkout root:

```sh
codex mcp add canvas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
codex mcp get canvas
```

Registration is stored in `~/.codex/config.toml`. Start a new session and inspect `/mcp`. For project configuration, adapt [.codex/config.toml.example](../.codex/config.toml.example) into the ignored `.codex/config.toml` and trust the project. Merge the section into existing configuration rather than replacing it. See [.codex/README.md](../.codex/README.md).

### Claude Desktop and JSON clients

Merge this into your client's MCP configuration, replacing both fictitious paths:

```json
{
  "mcpServers": {
    "canvas": {
      "command": "/absolute/path/mcp-instructure-canvas/.venv/bin/canvas-mcp-server",
      "args": ["--env-file", "/absolute/path/mcp-instructure-canvas/.env"]
    }
  }
}
```

Restart the client after changes. Do not place `CANVAS_API_TOKEN` in this JSON. The client launches the server; no separate daemon or public port is needed.

### Gemini CLI

Adapt [.gemini/settings.json.example](../.gemini/settings.json.example) into `.gemini/settings.json`, preserving existing settings and replacing the executable and `.env` paths. Restart Gemini CLI in the project and inspect `/mcp`. `GEMINI.md` imports the shared development instructions. See [.gemini/README.md](../.gemini/README.md).

### Cursor

Adapt [.cursor/mcp.json.example](../.cursor/mcp.json.example) into `.cursor/mcp.json`, replacing the absolute paths and preserving existing servers. Reload Cursor and check the MCP tools. See [.cursor/README.md](../.cursor/README.md).

### Kiro

Adapt [.kiro/settings/mcp.json.example](../.kiro/settings/mcp.json.example) into `.kiro/settings/mcp.json`. Replace the paths, preserve existing configuration, and inspect the MCP connection after reloading. See [.kiro/README.md](../.kiro/README.md).

All real local client copies are ignored by Git. Client instruction files help development; MCP registration establishes the Canvas connection.

## Troubleshooting

| Symptom | What to check |
|---|---|
| HTTP 401 | Token expired, revoked, or copied incorrectly; update only your private credential |
| HTTP 403 | Account permissions, administrator policy, and feature availability |
| HTTP 404 | Course/assignment ID and account access |
| Server does not start | Run `uv sync --locked`; verify the executable and absolute `.env` path |
| `.env` not found | Explicit `--env-file`; the client may start in a different working directory |
| No assignments returned | Timezone, date period, course scope, completed submissions, and `undated_count` |
| Write tool unavailable | `CANVAS_READ_ONLY=true`; change it only when you intend to enable writes, then reconnect |
| Server appears to wait in Terminal | Normal stdio behavior: the MCP client must send protocol messages |

See [agent troubleshooting](agents.md#troubleshooting) and [reminder scheduling](../automation/README.md) for those optional components.
