# Changelog

This project follows semantic versioning. Before 1.0, minor releases may change interfaces; migration guidance appears in release notes.

## 0.6.0 — 2026-10-28

- Make English the default language for documentation, CLI help, diagnostics, MCP instructions, and reminder/agent messages. Agents answer in the owner's language; original Canvas content is preserved.
- Retain a Portuguese README and legacy Portuguese approval replies/attachment markers. Add English assignment references and `[[file: ...]]` attachments to the Telegram bridge.
- Split setup, API, reminder, agent, and package guides; add contributor instructions, issue forms, a PR template, a code of conduct, and a roadmap.
- Start the example configuration in read-only mode with a fictitious institution and explicit UTC timezone. Existing runtime defaults and private configurations remain compatible.
- Require an explicit institution URL in cloud reminder variables instead of defaulting a fork's credentials to the maintainer's institution.
- Fix live MCP verification for installations without a default course, support an explicit course, and report skipped course checks for accounts with no active courses.
- Update the security policy to describe implemented agents, explicit automatic authorization, and private vulnerability reporting.

## 0.5.3 — 2026-10-23

- Accept Yes/No Telegram replies and approval commands for fieldless MCP confirmations without requiring JSON; real forms still validate their schema locally.
- Bind replies to current requests, rejecting expired codes, another user, ambiguous requests, and already-resolved permissions.
- Steer messages received during an active task into that turn using `turn/steer`.
- Persist private assignment references with conversations; current links/quotes take priority over old work and the default course.
- Resolve unquoted “this assignment” against current deadlines across all courses, asking when ambiguous.
- Redact signed URLs in approval previews. Automatic mode remains disabled by default; no broad permissions were added.

## 0.5.2 — 2026-10-14

- Report the project version in the MCP handshake instead of the SDK version.
- Preserve description, license, and source annotations in the GHCR multiarchitecture OCI index, and verify them before release creation.
- Verify downloaded wheel/image packages and record owner confirmation of the final agent reply.
- Correct package visibility documentation after anonymous public download verification.

## 0.5.1 — 2026-10-14

- Distribute Linux amd64/arm64 MCP images through GHCR, with digest-pinned base images and protocol checks before publication.
- Publish wheels, source archives, and SHA256SUMS; verify versions and private-file exclusion before upload.
- Update package metadata for Canvas MCP, Telegram reminders, and local Codex/Claude agents.
- Add package installation and end-to-end validation guides.

## 0.5.0 — 2026-10-14

- Add `canvas-agent setup` with explicit provider/account choice, official login, manual/automatic modes, and review before saving or starting.
- Save `CANVAS_AGENT_PROVIDER` in `.env`, without an implicit provider for start.
- Show both receiver statuses, provide `--json` for scripts, and separate login from service activation.
- Allow cancellation and saving without changing existing services.

## 0.4.0 — 2026-10-14

- Add an opt-in daily local worker, attempt ledger, independent submission verification, and no automatic task replay.
- Recover provisional Codex conversations without history while preserving real conversations and uncertain operations.
- Add an architecture overview and documentation for the three independent flows.

## 0.3.0 — 2026-10-13

- Add owner-only Telegram/Codex polling with ChatGPT login and Codex App Server.
- Support the official Claude Code Telegram plugin, subject to Channels policy.
- Add macOS LaunchAgent support, persistent conversations, approvals, and coursework attachments.

## 0.2.0 — 2026-10-13

- Official bundled REST catalog: 1,118 operations across 144 groups, with offline discovery.
- Generic GET/POST/PUT/PATCH/DELETE execution, JSON/forms/multipart/raw/binary bodies.
- 18 MCP tools, including GraphQL queries/mutations, file transfers, and assignment submission.
- Optional read-only mode hides four mutation tools and blocks HTTP writes.
- Token-free storage transfer clients; writes never retry automatically.
- Optional Telegram deadline reminders, private chat-ID discovery, and a gated weekly Actions workflow.
- Mocked coverage of the method/route inventory and functional write/transfer/GraphQL tests.
- API, Telegram, and scheduling guides. At this release, Telegram replies and LLM integration were still pending.
- Contributor guidance and MCP templates for Claude Code, Codex, Gemini CLI, Cursor, and Kiro.
- Private configs/reports ignored; personal expiration notes excluded from public examples.
- Optional weekly snapshots and launchd/cron examples; installation activates no scheduler.

## 0.1.0 — 2026-10-13

- Local stdio MCP with eight read-only course, assignment, deadline, and content tools.
- Canvas GET client with pagination, same-origin checks, bounded retries, and sanitized errors.
- Compact deadline summaries and complete assignment/page text with retained links.
- São Paulo weekly windows, effective student dates, and own submission status.
- Explicit `.env` configuration, declared expiry reminder, and safe diagnostics.
- Mocked unit/protocol tests, optional live verification, client examples, and CI.
- Claude Code/Codex setup guides and shared AGENTS.md instructions.
