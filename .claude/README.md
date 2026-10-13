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
