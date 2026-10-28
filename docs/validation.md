# Validation record

This page records **historical verification**, not a claim that every release or institution has passed live checks. It contains no tokens, chat IDs, course bodies, student names, or personal submissions. The documentation refresh does not run live Canvas writes, send Telegram messages, or activate jobs.

## October 14, 2026

| Flow | Scope | Recorded result |
|---|---|---|
| Local stdio MCP → authenticated Canvas | Initialization, tools, courses, assignments, deadlines, modules, and pages | Passed; detail tools returned complete content |
| Manual GitHub Actions → Canvas → Telegram | Manual run of the daily reminder workflow | Passed; Telegram confirmed delivery and the owner received it |
| Telegram → Codex → MCP → Canvas → Telegram | Owner's real request to read deadlines across all courses for the next seven days | Passed; completed MCP call and final reply confirmed by the owner |
| Agent setup | Provider/account choices, cancellation, save without starting, switching, and modes | Mocked tests passed; login opens only after an explicit choice |
| Canvas writes and automatic worker | Mocked HTTP/model execution, submission verification, and ledger | Passed; no real coursework submitted for testing |
| Claude Telegram | Official Channels integration with mocked coverage | Live validation blocked by Team organization policy |
| MCP image/distributions | Version, stdio protocol, offline catalog, and exclusion of private files | Passed on native amd64/arm64 release runners |
| Docker MCP → real Canvas | Same reads as local installation | Passed; deadlines matched agent/reminder results |
| GHCR publication | Anonymous manifest access | Passed; public download without authentication |
| Published 0.5.2 packages | Downloaded wheel/image, checksums, and real Canvas reads | Passed; handshake reported 0.5.2 and deadlines matched |

Evidence: [manual reminder run](https://github.com/arthurcuri/mcp-instructure-canvas/actions/runs/38508719491) and [0.5.2 release workflow](https://github.com/arthurcuri/mcp-instructure-canvas/actions/runs/38560983173).

The Codex test used ChatGPT authentication. Private history inspection verified tool names, statuses, counts, and a completed final reply; course content was not published. Manual reminder delivery proves the read/send path, not scheduled dispatch timing.

## October 23, 2026: approvals and assignment context

Version 0.5.3 added mocked coverage for Yes/No replies, forms with fields, expiration, multiple pending requests, another user, active-turn corrections, and persistent assignment references. The bridge uses elicitation and `turn/steer` contracts from Codex App Server.

Read-only live MCP verification passed with 18 tools and complete details; the next-seven-days query covered all active courses. Wheel/source audits checked versions, catalog inclusion, and private-file exclusion. The personal runtime was restarted with conversation/files preserved, Telegram connected, and automatic mode disabled. A human test of a new Telegram approval is separate from mocked coverage; no Canvas submission was used to validate the correction.

## October 28, 2026: English onboarding and regression checks

The unreleased checkout passed all 202 mocked tests, Ruff lint/format checks, shell
syntax validation, distribution build, and archive audit. Local documentation links
and the overview SVG were also checked.

Live read-only stdio verification against the configured Canvas account passed:
18 tools were registered, including 12 with read-only MCP annotations; course,
assignment, deadline, module, and page queries completed. Detail responses retained
their completeness flags. Only counts/status were inspected, without publishing
course bodies or credentials.

Canvas writes, Telegram delivery, and agent execution were covered by mocked tests
in this verification. Services and schedules were not activated or restarted.

## Reproduce on your own installation

Offline contribution checks are in [CONTRIBUTING.md](../CONTRIBUTING.md). The following commands deliberately access your own configured account:

```sh
uv run canvas-mcp-server --test
uv run python scripts/verify_mcp.py
uv run canvas-agent status
```

`verify_mcp.py` uses the first active course, or an explicit `--course-id 12345`. No configured default course is required. With no active courses, it still checks the protocol and all-course deadline query, and reports skipped course-detail checks. It prints counts/status rather than course bodies.

To inspect Canvas through Docker, use `--container ghcr.io/arthurcuri/mcp-instructure-canvas:v0.6.0` with Docker running. Live MCP checks are read-only. To test Telegram inbound behavior, the owner must send their own query; the Bot API cannot send an inbound message on their behalf. Keep one update consumer per bot.

A manual reminder workflow run sends a real message when bot secrets are configured. That is optional integration work, not a contributor requirement.

## Schedule timing

On **October 14, 2026**, the workflow requesting 08:00 São Paulo was created at **12:43:55**, and Telegram confirmed delivery at **12:44:17**. The event was `schedule`, not `workflow_dispatch`. Once created, the job started in two seconds and completed successfully. Counts and one delivery confirmation were logged; no Canvas/Telegram authentication error was recorded.

Evidence: [delayed scheduled run](https://github.com/arthurcuri/mcp-instructure-canvas/actions/runs/38591893378). The available history does not identify the specific platform cause. GitHub documents possible schedule delays/dropped runs, especially near the start of an hour. See [schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

To inspect dispatch timestamps:

```sh
gh run list --workflow daily-canvas.yml --limit 10 \
  --json databaseId,event,createdAt,startedAt,conclusion,url
```

API timestamps are UTC; convert them to the workflow timezone. A successful manual run does not establish that a schedule ran on time.

## Limits of this evidence

- It does not demonstrate permission for every teacher/admin endpoint.
- It does not establish real automatic submissions; those paths use mocked testing.
- It does not establish that Claude Channels is allowed by an institution's policy.
- It does not guarantee punctual cloud delivery or local execution while a computer is asleep/offline.
- Historical published-package checks do not verify uncommitted source changes or future releases.
