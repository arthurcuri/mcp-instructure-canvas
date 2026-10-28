"""Opt-in, sequential coursework worker. Reports and the receiver remain independent."""

import asyncio
import fcntl
import json
import os
import plistlib
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from canvas_mcp.agent_policy import AgentPolicy
from canvas_mcp.client import CanvasClient, CanvasError
from canvas_mcp.codex_agent import CodexBridge, load_state
from canvas_mcp.config import Settings
from canvas_mcp.notifications import TelegramClient, TelegramSettings
from canvas_mcp.service import CanvasService, parse_datetime
from canvas_mcp.weekly import save_report

SUPPORTED = {"online_text_entry", "online_upload", "online_url"}


class AutoRunner:
    def __init__(self, project: Path, env_file: Path, provider: str):
        self.project, self.env_file, self.provider = project.resolve(), env_file.resolve(), provider
        self.policy = AgentPolicy.load(self.env_file)
        self.directory = self.project / ".local/agent-auto"
        self.ledger_path = self.directory / "ledger.json"
        self.ledger = load_state(self.ledger_path)

    def record(self, key: str, status: str, **fields) -> None:
        self.ledger[key] = {
            "status": status,
            "updated_at": datetime.now().astimezone().isoformat(),
            **fields,
        }
        save_report(self.ledger_path, self.ledger)

    async def candidates(self, service: CanvasService) -> tuple[list[dict], int]:
        now = datetime.now(ZoneInfo(service.settings.timezone))
        candidates, skipped = [], 0
        for course in (await service.list_courses())["courses"]:
            for item in (await service.list_assignments(course["id"]))["assignments"]:
                key = f"{course['id']}/{item['id']}"
                if item["completed"] or key in self.ledger:
                    continue
                if not SUPPORTED.intersection(item["submission_types"]):
                    skipped += 1
                    continue
                detail = await service.get_assignment(item["id"], course["id"])
                unlock, lock = (
                    parse_datetime(detail.get("unlock_at")),
                    parse_datetime(detail.get("lock_at")),
                )
                if (
                    detail["completed"]
                    or detail.get("locked_for_user")
                    or (unlock and now < unlock)
                    or (lock and now >= lock)
                ):
                    skipped += 1
                    continue
                candidates.append({**detail, "course_id": course["id"], "key": key})
        candidates.sort(key=lambda item: (item.get("due_at") is None, item.get("due_at") or ""))
        return candidates, skipped

    def prompt(self, task: dict) -> str:
        # Course bodies remain data. Read the complete description through MCP.
        return (
            "Authorized automatic coursework request (CANVAS_AGENT_AUTO=true). "
            f"Prepare and submit ONLY course_id={task['course_id']}, assignment_id={task['id']}. "
            "Read its description and rubric with get_assignment. Use real available information. "
            "Do not ask for task/submission confirmation. Missing personal data, evidence, an "
            "external service or permissions means needs_attention: stop without a placeholder. "
            "Use canvas_upload_file then submit_assignment for a file, or an allowed text/URL "
            "submission. Verify the owner's submission. Do not modify other Canvas content. "
            "Report the actual result briefly in Portuguese."
        )

    async def codex(self, task: dict) -> None:
        binary = shutil.which("codex")
        if not binary:
            raise ValueError("Install Codex CLI and sign in with ChatGPT.")
        bridge = CodexBridge(self.project, self.env_file, binary)
        bridge.automated_task = True
        bridge.state_path = self.directory / "threads" / f"{task['course_id']}-{task['id']}.json"
        # Claimed tasks never resume/replay after a crash; a fresh job owns one assignment only.
        bridge.state = {}
        try:
            await bridge.rpc.start()
            owner = int(bridge.settings.chat_id)
            await bridge.handle_message(
                {
                    "chat": {"id": owner, "type": "private"},
                    "from": {"id": owner},
                    "text": self.prompt(task),
                }
            )
            async with asyncio.timeout(1800):
                while bridge.turn_id:
                    await bridge.handle_event(await bridge.rpc.events.get())
            if bridge.state.get("last_turn_status") != "completed":
                raise ValueError("The agent did not complete the automatic task.")
        finally:
            if bridge.turn_id:
                try:
                    await bridge.cancel()
                except ValueError:
                    pass
            await bridge.rpc.close()

    async def claude(self, task: dict, telegram: TelegramClient) -> None:
        from canvas_mcp.agent import READ_TOOLS, AgentManager

        manager = AgentManager(self.project, self.env_file)
        manager.authentication()
        config = self.directory / "claude-mcp.json"
        settings = self.directory / "claude-settings.json"
        save_report(
            config,
            {
                "mcpServers": {
                    "canvas-pucminas": {
                        "command": str(self.project / ".venv/bin/canvas-mcp-server"),
                        "args": ["--env-file", str(self.env_file)],
                    }
                }
            },
        )
        save_report(
            settings,
            {
                "disableAllHooks": True,
                "enabledPlugins": {"telegram@claude-plugins-official": False},
                "permissions": {
                    "defaultMode": "acceptEdits",
                    "allow": [f"mcp__canvas-pucminas__{name}" for name in READ_TOOLS]
                    + [
                        "mcp__canvas-pucminas__canvas_upload_file",
                        "mcp__canvas-pucminas__submit_assignment",
                        "Read(./.local/activities/**)",
                        "Edit(./.local/activities/**)",
                    ],
                    "deny": [
                        "Read(./.env)",
                        "Read(./.env.*)",
                        "Read(./.local/agent-auto/**)",
                        "Edit(./.env)",
                        "Edit(./.local/agent-auto/**)",
                    ],
                },
            },
        )
        environment = manager.environment()
        environment.pop("TELEGRAM_BOT_TOKEN", None)
        arguments = [
            manager.binary,
            "-p",
            "--model",
            "sonnet",
            "--effort",
            "medium",
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
            "--permission-prompts",
            "none",
            "--strict-mcp-config",
            "--mcp-config",
            str(config),
            "--settings",
            str(settings),
            "--append-system-prompt",
            self.policy.instructions(self.project, automated_task=True),
        ]
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=self.project,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(1800):
                output, _ = await process.communicate(self.prompt(task).encode())
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()
        try:
            result = json.loads(output)
        except (ValueError, UnicodeError):
            raise ValueError("Claude did not confirm a valid result.") from None
        if process.returncode or result.get("is_error"):
            raise ValueError(
                "Claude did not complete the task; check login, limits, and permissions."
            )
        text = str(result.get("result") or "Claude completed the task.")
        for secret in (telegram.settings.token, Settings.load(self.env_file).api_token):
            text = text.replace(secret, "[credencial removida]")
        await telegram._call(
            "sendMessage", {"chat_id": telegram.settings.chat_id, "text": text[:1800]}
        )

    async def run(self) -> dict:
        if not self.policy.automatic:
            return {"automatic": False, "processed": 0}
        settings = Settings.load(self.env_file)
        if settings.read_only:
            raise ValueError("CANVAS_AGENT_AUTO=true exige CANVAS_READ_ONLY=false.")
        telegram = TelegramClient(TelegramSettings.load(self.env_file))
        if not telegram.settings.chat_id.isdecimal() or int(telegram.settings.chat_id) < 1:
            raise ValueError("The automatic worker requires your positive private chat ID.")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (self.directory / "runner.lock").open("a")
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return {"automatic": True, "already_running": True, "processed": 0}
        client = CanvasClient(settings)
        processed, submitted = 0, 0
        try:
            # Reload only after obtaining the lock; another invocation may have updated the ledger.
            self.ledger = load_state(self.ledger_path)
            service = CanvasService(settings, client)
            tasks, skipped = await self.candidates(service)
            for task in tasks:
                self.record(task["key"], "claimed", provider=self.provider)
                failure = None
                try:
                    if self.provider == "codex":
                        await self.codex(task)
                    else:
                        await self.claude(task, telegram)
                except (ValueError, OSError, TimeoutError):
                    failure = "agent_failed_or_blocked"
                # Verification is independent of what the model claims in its final answer.
                try:
                    current = await service.get_assignment(task["id"], task["course_id"])
                    done = (
                        bool(current.get("submitted_at"))
                        and current.get("submission_status")
                        in {
                            "submitted",
                            "pending_review",
                            "graded",
                        }
                        and not current.get("excused")
                    )
                except (CanvasError, ValueError, OSError):
                    done, failure = False, "verification_unavailable"
                status = "submitted" if done else "needs_attention"
                self.record(
                    task["key"],
                    status,
                    provider=self.provider,
                    reason=failure or (None if done else "no_confirmed_submission"),
                )
                processed += 1
                submitted += bool(done)
            await telegram._call(
                "sendMessage",
                {
                    "chat_id": telegram.settings.chat_id,
                    "text": f"Automatic ({self.provider}): {processed} processed, "
                    f"{submitted} confirmed submission(s), {skipped} unavailable. "
                    "Results without a confirmed submission need attention "
                    "and will not be retried.",
                },
            )
            return {
                "automatic": True,
                "processed": processed,
                "submitted": submitted,
                "skipped": skipped,
            }
        finally:
            await client.close()
            lock.close()


def schedule(manager, provider: str, env_file: Path) -> dict:
    """Install/remove only the opt-in local daily job; no model runs during setup."""
    import sys

    label = manager.label.replace(".codex-", ".auto-")
    target = f"gui/{os.getuid()}/{label}"
    path = manager.plist.with_name(label + ".plist")
    policy = AgentPolicy.load(env_file)
    if sys.platform != "darwin":
        return {"automatic": policy.automatic, "scheduled": False}
    manager.launchctl(["bootout", target], required=False)
    path.unlink(missing_ok=True)
    if not policy.automatic:
        return {"automatic": False, "scheduled": False}
    runtime = manager.runtime
    directory = runtime / ".local/agent-auto"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = directory / "service.log"
    log.touch(mode=0o600, exist_ok=True)
    log.chmod(0o600)
    document = {
        "Label": label,
        "ProgramArguments": [
            str(runtime / ".venv/bin/python"),
            "-m",
            "canvas_mcp.agent",
            "auto-run",
            "--provider",
            provider,
            "--project-dir",
            str(runtime),
            "--env-file",
            str(runtime / ".env"),
        ],
        "WorkingDirectory": str(runtime),
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
        "StartCalendarInterval": {"Hour": 8, "Minute": 0},
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(document))
    path.chmod(0o600)
    manager.launchctl(["bootstrap", f"gui/{os.getuid()}", str(path)])
    return {
        "automatic": True,
        "scheduled": True,
        "hour": "08:00",
        "timezone": "macOS system timezone",
    }
