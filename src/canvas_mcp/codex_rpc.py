"""JSONL client for the installed Codex App Server (managed ChatGPT login)."""

import asyncio
import json
import os
from pathlib import Path

from canvas_mcp import __version__


class CodexError(ValueError):
    """Safe errors; never forward raw provider output or authenticated URLs."""

    def __init__(self, message: str, *, category: str = "provider_error"):
        super().__init__(message)
        self.category = category

    @classmethod
    def from_response(cls, error: dict) -> "CodexError":
        message = str(error.get("message", "")).lower()
        # Classify known failures locally; neither the original message nor data is exposed.
        if "no rollout found" in message or "thread not found" in message:
            return cls(
                "A conversa não tem histórico disponível no Codex.", category="thread_missing"
            )
        if any(word in message for word in ("unauthorized", "not logged in", "authentication")):
            return cls("Renove o login do Codex com ChatGPT.", category="authentication")
        if "required" in message and "mcp" in message:
            return cls(
                "O MCP obrigatório não iniciou; confira a instalação e o Canvas.",
                category="mcp_unavailable",
            )
        return cls("Codex recusou a operação solicitada.")


class CodexRPC:
    def __init__(self, binary: str, cwd: Path, overrides: list[str]):
        self.binary, self.cwd, self.overrides = binary, cwd, overrides
        self.events: asyncio.Queue = asyncio.Queue()
        self.pending: dict[int, asyncio.Future] = {}
        self.sequence = 0
        self.process = None
        self.reader = None

    async def start(self) -> dict:
        environment = dict(os.environ)
        for name in ("OPENAI_API_KEY", "CANVAS_API_TOKEN", "TELEGRAM_BOT_TOKEN"):
            environment.pop(name, None)
        self.process = await asyncio.create_subprocess_exec(
            self.binary,
            *self.overrides,
            "app-server",
            "--listen",
            "stdio://",
            cwd=self.cwd,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,
        )
        self.reader = asyncio.create_task(self.read())
        await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "canvas_telegram",
                    "title": "Canvas Telegram",
                    "version": __version__,
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.send({"method": "initialized"})
        account = (await self.request("account/read", {"refreshToken": False})).get("account")
        if not isinstance(account, dict) or account.get("type") != "chatgpt":
            raise CodexError("Execute codex login com ChatGPT; o agente não usa chave de API.")
        return {"authentication": "chatgpt", "plan": account.get("planType")}

    async def send(self, message: dict) -> None:
        if not self.process or self.process.returncode is not None:
            raise CodexError("Codex App Server não está disponível.")
        try:
            self.process.stdin.write((json.dumps(message) + "\n").encode())
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionError):
            raise CodexError("A conexão local com Codex foi interrompida.") from None

    async def request(self, method: str, params: dict) -> dict:
        self.sequence += 1
        identifier = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            await self.send({"id": identifier, "method": method, "params": params})
            return await asyncio.wait_for(future, 90)
        except TimeoutError:
            raise CodexError("Codex não respondeu a tempo; confira login e conexão.") from None
        finally:
            self.pending.pop(identifier, None)

    async def respond(self, identifier: str | int, result: dict) -> None:
        await self.send({"id": identifier, "result": result})

    async def read(self) -> None:
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message:
                    await self.events.put(message)
                elif (future := self.pending.get(message.get("id"))) and not future.done():
                    if "error" in message:
                        future.set_exception(CodexError.from_response(message["error"]))
                    else:
                        future.set_result(message.get("result") or {})
        except (ValueError, OSError):
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(CodexError("Codex App Server encerrou a conexão."))
            await self.events.put({"method": "bridge/disconnected"})

    async def close(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.terminate()
                await self.process.wait()
        if self.reader:
            await self.reader
