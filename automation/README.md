# Optional reminders and scheduling

These tools read Canvas deadlines, save a private snapshot, and optionally send it to Telegram. They make **no model calls and no Canvas writes**. Installing or cloning the project does not enable any schedule. The [local agent](../docs/agents.md) is a separate opt-in component.

## Run a private snapshot

After [setup](../docs/setup.md), from the checkout:

```sh
uv run canvas-weekly-check --all-courses --output .local/weekly-report.json
```

The default period is the next seven days. Use `--period this_week` for the local Monday-to-Monday window, or `--course-id 12345` instead of `--all-courses` for one course. Without either, the configured default course is used. `--include-completed` includes completed/excused work.

The JSON snapshot is replaced atomically with mode `600`; `.local/` is ignored. Omitting `--output` prints the report to stdout, which may contain private course data. Scheduling wrappers save the report privately and print only counts.

## Telegram

1. Create a dedicated bot through Telegram's official **@BotFather** and keep its token private.
2. Edit `TELEGRAM_BOT_TOKEN` in your private `.env`. Do not put it in shell commands or browser URLs.
3. Open your new bot's private chat and send `/start`.
4. Before starting any agent receiver, discover private chat IDs:

   ```sh
   uv run canvas-telegram-chats
   ```

5. Put your own numeric private chat ID in `TELEGRAM_CHAT_ID`. If several appear, confirm which is yours.
6. When you explicitly want a real delivery test:

   ```sh
   uv run canvas-weekly-check --all-courses --telegram --output .local/weekly-report.json
   ```

Chat discovery sends no messages and does not advance the polling offset. Use a dedicated bot without a webhook or competing update consumer. Do not run discovery while an agent receiver is active. If no chat appears, send a fresh `/start`.

Without `--telegram`, local snapshot commands do not send messages even if credentials are configured. Reminders use plain text, disable link previews, and split long reports. Delivery is not retried automatically: a transport failure can happen after delivery, and multipart reports can be partially sent. Check the chat before repeating.

A reminder includes selected assignment titles, dates, and links. Reply to a reminder or send its assignment URL to a separately configured agent when you want help; sending a reminder alone does not start agent work.

## GitHub Actions

Two opt-in workflows are included. Both can be run manually before enabling their schedule.

| Frequency | Workflow | Requested time | Enable variable |
|---|---|---|---|
| Daily | [daily-canvas.yml](../.github/workflows/daily-canvas.yml) | Every day, 08:00 São Paulo | `CANVAS_DAILY_ENABLED=true` |
| Weekly | [weekly-canvas.yml](../.github/workflows/weekly-canvas.yml) | Monday, 09:17 São Paulo | `CANVAS_WEEKLY_ENABLED=true` |

Enable one frequency to avoid duplicate Monday reminders. The YAML schedule timezone and the report timezone are separate settings. Edit the workflow schedule if you want a different dispatch timezone or time.

### Configure your own repository

Open **Settings → Secrets and variables → Actions**:

| Type | Name | Value |
|---|---|---|
| Secret | `CANVAS_API_TOKEN` | Your Canvas token |
| Variable | `CANVAS_API_URL` | **Required:** your institution's HTTPS Canvas URL |
| Variable | `CANVAS_TIMEZONE` | Your IANA report timezone; workflow fallback is `America/Sao_Paulo` |
| Secret, optional | `TELEGRAM_BOT_TOKEN` | Your bot token |
| Secret, optional | `TELEGRAM_CHAT_ID` | Your private chat ID |

The workflow deliberately has no default institution URL. Both Telegram secrets must be supplied together to enable delivery. If both are absent, only a private snapshot is produced; incomplete Telegram configuration fails before querying Canvas.

From the Actions tab, manually run the chosen workflow and inspect status/counts. **This sends a real Telegram message when both bot secrets are configured.** To enable recurring runs, set the corresponding enable variable to exactly `true` and disable the other frequency. Pushing source changes alone does not configure secrets or enable scheduled runs.

The helper below is an alternative when you explicitly want to copy the three credentials from your local private `.env` to your own repository, plus URL/timezone variables:

```sh
uv run python automation/configure_github.py --repo YOUR-USERNAME/mcp-instructure-canvas
```

It requires authenticated GitHub CLI and repository permissions. It passes secrets through stdin. Adding `--activate` also enables the daily schedule and disables the weekly one; without that flag, enable variables are unchanged. Review and publish the desired workflows before enabling them. Never upload `.env` itself.

Jobs force Canvas read-only mode and check all active courses. Private reports remain on the ephemeral runner: they are not uploaded as artifacts, cached, or committed. With Telegram enabled, a summary is sent even when no deadlines match. Pending work can appear again on subsequent days; this version has no persistent reminder deduplication.

### Timing and disabling

GitHub Actions can delay or drop scheduled dispatches; the cron is a requested time, not an alarm guarantee. Schedules use the default branch, and public repository schedules may be disabled after inactivity. See the [official schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) and the [recorded delayed run](../docs/validation.md#schedule-timing).

Set `CANVAS_DAILY_ENABLED=false` or `CANVAS_WEEKLY_ENABLED=false` to disable recurring queries. Disabling a workflow in the Actions UI also prevents manual execution. Manual reruns can resend a report; inspect the chat before repeating an uncertain delivery.

Actions usage and runner billing depend on GitHub's current plan and pricing; see [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions). No model provider is involved in these jobs.

## Local macOS scheduling

The wrapper discovers uv or uses an explicit `CANVAS_UV_BIN` absolute path:

```sh
bash automation/run_weekly.sh --all-courses
```

To generate a private launchd file **without activating it**:

```sh
uv run python automation/prepare_launchd.py --all-courses
```

Review `.local/com.canvas-mcp.weekly.plist`. The template requests Monday at 09:00 in the computer's system timezone, saves private logs, and does not include `--telegram`. Add `--telegram` to the private `ProgramArguments` only when you want delivery. Confirm all executable paths and intended timing first.

When you choose to activate it, load the reviewed file from your interactive shell:

```sh
launchctl bootstrap "gui/$(id -u)" "$PWD/.local/com.canvas-mcp.weekly.plist"
```

To remove that scheduled job:

```sh
launchctl bootout "gui/$(id -u)/com.canvas-mcp.weekly"
```

The computer must be available to run local jobs. The generated file alone does not install a service. Keep local scheduling and cloud reminders from overlapping if you want one delivery.

## Cron alternative

Adapt [crontab.example](crontab.example) with an absolute checkout path and install it through `crontab -e` only when desired. It requests Monday at 09:00 in the system timezone. Add `--telegram` explicitly for delivery. Do not install both cron and launchd for the same task; sleeping computers can miss cron runs.

For interactive agent setup, provider/account selection, approvals, and the separate automatic coursework worker, see [Optional Telegram agents](../docs/agents.md).
