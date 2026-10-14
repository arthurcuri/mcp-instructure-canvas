# Claude Code contributors

`CLAUDE.md` at the repository root imports the shared `AGENTS.md`.
Claude Code also loads the project rules in `.claude/rules/`.

After completing the root README's installation steps, register the MCP with
`claude mcp add --scope local --transport stdio canvas-pucminas -- "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"`.
The record is private to this project in `~/.claude.json`.

For an optional project record, adapt `examples/mcp.json` into `.mcp.json` at the
root. That local file is ignored because it contains machine-specific paths.
Do not duplicate the local and project registrations under different names.

Follow [the root README](../README.md) for setup and [the shared instructions](../AGENTS.md)
for development. No permission bypass or credential is committed here.

The `canvas-activity` skill in this folder is also exposed to Codex through
`.agents/skills/`. For Telegram, the optional provider uses the official
`telegram@claude-plugins-official` Channels plugin. Use `canvas-agent setup` to choose
Claude, explicitly reuse the shown account or open native login, then review activation.
An explicit `--provider claude` is also available for individual lifecycle commands.
See [the complete setup](../README.md#6-conversar-pelo-telegram-com-codex-ou-claude-code).
Team/Enterprise Channels policy must allow it; keep normal permissions and never
run two update receivers against the same bot.
