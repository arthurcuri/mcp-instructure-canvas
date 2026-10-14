"""Control subscription-based Canvas agents: Codex bridge or official Claude Channels."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

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
            raise AgentError("Instale o Claude Code antes de iniciar o agente.")
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
            raise AgentError("Não foi possível executar o controle do Claude Code.") from None
        if result.returncode:
            message = (result.stdout + result.stderr).lower()
            if "workspace not trusted" in message:
                raise AgentError(
                    "Claude Code exige confiança no projeto: abra claude neste diretório "
                    "e aceite o diálogo de confiança antes de iniciar o agente."
                )
            raise AgentError(
                "Claude Code recusou o comando. Verifique login, versão e política de Channels."
            )
        return result.stdout

    def authentication(self) -> dict:
        try:
            auth = json.loads(self.call(["auth", "status"]))
        except (ValueError, TypeError):
            raise AgentError("Claude Code não retornou um status de autenticação válido.") from None
        if (
            not isinstance(auth, dict)
            or not auth.get("loggedIn")
            or auth.get("authMethod") != "claude.ai"
        ):
            raise AgentError(
                "Entre no Claude Code com sua assinatura pelo /login; "
                "este agente não usa chave de API."
            )
        return {key: auth.get(key) for key in ("loggedIn", "authMethod", "subscriptionType")}

    def prepare(self) -> dict:
        Settings.load(self.env_file)
        telegram = TelegramSettings.load(self.env_file)
        if not telegram.chat_id.isdecimal() or int(telegram.chat_id) < 1:
            raise AgentError("Configure o ID positivo da sua conversa privada em TELEGRAM_CHAT_ID.")
        server = self.project / ".venv/bin/canvas-mcp-server"
        instructions = self.project / "automation/agent_instructions.md"
        if not server.is_file() or not instructions.is_file():
            raise AgentError("Abra o repositório instalado e execute uv sync --locked.")
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
            raise AgentError("Claude Code não retornou uma lista válida de sessões.") from None
        if not isinstance(sessions, list) or any(not isinstance(item, dict) for item in sessions):
            raise AgentError("Formato inesperado na lista de sessões do Claude Code.")
        return sessions

    def state(self) -> dict:
        if not self.state_file.is_file():
            return {}
        try:
            state = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            raise AgentError(
                "Estado local do agente inválido; confira .local/agent/session.json."
            ) from None
        if not isinstance(state, dict):
            raise AgentError("Estado local do agente inválido.")
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
            raise AgentError("Instale Bun para usar o plugin oficial do Telegram.")
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
            (self.project / "automation/agent_instructions.md").read_text(),
        ]
        output = self.call(arguments, environment=self.environment())
        launched = re.search(r"backgrounded\s*·\s*([A-Za-z0-9-]+)", output)
        if launched is None:
            raise AgentError(
                "Claude iniciou sem retornar um ID reconhecível. "
                "Confira claude agents antes de repetir."
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
            raise AgentError("Instale Claude Code e Bun antes de iniciar Channels.")
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
                (self.project / "automation/agent_instructions.md").read_text(),
            ],
            self.environment(),
        )
        return {"started": True}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Controlar o agente Canvas/Telegram com a assinatura do Codex ou Claude Code."
    )
    parser.add_argument("action", choices=["prepare", "start", "status", "stop", "run"])
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        from canvas_mcp.agent_runtime import CodexManager

        manager = (
            CodexManager(args.project_dir, args.env_file)
            if args.provider == "codex"
            else AgentManager(args.project_dir, args.env_file)
        )
        if args.action in {"start", "run"}:
            if args.provider == "claude" and CodexManager(args.project_dir).status()["running"]:
                raise AgentError("Pare o receptor Codex antes de iniciar Claude com o mesmo bot.")
            if args.provider == "codex" and shutil.which("claude"):
                other = AgentManager(args.project_dir, args.env_file).current()
                if (
                    other
                    and other.get("pid")
                    and other.get("status") in {"busy", "waiting", "idle"}
                ):
                    raise AgentError(
                        "Pare o receptor Claude antes de iniciar Codex com o mesmo bot."
                    )
        result = getattr(manager, args.action)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "Falha ao acessar a configuração local do agente."
        )
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
