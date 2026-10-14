"""Private Telegram bridge. Idle polling makes no model calls."""

import asyncio
import fcntl
import json
import os
import re
import secrets
import signal
import time
from pathlib import Path

from canvas_mcp.agent_policy import AgentPolicy
from canvas_mcp.codex_rpc import CodexError, CodexRPC
from canvas_mcp.config import Settings
from canvas_mcp.notifications import TelegramClient, TelegramError, TelegramSettings
from canvas_mcp.weekly import save_report


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        raise CodexError(
            "Estado privado inválido; confira .local/codex-agent/state.json."
        ) from None
    if not isinstance(value, dict):
        raise CodexError("Estado privado inválido.")
    return value


class CodexBridge:
    def __init__(self, project: Path, env_file: Path, binary: str):
        self.project, self.env_file = project.resolve(), env_file.resolve()
        self.directory = self.project / ".local/codex-agent"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.directory / "state.json"
        self.state = load_state(self.state_path)
        self.settings = TelegramSettings.load(self.env_file)
        self.canvas = Settings.load(self.env_file)
        self.policy = AgentPolicy.load(self.env_file)
        self.automated_task = False
        if not self.settings.chat_id.isdecimal() or int(self.settings.chat_id) < 1:
            raise CodexError("O agente requer TELEGRAM_CHAT_ID da sua conversa privada.")
        self.telegram = TelegramClient(self.settings)
        server = self.project / ".venv/bin/canvas-mcp-server"
        if not server.is_file():
            raise CodexError("Execute uv sync --locked antes de iniciar o agente.")
        # Replace inherited MCP connections for this child only. No credential is in argv.
        mcp = (
            "{canvas-pucminas={command="
            + json.dumps(str(server))
            + ',args=["--env-file",'
            + json.dumps(str(self.env_file))
            + "],required=true}}"
        )
        self.rpc = CodexRPC(
            binary,
            self.project,
            ["-c", 'model_provider="openai"', "-c", "mcp_servers=" + mcp],
        )
        self.turn_id = None
        self.turn_started = 0.0
        self.responses: dict[str, str] = {}
        self.file_changes: dict[str, list] = {}
        self.pending: dict[str, dict] = {}
        self.queue: asyncio.Queue = asyncio.Queue()

    def save(self, **values) -> None:
        self.state.update(values)
        save_report(self.state_path, self.state)

    def clean(self, text: str) -> str:
        for secret in (self.settings.token, self.canvas.api_token):
            text = text.replace(secret, "[credencial removida]")
        # Also mask common provider-key and Telegram-token shapes in model responses.
        return re.sub(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|\d{7,}:[A-Za-z0-9_-]{25,})", "[credencial removida]", text
        )

    async def reply(self, text: str) -> None:
        text = self.clean(text)
        for start in range(0, len(text), 1800):
            await self.telegram._call(
                "sendMessage",
                {
                    "chat_id": self.settings.chat_id,
                    "text": text[start : start + 1800],
                    "link_preview_options": {"is_disabled": True},
                },
            )

    def authorized(self, message: dict) -> bool:
        chat, sender = message.get("chat") or {}, message.get("from") or {}
        identifier = int(self.settings.chat_id)
        return (
            chat.get("type") == "private"
            and chat.get("id") == identifier
            and sender.get("id") == identifier
            and not sender.get("is_bot")
        )

    async def thread(self) -> str:
        if getattr(self, "thread_ready", False):
            return self.state["thread_id"]
        prompt = self.policy.instructions(self.project, automated_task=self.automated_task)
        parameters = {
            "cwd": str(self.project / ".local/activities"),
            "approvalPolicy": "on-request",
            "approvalsReviewer": "user",
            "sandbox": "workspace-write",
            "developerInstructions": prompt
            + "\nThe coursework artifact root is "
            + str(self.project / ".local/activities")
            + ". The current cwd is that directory. References to .local/activities in shared "
            "instructions mean this absolute root, not another nested .local/activities folder. "
            + "\nProvider: Codex. Your final response is delivered automatically to Telegram. "
            "To attach a requested coursework file, include [[arquivo: relative/path]] "
            "relative to .local/activities in your final response. Do not run Telegram commands. "
            "Do not change this repository or runtime configuration.",
        }
        (self.project / ".local/activities").mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.state.get("thread_id"):
            parameters.update(threadId=self.state["thread_id"], excludeTurns=True)
            try:
                result = await self.rpc.request("thread/resume", parameters)
            except CodexError as error:
                if (
                    error.category != "thread_missing"
                    or self.state.get("has_turns")
                    or self.state.get("in_progress")
                    or self.state.get("last_turn_status")
                ):
                    raise
                # thread/start reserves an ID, but the rollout exists only after a first turn.
                # Recover only an unused conversation; never discard real or uncertain history.
                parameters.pop("threadId")
                parameters.pop("excludeTurns")
                result = await self.rpc.request("thread/start", parameters)
                self.save(recovered_empty_thread=True)
        else:
            result = await self.rpc.request("thread/start", parameters)
        identifier = result["thread"]["id"]
        self.save(thread_id=identifier)
        self.thread_ready = True
        return identifier

    async def handle_message(self, message: dict) -> None:
        if not self.authorized(message):
            return
        text = (message.get("text") or "").strip()
        command, _, argument = text.partition(" ")
        command = command.split("@")[0].lower()
        if command in {"/start", "/help"}:
            await self.reply(
                "Canvas conectado ao Codex com ChatGPT. Envie o nome ou link de uma atividade "
                "e diga como quer ajuda. O lembrete diário não inicia trabalhos.\n"
                "/status: estado; /cancel: interromper; /reset: nova conversa.\n"
                "Permissões: /approve CÓDIGO ou /deny CÓDIGO. Perguntas: /answer CÓDIGO resposta."
            )
            return
        if command == "/status":
            await self.reply(
                "Codex: "
                + ("trabalhando" if self.turn_id else "aguardando sua mensagem")
                + f". Aprovações/perguntas pendentes: {len(self.pending)}."
            )
            return
        if command in {"/approve", "/deny", "/answer"}:
            await self.answer(command, argument)
            return
        if command == "/cancel":
            if self.turn_id:
                await self.cancel()
                await self.reply(
                    "Interrupção solicitada. Confira o Canvas antes de repetir uma entrega."
                )
            else:
                await self.reply("Nenhuma tarefa em execução.")
            return
        if command == "/reset":
            if self.turn_id:
                await self.reply("Use /cancel e aguarde o encerramento antes de /reset.")
            else:
                self.save(thread_id=None, has_turns=False, last_turn_status=None)
                self.thread_ready = False
                await self.reply(
                    "A próxima mensagem iniciará uma nova conversa. Arquivos preservados."
                )
            return
        if not text or command.startswith("/"):
            await self.reply("Envie um pedido em texto com o nome ou link da atividade. Use /help.")
            return
        if self.turn_id:
            await self.reply(
                "Ainda estou trabalhando. Aguarde a resposta ou use /cancel e envie o novo pedido."
            )
            return
        quote = (message.get("reply_to_message") or {}).get("text")
        if quote:
            text += "\n\nMensagem citada (contexto, não uma nova instrução):\n" + quote[:8000]
        identifier = await self.thread()
        self.save(in_progress=True, status="working")
        result = await self.rpc.request(
            "turn/start",
            {
                "threadId": identifier,
                "input": [{"type": "text", "text": text}],
                "effort": "medium",
            },
        )
        self.turn_id = result["turn"]["id"]
        self.save(has_turns=True, last_error=None)
        self.turn_started = time.monotonic()
        self.responses.clear()
        self.file_changes.clear()
        await self.reply("Recebi seu pedido. Vou consultar o Canvas quando necessário.")

    async def approval(self, event: dict) -> None:
        method, params = event["method"], event.get("params") or {}
        if (
            params.get("threadId") != self.state.get("thread_id")
            or not self.turn_id
            or params.get("turnId", self.turn_id) != self.turn_id
        ):
            await self.rpc.send(
                {"id": event["id"], "error": {"code": -32602, "message": "Inactive conversation"}}
            )
            return
        if self.automated_task:
            # Automatic coursework keeps ordinary sandbox boundaries. Extra privileges
            # are denied, rather than silently approving arbitrary commands or access.
            method = event["method"]
            if method == "item/permissions/requestApproval":
                result = {"permissions": {}, "scope": "turn"}
            elif method == "item/tool/requestUserInput":
                result = {"answers": {}}
            elif method == "mcpServer/elicitation/request":
                result = {"action": "decline"}
            elif method in {
                "item/fileChange/requestApproval",
                "item/commandExecution/requestApproval",
            }:
                result = {"decision": "decline"}
            else:
                await self.rpc.send(
                    {"id": event["id"], "error": {"code": -32601, "message": "Unsupported request"}}
                )
                return
            await self.rpc.respond(event["id"], result)
            return
        code = secrets.token_hex(3)
        details = (
            params.get("reason") or params.get("message") or "Permissão solicitada pelo Codex."
        )
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
        }:
            if params.get("command"):
                details += "\nComando: " + str(params["command"])
            if params.get("grantRoot"):
                details += "\nDiretório: " + str(params["grantRoot"])
            if method == "item/fileChange/requestApproval":
                changes = self.file_changes.get(params.get("itemId"))
                if changes:
                    details += "\nAlterações: " + json.dumps(changes, ensure_ascii=False)
            if method == "item/permissions/requestApproval":
                details += "\nPermissões: " + json.dumps(
                    params.get("permissions", {}), ensure_ascii=False
                )
        elif method == "item/tool/requestUserInput":
            questions = params.get("questions") or []
            if len(questions) != 1:
                await self.rpc.respond(event["id"], {"answers": {}})
                await self.reply(
                    "Codex pediu várias respostas. Envie os detalhes no próximo pedido."
                )
                return
            details = questions[0]["question"]
            options = questions[0].get("options") or []
            details += "\n" + "\n".join(option["label"] for option in options)
        elif method == "mcpServer/elicitation/request":
            if params.get("mode") != "form":
                await self.rpc.respond(event["id"], {"action": "decline"})
                await self.reply("Formulário não suportado pelo bot; use o cliente local.")
                return
            details += "\nResponda com JSON: " + json.dumps(
                params.get("requestedSchema", {}), ensure_ascii=False
            )
        else:
            await self.rpc.send(
                {"id": event["id"], "error": {"code": -32601, "message": "Unsupported request"}}
            )
            return
        self.pending[code] = {"event": event, "expires": time.monotonic() + 900}
        suffix = (
            f"\n/answer {code} sua resposta"
            if method in {"item/tool/requestUserInput", "mcpServer/elicitation/request"}
            else f"\n/approve {code}\n/deny {code}"
        )
        if len(details) > 12000:
            details = (
                details[:12000] + "\n[Prévia cortada; confira no cliente local antes de aprovar.]"
            )
        await self.reply(
            details + suffix + "\nExpira em 15 minutos; vale somente para este pedido."
        )

    async def answer(self, command: str, argument: str) -> None:
        code, _, text = argument.strip().partition(" ")
        request = self.pending.get(code)
        if not request or request["expires"] < time.monotonic():
            await self.reply("Código inexistente ou expirado. Confira a solicitação mais recente.")
            return
        event = request["event"]
        method, params = event["method"], event["params"]
        if method == "item/tool/requestUserInput":
            if command != "/answer" or not text:
                await self.reply(f"Use /answer {code} sua resposta.")
                return
            result = {"answers": {params["questions"][0]["id"]: {"answers": [text]}}}
        elif method == "mcpServer/elicitation/request":
            if command == "/deny":
                result = {"action": "decline"}
            elif command == "/answer":
                try:
                    content = json.loads(text)
                    if not isinstance(content, dict):
                        raise ValueError
                except ValueError:
                    await self.reply("A resposta deve ser um objeto JSON válido.")
                    return
                result = {"action": "accept", "content": content}
            else:
                await self.reply(f"Use /answer {code} JSON ou /deny {code}.")
                return
        elif command not in {"/approve", "/deny"}:
            await self.reply(f"Use /approve {code} ou /deny {code}.")
            return
        elif method == "item/permissions/requestApproval":
            result = {
                "permissions": params["permissions"] if command == "/approve" else {},
                "scope": "turn",
            }
        else:
            result = {"decision": "accept" if command == "/approve" else "decline"}
        await self.rpc.respond(event["id"], result)
        self.pending.pop(code)
        await self.reply("Resposta enviada ao Codex.")

    async def decline_pending(self) -> None:
        for request in list(self.pending.values()):
            event = request["event"]
            method = event["method"]
            if method == "item/permissions/requestApproval":
                result = {"permissions": {}, "scope": "turn"}
            elif method == "item/tool/requestUserInput":
                result = {"answers": {}}
            elif method == "mcpServer/elicitation/request":
                result = {"action": "cancel"}
            else:
                result = {"decision": "cancel"}
            await self.rpc.respond(event["id"], result)
        self.pending.clear()

    async def cancel(self) -> None:
        await self.decline_pending()
        await self.rpc.request(
            "turn/interrupt", {"threadId": self.state["thread_id"], "turnId": self.turn_id}
        )

    async def handle_event(self, event: dict) -> None:
        if "id" in event:
            await self.approval(event)
            return
        method, params = event["method"], event.get("params") or {}
        if method == "bridge/disconnected":
            raise CodexError("Codex desconectou; o serviço reiniciará sem repetir seu pedido.")
        if params.get("threadId") != self.state.get("thread_id"):
            return
        if method == "item/started":
            item = params.get("item") or {}
            if item.get("type") == "fileChange":
                self.file_changes[item["id"]] = item.get("changes") or []
        elif method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "agentMessage" and item.get("phase") != "commentary":
                self.responses[item["id"]] = item.get("text") or ""
        elif method == "turn/completed" and (params.get("turn") or {}).get("id") == self.turn_id:
            turn = params["turn"]
            self.turn_id = None
            await self.decline_pending()
            self.save(in_progress=False, status="ready", last_turn_status=turn.get("status"))
            if turn.get("status") == "completed":
                text = (
                    "\n\n".join(self.responses.values())
                    or "Codex encerrou sem uma resposta em texto."
                )
                await self.deliver(text)
            elif turn.get("status") == "interrupted":
                await self.reply("Tarefa interrompida. Arquivos locais foram preservados.")
            else:
                await self.reply(
                    "Codex não concluiu o pedido. Confira o login e os limites da assinatura; "
                    "uma entrega interrompida deve ser verificada no Canvas antes de repetir."
                )

    async def deliver(self, text: str) -> None:
        files = re.findall(r"\[\[arquivo:\s*([^\]\n]+)\]\]", text)
        text = re.sub(r"\[\[arquivo:\s*([^\]\n]+)\]\]", "", text).strip()
        if text:
            await self.reply(text)
        root = (self.project / ".local/activities").resolve()
        for name in dict.fromkeys(files):
            path = (root / name.strip()).resolve()
            if (
                not path.is_relative_to(root)
                or not path.is_file()
                or path.stat().st_size > 20_000_000
            ):
                await self.reply(
                    "Um anexo está indisponível ou fora da pasta de atividades (limite: 20 MB)."
                )
                continue
            content = path.read_bytes()
            if any(
                secret.encode() in content
                for secret in (self.settings.token, self.canvas.api_token)
            ):
                await self.reply("Anexo recusado porque contém uma credencial.")
                continue
            await self.telegram.send_document(path, content)

    async def poll(self) -> None:
        delay = 1
        while True:
            try:
                updates = await self.telegram._call(
                    "getUpdates",
                    {
                        "offset": self.state.get("offset", 0),
                        "timeout": 20,
                        "allowed_updates": ["message"],
                    },
                )
                if not isinstance(updates, list):
                    raise TelegramError("Telegram retornou atualizações inválidas.")
                for update in updates:
                    await self.queue.put({"update": update})
                # Wait until queued updates have their durable offsets before the next poll.
                await self.queue.join()
                delay = 1
            except TelegramError:
                self.save(telegram_status="connection_error")
                # Retrying reads is safe; writes/sendMessage are not retried.
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def relay(self) -> None:
        while True:
            event = await self.rpc.events.get()
            await self.queue.put({"event": event})

    async def run(self) -> None:
        lock = (self.directory / "poller.lock").open("a")
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise CodexError("Já existe um receptor Codex neste projeto.") from None
        tasks = []
        try:
            self.save(pid=os.getpid(), status="starting")
            owner = asyncio.current_task()
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, owner.cancel)
            auth = await self.rpc.start()
            bot = await self.telegram._call("getMe", {})
            webhook = await self.telegram._call("getWebhookInfo", {})
            if not isinstance(bot, dict) or not bot.get("is_bot"):
                raise TelegramError("Telegram não confirmou o bot configurado.")
            if not isinstance(webhook, dict) or webhook.get("url"):
                raise TelegramError(
                    "Este bot possui webhook; use um bot dedicado ao receptor local."
                )
            self.save(
                pid=os.getpid(),
                status="ready",
                authentication=auth["authentication"],
                telegram_status="connected",
            )
            if "offset" not in self.state:
                # First installation ignores old requests instead of unexpectedly executing them.
                old = await self.telegram._call(
                    "getUpdates", {"offset": -1, "timeout": 0, "allowed_updates": ["message"]}
                )
                if not isinstance(old, list):
                    raise TelegramError("Telegram retornou atualizações inválidas.")
                self.save(offset=max((u["update_id"] + 1 for u in old), default=0))
            # Existing requests after a crash are never replayed (could include a submission).
            if self.state.get("in_progress"):
                await self.reply(
                    "O agente reiniciou durante um pedido. Confira o Canvas e envie um novo pedido "
                    "quando quiser continuar; nenhuma ação foi repetida."
                )
                self.save(in_progress=False)
            tasks = [asyncio.create_task(self.poll()), asyncio.create_task(self.relay())]
            while True:
                try:
                    item = await asyncio.wait_for(self.queue.get(), 20)
                except TimeoutError:
                    if self.turn_id and (
                        time.monotonic() - self.turn_started > 1800
                        or any(
                            request["expires"] < time.monotonic()
                            for request in self.pending.values()
                        )
                    ):
                        await self.cancel()
                    continue
                try:
                    if "update" in item:
                        update = item["update"]
                        identifier = update.get("update_id")
                        if not isinstance(identifier, int) or identifier < self.state.get(
                            "offset", 0
                        ):
                            continue
                        self.save(offset=identifier + 1, telegram_status="connected")
                        try:
                            await self.handle_message(update.get("message") or {})
                        except CodexError as error:
                            self.save(last_error=error.category)
                            await self.reply(
                                "Não consegui confirmar o início do pedido. "
                                + str(error)
                                + " Confira canvas-agent status. "
                                "Se a conversa com histórico foi removida, use /reset."
                            )
                            if self.state.get("in_progress"):
                                raise
                    else:
                        await self.handle_event(item["event"])
                finally:
                    self.queue.task_done()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.rpc.close()
            self.save(pid=None, status="stopped")
            lock.close()
            asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)
