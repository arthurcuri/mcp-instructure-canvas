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
login. Use `canvas-agent setup` to choose the provider/account and review activation;
then `canvas-agent start|status|stop` uses the saved choice. An explicit `--provider codex`
overrides it for one command only. Setup never opens login or activates without your choice.
Follow [the complete setup](../docs/agents.md).
Test with synthetic updates and mocked protocol messages; do not solve real
coursework or submit to Canvas just to validate the bridge.
