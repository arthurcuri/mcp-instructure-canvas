# Gemini CLI contributors

The root `GEMINI.md` imports `AGENTS.md` with Gemini's memory import syntax.
Run `/memory show` in Gemini CLI to inspect the loaded project guidance.

After installing dependencies, copy `settings.json.example` to `settings.json`
and replace the two absolute paths. If settings already exist, merge only the
`mcpServers.canvas-pucminas` entry, preserving the other settings. Restart Gemini
CLI and use `/mcp` to inspect the server.

The real `.gemini/settings.json` is ignored. Never copy the Canvas token into it;
the server reads the ignored `.env` through its `--env-file` argument.

See [README.md](../README.md) and [AGENTS.md](../AGENTS.md) for setup and development.
