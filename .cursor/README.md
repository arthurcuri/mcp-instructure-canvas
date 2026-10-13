# Cursor contributors

Cursor loads `.cursor/rules/*.mdc`; the always-applied rule points to the root
`AGENTS.md`, which Cursor also supports as project guidance.

Install dependencies using the root README. Copy `mcp.json.example` to `mcp.json`,
replace the absolute paths, then inspect the server under Cursor's MCP settings.
If a config already exists, merge only this server's entry. The real `mcp.json`
is ignored; leave the Canvas token in `.env`.

See [README.md](../README.md) and [AGENTS.md](../AGENTS.md) for setup and development.
