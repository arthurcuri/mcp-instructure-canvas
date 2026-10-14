# Codex contributors

Codex automatically reads the root `AGENTS.md`. This folder provides an optional
MCP configuration example for contributors; it does not replace those instructions.

Follow the root README to install dependencies and register the server with
`codex mcp add canvas-pucminas -- "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"`.

Alternatively, copy `config.toml.example` to `config.toml`, replace the absolute
paths, and open this repository as a trusted project. Codex only loads project
configuration for trusted projects. The actual `config.toml` is ignored by Git.
If you already have that file, merge the MCP table instead of replacing it.

Keep tokens in `.env`. Read [AGENTS.md](../AGENTS.md) before editing the server.

The shared `canvas-activity` skill is exposed through `.agents/skills/` for native
Codex discovery. The optional Telegram bridge uses Codex App Server with ChatGPT
login and is controlled by `canvas-agent start|status|stop --provider codex`.
Follow [the complete setup](../README.md#6-conversar-pelo-telegram-com-codex-ou-claude-code).
Test with synthetic updates and mocked protocol messages; do not solve real
coursework or submit to Canvas just to validate the bridge.
