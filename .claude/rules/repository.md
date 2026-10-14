# Canvas MCP development

Read the root `AGENTS.md` for architecture, commands and shared repository rules.
This folder supports developers using Claude Code; Canvas credentials belong in
the ignored `.env`, never in rules, settings or prompts.

Preserve separate read/write tools, `CANVAS_READ_ONLY` enforcement and compact
summaries. Use mocked HTTP in tests. Keep reports and logs under the ignored
`.local/` directory. Scheduling
and external delivery must remain opt-in; do not load a job while editing its template.
