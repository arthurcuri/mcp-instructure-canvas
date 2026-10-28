# Roadmap

This is a community planning guide, not a release schedule. Priorities can change with maintainer capacity and contributor feedback. Discuss substantial work in an issue before implementing it.

## Current foundation

- Local stdio MCP with separate reads and writes, optional read-only mode, REST discovery, GraphQL, and file transfers.
- Credential-safe transport, opaque pagination, timezone-aware deadlines, and personal submission state.
- Optional reminders and owner-controlled local agents, with mocked regression coverage.

## Near-term priorities

| Area | Useful contributions | How to validate |
|---|---|---|
| Installation | Clear setup across Canvas institutions and MCP clients | Sanitized steps, configuration examples, and reproducible failures |
| Reliability | Regression fixes for pagination, effective dates, approvals, and uncertain outcomes | Focused mocked tests without live writes |
| Documentation | Broken-link fixes, clearer API examples, Portuguese translation updates | Check examples against the implementation and keep local links valid |
| Catalog maintenance | Review changes in the public Instructure schemas | Generator diff, coverage counts, and catalog tests |
| Accessibility | Improve text output and errors for different clients and languages | Representative fixtures, without changing users' original course content |

## Proposals needing design discussion

Multiuser OAuth, authenticated remote MCP transport, broader platform lifecycle support, and a maintained localization system need explicit design and security review. They are not implemented promises. Include the user need, alternatives, compatibility implications, and a testing approach in a feature proposal.

See [CONTRIBUTING.md](CONTRIBUTING.md) to get started. Do not assume an issue is available or labeled for beginners; comment on the relevant issue to coordinate work.
