# Kiro contributors

Kiro loads `.kiro/steering/` guidance and supports the root `AGENTS.md`.
The always-included steering file points to that shared source.

Install dependencies following the root README, copy `settings/mcp.json.example`
to `settings/mcp.json`, and replace the absolute paths. If a config already exists,
merge only the server entry. Use Kiro's workspace MCP configuration panel to
inspect or reconnect the server. The example does not automatically approve tools.

The real config is ignored by Git. Keep the token in `.env`, not in Kiro settings.
See [README.md](../README.md) and [AGENTS.md](../AGENTS.md) for setup and development.
