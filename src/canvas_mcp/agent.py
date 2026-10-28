"""Control subscription-based Canvas agents: Codex bridge or official Claude Channels."""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from canvas_mcp.agent_policy import AgentPolicy
from canvas_mcp.client import CanvasError
from canvas_mcp.config import Settings
from canvas_mcp.notifications import TelegramSettings
from canvas_mcp.weekly import save_report

CHANNEL = "plugin:telegram@claude-plugins-official"
SESSION_NAME = "Canvas Telegram"
READ_TOOLS = (
    "list_courses",
    "get_course",
    "list_assignments",
    "get_assignment",
    "get_due_assignments",
    "list_modules",
    "list_pages",
    "get_page",
    "search_canvas_operations",
    "get_canvas_operation",
    "canvas_api_read",
    "canvas_graphql_read",
)


class AgentError(ValueError):
    """A diagnostic that never contains command output or credentials."""


class AgentManager:
    def __init__(self, project: Path, env_file: Path | None = None):
        self.project = project.resolve()
        self.env_file = (env_file or self.project / ".env").resolve()
        self.directory = self.project / ".local/agent"
        self.state_file = self.directory / "session.json"
        self.binary = shutil.which("claude")

    def call(self, arguments: list[str], *, environment: dict | None = None) -> str:
        if not self.binary:
            raise AgentError("Install Claude Code before starting the agent.")
        try:
            result = subprocess.run(
                [self.binary, *arguments],
                cwd=self.project,
                env=environment,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise AgentError("Could not run Claude Code lifecycle commands.") from None
        if result.returncode:
            message = (result.stdout + result.stderr).lower()
            if "workspace not trusted" in message:
                raise AgentError(
                    "Claude Code requires project trust: open claude in this directory "
                    "and accept the trust prompt before starting the agent."
                )
            raise AgentError(
                "Claude Code rejected the command. Check login, version, and Channels policy."
            )
        return result.stdout

    def authentication(self) -> dict:
        try:
            auth = json.loads(self.call(["auth", "status"]))
        except (ValueError, TypeError):
            raise AgentError("Claude Code returned an invalid authentication status.") from None
        if (
            not isinstance(auth, dict)
            or not auth.get("loggedIn")
            or auth.get("authMethod") != "claude.ai"
        ):
            raise AgentError(
                "Sign in to Claude Code with your subscription using /login; "
                "this agent does not use an API key."
            )
        return {key: auth.get(key) for key in ("loggedIn", "authMethod", "subscriptionType")}

    def prepare(self) -> dict:
        Settings.load(self.env_file)
        telegram = TelegramSettings.load(self.env_file)
        if not telegram.chat_id.isdecimal() or int(telegram.chat_id) < 1:
            raise AgentError("Set TELEGRAM_CHAT_ID to your positive private chat ID.")
        server = self.project / ".venv/bin/canvas-mcp-server"
        instructions = self.project / "automation/agent_instructions.md"
        if not server.is_file() or not instructions.is_file():
            raise AgentError("Open the installed repository and run uv sync --locked.")
        access = {
            "dmPolicy": "allowlist",
            "allowFrom": [telegram.chat_id],
            "groups": {},
            "ackReaction": "👀",
            "replyToMode": "first",
            "chunkMode": "newline",
        }
        save_report(self.directory / "telegram/access.json", access)
        save_report(
            self.directory / "mcp.json",
            {
                "mcpServers": {
                    "canvas-pucminas": {
                        "command": str(server),
                        "args": ["--env-file", str(self.env_file)],
                    }
                }
            },
        )
        permissions = {
            "defaultMode": "manual",
            "allow": [f"mcp__canvas-pucminas__{name}" for name in READ_TOOLS]
            + [
                "mcp__plugin_telegram_telegram__reply",
                "mcp__plugin_telegram_telegram__react",
                "mcp__plugin_telegram_telegram__edit_message",
                "mcp__plugin_telegram_telegram__download_attachment",
                "Read(./.local/activities/**)",
                "Edit(./.local/activities/**)",
            ],
            "deny": [
                "Read(./.env)",
                "Read(./.env.*)",
                "Read(./.local/agent/**)",
                "Edit(./.env)",
                "Edit(./.local/agent/**)",
            ],
        }
        save_report(
            self.directory / "settings.json",
            {
                "disableAllHooks": True,
                "permissions": permissions,
                "enabledPlugins": {"telegram@claude-plugins-official": True},
                "env": {
                    "TELEGRAM_STATE_DIR": str(self.directory / "telegram"),
                    "TELEGRAM_ACCESS_MODE": "static",
                },
            },
        )
        # Native background workers do not forward arbitrary shell variables. The official
        # plugin reads its private .env fallback. The project .env remains the source of truth.
        runtime_env = self.directory / "telegram/.env"
        descriptor = os.open(runtime_env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write("TELEGRAM_BOT_TOKEN=" + telegram.token + "\n")
        runtime_env.chmod(0o600)
        (self.project / ".local/activities").mkdir(parents=True, exist_ok=True, mode=0o700)
        return {
            "prepared": True,
            "access": "own_private_chat_only",
            "canvas_credentials_copied": False,
            "telegram_runtime_env": "private_generated_copy",
        }

    def environment(self) -> dict:
        telegram = TelegramSettings.load(self.env_file)
        environment = dict(os.environ)
        for name in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_PROFILE",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CANVAS_API_TOKEN",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
            "CLAUDE_CODE_SIMPLE",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "TELEGRAM_BOT_TOKEN": telegram.token,
                "TELEGRAM_STATE_DIR": str(self.directory / "telegram"),
                "TELEGRAM_ACCESS_MODE": "static",
            }
        )
        return environment

    def sessions(self) -> list[dict]:
        try:
            sessions = json.loads(
                self.call(["agents", "--json", "--all", "--cwd", str(self.project)])
            )
        except (ValueError, TypeError):
            raise AgentError("Claude Code returned an invalid session list.") from None
        if not isinstance(sessions, list) or any(not isinstance(item, dict) for item in sessions):
            raise AgentError("Unexpected Claude Code session list format.")
        return sessions

    def state(self) -> dict:
        if not self.state_file.is_file():
            return {}
        try:
            state = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            raise AgentError(
                "Invalid local agent state; check .local/agent/session.json."
            ) from None
        if not isinstance(state, dict):
            raise AgentError("Invalid local agent state.")
        return state

    def current(self) -> dict | None:
        identifier = self.state().get("session_id")
        if not identifier:
            return None
        return next(
            (
                item
                for item in self.sessions()
                if item.get("sessionId") == identifier
                or item.get("session_id") == identifier
                or item.get("id") == identifier
            ),
            None,
        )

    def start(self) -> dict:
        auth = self.authentication()
        if not shutil.which("bun"):
            raise AgentError("Install Bun to use the official Telegram plugin.")
        existing = self.current()
        if (
            existing
            and existing.get("pid")
            and existing.get("status") in {"busy", "waiting", "idle"}
        ):
            return {
                "started": False,
                "already_running": True,
                "session_id": self.state()["session_id"],
            }
        self.prepare()
        arguments = [
            "--bg",
            "--name",
            SESSION_NAME,
            "--channels",
            CHANNEL,
            "--model",
            "sonnet",
            "--effort",
            "medium",
            "--permission-mode",
            "manual",
            "--mcp-config",
            str(self.directory / "mcp.json"),
            "--settings",
            str(self.directory / "settings.json"),
            "--append-system-prompt",
            AgentPolicy.load(self.env_file).instructions(self.project),
        ]
        output = self.call(arguments, environment=self.environment())
        launched = re.search(r"backgrounded\s*·\s*([A-Za-z0-9-]+)", output)
        if launched is None:
            raise AgentError(
                "Claude started without returning a recognizable ID. "
                "Check claude agents before repeating."
            )
        identifier = launched.group(1)
        save_report(self.state_file, {"session_id": identifier})
        return {
            "started": True,
            "session_id": identifier,
            "authentication": auth,
            "channel_registration": "check_status",
            "permission_mode": "manual",
        }

    def status(self) -> dict:
        state = self.state()
        current = self.current()
        result = {"session_id": state.get("session_id"), "registered_session": current is not None}
        if current:
            for key in ("id", "state", "status", "pid", "waitingFor"):
                if key in current:
                    result[key] = current[key]
            if not current.get("pid"):
                result["channel_registration"] = "stopped"
                return result
            logs = self.call(["logs", str(current["id"])])
            if "--channels blocked by org policy" in logs:
                result["channel_registration"] = "blocked_by_organization"
                result["required_action"] = "Team administrator must enable channelsEnabled"
            elif "TELEGRAM_BOT_TOKEN required" in logs:
                result["channel_registration"] = "missing_token_in_worker"
            else:
                result["channel_registration"] = "not_yet_verified"
        return result

    def stop(self) -> dict:
        current = self.current()
        if current is None:
            return {"stopped": False, "reason": "no_registered_session"}
        identifier = current.get("id") or self.state()["session_id"]
        self.call(["stop", str(identifier)])
        return {"stopped": True}

    def run(self) -> dict:
        self.authentication()
        if not self.binary or not shutil.which("bun"):
            raise AgentError("Install Claude Code and Bun before starting Channels.")
        self.prepare()
        os.chdir(self.project)
        os.execve(
            self.binary,
            [
                self.binary,
                "--channels",
                CHANNEL,
                "--model",
                "sonnet",
                "--effort",
                "medium",
                "--permission-mode",
                "manual",
                "--mcp-config",
                str(self.directory / "mcp.json"),
                "--settings",
                str(self.directory / "settings.json"),
                "--append-system-prompt",
                AgentPolicy.load(self.env_file).instructions(self.project),
            ],
            self.environment(),
        )
        return {"started": True}


def control(action: str, provider: str, project: Path, env_file: Path | None) -> dict:
    """Explicit lifecycle operations; shared by advanced commands and reviewed setup."""
    from canvas_mcp.agent_runtime import CodexManager

    manager = (
        CodexManager(project, env_file) if provider == "codex" else AgentManager(project, env_file)
    )
    if action in {"start", "run"}:
        if provider == "claude" and CodexManager(project, env_file).status()["running"]:
            raise AgentError("Codex is running. Use canvas-agent setup to review switching agents.")
        if provider == "codex" and shutil.which("claude"):
            other = AgentManager(project, env_file).current()
            if other and other.get("pid") and other.get("status") in {"busy", "waiting", "idle"}:
                raise AgentError(
                    "Claude is running. Use canvas-agent setup to review switching agents."
                )
    result = getattr(manager, action)()
    if provider == "claude" and action == "start":
        from canvas_mcp.agent_auto import schedule

        runtime_manager = CodexManager(project, env_file)
        if sys.platform == "darwin" and AgentPolicy.load(runtime_manager.env_file).automatic:
            runtime_manager.install_runtime()
        result["automatic_worker"] = schedule(runtime_manager, "claude", runtime_manager.env_file)
    elif provider == "claude" and action == "stop" and sys.platform == "darwin":
        runtime_manager = CodexManager(project, env_file)
        label = runtime_manager.label.replace(".codex-", ".auto-")
        runtime_manager.launchctl(["bootout", f"gui/{os.getuid()}/{label}"], required=False)
        runtime_manager.plist.with_name(label + ".plist").unlink(missing_ok=True)
    return result


def display(action: str, provider: str | None, result: dict) -> None:
    from canvas_mcp.agent_setup import LABELS

    label = LABELS.get(provider, "Agent")
    if action == "start":
        print(
            f"{label}: "
            + ("already running." if result.get("already_running") else "start requested.")
        )
        print("Check receiver connection: uv run canvas-agent status")
    elif action == "stop":
        print(f"{label}: receiver and local schedule stopped; conversation and files preserved.")
    elif action == "prepare":
        print(f"{label}: installation prepared; no service has been activated.")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Control the Canvas/Telegram agent with a Codex or Claude Code subscription."
    )
    parser.add_argument(
        "action",
        choices=["setup", "login", "prepare", "start", "status", "stop", "run", "auto-run"],
    )
    parser.add_argument(
        "--provider",
        choices=["codex", "claude"],
        help="Override the choice saved in .env for this command.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Structured output for lifecycle/status commands."
    )
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        from canvas_mcp.agent_runtime import CodexManager
        from canvas_mcp.agent_setup import (
            describe_overview,
            login,
            overview,
            resolve_provider,
            setup,
        )

        project = args.project_dir.resolve()
        env_file = (args.env_file or project / ".env").resolve()
        if args.action == "setup":
            if args.json:
                raise AgentError("setup is interactive and does not accept --json.")
            setup(project, env_file, args.provider)
            return 0
        if args.action == "status" and not args.provider:
            result = overview(project, env_file)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                describe_overview(result)
            return 0
        if args.action == "stop" and not args.provider:
            from canvas_mcp.agent_setup import selected_provider

            state = overview(project, env_file)
            providers = {name for name, item in state["providers"].items() if item.get("running")}
            chosen = selected_provider(env_file)
            if chosen:
                providers.add(chosen)
            # On macOS, also remove a scheduled worker whose receiver is already stopped.
            if sys.platform == "darwin":
                providers.add("codex")
            results = {name: control("stop", name, project, env_file) for name in sorted(providers)}
            if args.json:
                print(json.dumps(results, ensure_ascii=False, indent=2))
            elif results:
                print(
                    "Receptores e agendamento local deste projeto encerrados; "
                    "conversa e arquivos preservados."
                )
            else:
                print("No background receiver is active in this project.")
            return 0
        provider = resolve_provider(args.provider, env_file)
        if args.action == "login":
            if args.json:
                raise AgentError("login opens the official flow and does not accept --json.")
            login(provider, project)
            return 0

        if args.action == "auto-run":
            from canvas_mcp.agent_auto import AutoRunner

            runtime_manager = CodexManager(project, env_file)
            project = (
                runtime_manager.runtime
                if (runtime_manager.runtime / ".venv/bin/python").is_file()
                else project
            )
            result = asyncio.run(AutoRunner(project, runtime_manager.env_file, provider).run())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.action == "start" and not args.json:
            from canvas_mcp.agent_setup import LABELS

            print("Starting " + LABELS[provider] + "; using this CLI's existing login.")
            print("To review the account/mode or switch agents, use uv run canvas-agent setup.")
        result = control(args.action, provider, project, env_file)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            display(args.action, provider, result)
        return 0
    except (EOFError, KeyboardInterrupt):
        print(
            "\nOperation interrupted. Completed steps remain in place; "
            "check uv run canvas-agent status.",
            file=sys.stderr,
        )
        return 130
    except (CanvasError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        message = (
            str(error)
            if isinstance(error, (ValueError, CanvasError))
            else "Could not access the local agent configuration."
        )
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
