---
inclusion: always
---

# Canvas MCP development

Kiro automatically discovers the root `AGENTS.md`. Use it as the shared source
for architecture, validation commands and repository rules.

Keep Canvas access read-only. Use mocked HTTP for tests, leave credentials in the
ignored `.env`, and store reports/logs in `.local/`. Preserve compact list results
and complete detail reads. Editing a scheduling template must not activate it.
