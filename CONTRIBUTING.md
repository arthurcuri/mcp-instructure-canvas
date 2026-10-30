# Contributing

Documentation, translations, bug reports, and code contributions are welcome. The project currently has one maintainer; reviews depend on availability.

## Before you start

Search existing issues and pull requests. For a substantial feature, API change, or new dependency, open a feature proposal first to discuss scope. Small fixes and documentation improvements can go straight to a pull request. The [roadmap](ROADMAP.md) identifies useful areas without promising dates or assigning work.

Use English for shared documentation and code comments. Reports and questions in Portuguese are also welcome; imperfect English is fine. Keep the Portuguese README available and update it when installation or behavior changes. Follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Local development

Requirements: Git, Python 3.11+, and [uv](https://docs.astral.sh/uv/getting-started/installation/). The checkout uses Python 3.12 by default. Fork the repository on GitHub, then:

```sh
git clone https://github.com/YOUR-USERNAME/mcp-instructure-canvas.git
cd mcp-instructure-canvas
git switch -c fix/short-description
uv sync --locked
uv run pytest -q
```

No `.env`, Canvas account, network access to Canvas, Telegram bot, or model subscription is needed for the test suite. Tests use synthetic credentials and mocked HTTP. Never run live writes or send messages to test a contribution.

## Make a focused change

- Read [AGENTS.md](AGENTS.md) for architecture, data handling, and behavior that must be preserved. Client-specific guidance imports those same rules.
- Keep Canvas reads and writes separate. Respect `CANVAS_READ_ONLY` in both the MCP surface and transport. Never add automatic write retries.
- Add meaningful regression tests for changed behavior, especially pagination, date boundaries, credential handling, tool schemas, and uncertain write outcomes. Documentation-only changes do not need unit tests.
- Use fictitious institutions, paths, tokens, and coursework in examples and fixtures. Preserve multilingual Canvas content rather than translating user data.
- Keep English as the default for runtime messages and shared instructions. Reminder translations live in `reminder_format.py`; preserve supported Portuguese approval replies and attachment markers for existing users.
- Update the appropriate guide and add a concise entry under `Unreleased` in [CHANGELOG.md](CHANGELOG.md) when behavior changes. Do not bump the release version in ordinary contributions.

## Validate

Run the same checks as CI:

```sh
uv sync --locked
uv run ruff check src tests scripts automation
uv run ruff format --check src tests scripts automation
uv run pytest -q
bash -n automation/run_weekly.sh
uv build
uv run python scripts/verify_distribution.py
```

For formatting changes, run `uv run ruff format src tests scripts automation` and review the diff. CI runs against Python 3.11 and 3.12 on Linux. macOS lifecycle code is covered with mocks; describe any platform-specific verification in your PR.

The opt-in commands `canvas-mcp-server --test` and `scripts/verify_mcp.py` access a real Canvas account. They are not required for contributions. Use them only with your own explicit authorization, and share status/counts rather than course bodies. Do not run an LLM solely to test the MCP protocol.

## Open a pull request

Push your branch to your fork and open a PR against `main`. Describe the problem, resulting behavior, relevant issue, and checks you ran. Explain material compatibility changes and limitations. Keep unrelated refactors separate and leave generated catalog changes out unless they are part of the task.

The maintainer reviews scope, compatibility, security, and tests before merging. Address actionable feedback in the same PR. There is no CLA; contributions are distributed under the repository's [MIT license](LICENSE).

## Bugs, questions, and security

Use the [issue forms](https://github.com/arthurcuri/mcp-instructure-canvas/issues/new/choose) with reproduction steps, version, client, platform, and sanitized errors. Include a small mocked reproduction when possible. Use a feature proposal or question issue for other topics.

Never include `.env`, access tokens, private chat IDs, student data, signed download URLs, or coursework. Follow [SECURITY.md](SECURITY.md) for vulnerabilities instead of reporting exploitable details publicly.
