"""macOS lifecycle for the Codex bridge; foreground mode also works on Linux."""

import asyncio
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from canvas_mcp.codex_agent import CodexBridge, load_state
from canvas_mcp.codex_rpc import CodexError


class CodexManager:
    def __init__(self, project: Path, env_file: Path | None = None):
        self.project = project.resolve()
        self.env_file = (env_file or self.project / ".env").resolve()
        self.directory = self.project / ".local/codex-agent"
        suffix = hashlib.sha256(str(self.project).encode()).hexdigest()[:10]
        self.label = "com.canvas-mcp.codex-" + suffix
        self.plist = Path.home() / "Library/LaunchAgents" / (self.label + ".plist")
        self.target = f"gui/{os.getuid()}/{self.label}"
        self.binary = shutil.which("codex")
        self.runtime = Path.home() / "Library/Application Support/CanvasMCP" / self.label

    def install_runtime(self) -> None:
        """Install local code outside the protected Documents/Desktop folders."""
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("src", "automation", ".claude/skills", ".agents/skills"):
            source = self.project / name
            if source.exists():
                shutil.copytree(source, self.runtime / name, dirs_exist_ok=True)
        for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE", "AGENTS.md", "CLAUDE.md"):
            shutil.copyfile(self.project / name, self.runtime / name)
        credential = self.runtime / ".env"
        descriptor = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(self.env_file.read_bytes())
        credential.chmod(0o600)
        for name in ("codex-agent", "activities"):
            source = self.project / ".local" / name
            target = self.runtime / ".local" / name
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            if source.is_symlink():
                if source.resolve() != target.resolve():
                    raise CodexError("O estado aponta para outra instalação; confira .local.")
            elif source.exists():
                shutil.copytree(source, target, dirs_exist_ok=True)
                source.rename(source.with_name(name + ".before-runtime-" + str(time.time_ns())))
                source.symlink_to(target, target_is_directory=True)
            else:
                source.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source.symlink_to(target, target_is_directory=True)
        uv = shutil.which("uv")
        if not uv:
            raise CodexError("Instale uv para preparar o serviço local.")
        result = subprocess.run(
            [uv, "sync", "--locked", "--no-dev", "--project", str(self.runtime)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode:
            raise CodexError("Falha ao preparar dependências do serviço; confira uv.")

    def bridge(self) -> CodexBridge:
        if not self.binary:
            raise CodexError("Instale Codex CLI e execute codex login com ChatGPT.")
        if sys.platform == "darwin" and (self.runtime / ".venv/bin/python").is_file():
            return CodexBridge(self.runtime, self.runtime / ".env", self.binary)
        return CodexBridge(self.project, self.env_file, self.binary)

    def prepare(self) -> dict:
        if self.status()["running"]:
            raise CodexError("Pare o receptor antes de atualizar sua instalação privada.")
        if sys.platform == "darwin":
            self.install_runtime()
        bridge = self.bridge()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Runtime credentials are private files, never plist environment or process arguments.
        arguments = [
            str(bridge.project / ".venv/bin/python"),
            "-m",
            "canvas_mcp.agent",
            "run",
            "--provider",
            "codex",
            "--project-dir",
            str(bridge.project),
            "--env-file",
            str(bridge.env_file),
        ]
        document = {
            "Label": self.label,
            "ProgramArguments": arguments,
            "WorkingDirectory": str(bridge.project),
            "EnvironmentVariables": {
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
            },
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 30,
            "StandardOutPath": str(bridge.directory / "service.log"),
            "StandardErrorPath": str(bridge.directory / "service.log"),
        }
        path = self.directory / "launchd.plist"
        path.write_bytes(plistlib.dumps(document))
        path.chmod(0o600)
        log = self.directory / "service.log"
        log.touch(mode=0o600, exist_ok=True)
        log.chmod(0o600)
        return {
            "prepared": True,
            "credentials_copied": sys.platform == "darwin",
            "provider": "codex",
            "chat_scope": "owner_only",
            "configuration": str(path),
            "state_exists": bridge.state_path.exists(),
        }

    def launchctl(
        self, arguments: list[str], *, required: bool = True
    ) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["launchctl", *arguments], capture_output=True, text=True, check=False, timeout=20
        )
        if required and result.returncode:
            raise CodexError(
                "launchd recusou a operação; confira canvas-agent status e o login do macOS."
            )
        return result

    def start(self) -> dict:
        if sys.platform != "darwin":
            raise CodexError(
                "Neste sistema use canvas-agent run --provider codex em um serviço local."
            )
        if self.status().get("running"):
            return {"started": False, "already_running": True, "provider": "codex"}
        self.prepare()
        # Fail before registering a recurring job if ChatGPT authentication is unavailable.
        auth = asyncio.run(self.doctor())
        self.plist.parent.mkdir(parents=True, exist_ok=True)
        self.plist.write_bytes((self.directory / "launchd.plist").read_bytes())
        self.plist.chmod(0o600)
        registered = self.launchctl(["print", self.target], required=False).returncode == 0
        if registered:
            self.launchctl(["kickstart", self.target])
        else:
            self.launchctl(["bootstrap", f"gui/{os.getuid()}", str(self.plist)])
        return {
            "started": True,
            "provider": "codex",
            **auth,
            "service": self.label,
            "check": "canvas-agent status",
        }

    async def doctor(self) -> dict:
        bridge = self.bridge()
        try:
            return await bridge.rpc.start()
        finally:
            await bridge.rpc.close()

    def status(self) -> dict:
        state = load_state(self.directory / "state.json")
        running = False
        pid = state.get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
                # PID reuse must not turn another process into our receiver.
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                running = "canvas_mcp.agent run" in result.stdout and (
                    str(self.project) in result.stdout or str(self.runtime) in result.stdout
                )
            except OSError:
                pass
        return {
            "provider": "codex",
            "running": running,
            "status": state.get("status", "not_started"),
            "authentication": state.get("authentication"),
            "telegram": state.get("telegram_status"),
            "conversation_exists": bool(state.get("thread_id")),
            "service": self.label,
        }

    def stop(self) -> dict:
        if sys.platform != "darwin":
            raise CodexError("Encerre o processo em primeiro plano ou seu serviço local.")
        result = self.launchctl(["bootout", self.target], required=False)
        if result.returncode and self.status()["running"]:
            raise CodexError("Não foi possível parar o receptor; confira seu serviço no launchd.")
        self.plist.unlink(missing_ok=True)
        return {"stopped": True, "provider": "codex", "conversation_preserved": True}

    def run(self) -> dict:
        try:
            if not self.binary:
                raise CodexError("Instale Codex CLI e execute codex login com ChatGPT.")
            asyncio.run(CodexBridge(self.project, self.env_file, self.binary).run())
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        return {"stopped": True}
