"""Opt-in Telegram reminders, with fixed endpoints and credential-safe errors."""

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import dotenv_values

from canvas_mcp.service import parse_datetime


class TelegramError(ValueError):
    """A Telegram failure safe to display without its token-bearing URL."""


@dataclass(frozen=True)
class TelegramSettings:
    token: str = field(repr=False)
    chat_id: str = ""

    @classmethod
    def load(cls, env_file: Path | None = None, *, require_chat: bool = True):
        path = env_file if env_file is not None else Path.cwd() / ".env"
        if env_file is not None and not path.is_file():
            raise TelegramError("O arquivo de configuração do Telegram não existe.")
        values = dotenv_values(path, interpolate=False) if path.is_file() else {}
        token = str(
            os.environ.get("TELEGRAM_BOT_TOKEN", values.get("TELEGRAM_BOT_TOKEN") or "")
        ).strip()
        chat = str(os.environ.get("TELEGRAM_CHAT_ID", values.get("TELEGRAM_CHAT_ID") or "")).strip()
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise TelegramError("Configure TELEGRAM_BOT_TOKEN com o token do BotFather.")
        if require_chat and not re.fullmatch(r"-?[0-9]+", chat):
            raise TelegramError("Configure TELEGRAM_CHAT_ID com o ID numérico do chat.")
        return cls(token, chat)


def reminder_messages(report: dict) -> list[str]:
    lines = [
        f"Canvas: {report['count']} atividade(s) nos próximos dias.",
        f"Fuso: {report['timezone']}",
    ]
    for item in report["assignments"]:
        date = parse_datetime(item.get("due_at_local") or item.get("due_at"))
        due = date.strftime("%d/%m às %H:%M") if date else "sem prazo"
        course = item.get("course_name") or f"Matéria {item.get('course_id', '')}"
        lines.extend(["", f"{course}: {item.get('name', 'Atividade')}", f"Prazo: {due}"])
        if item.get("html_url"):
            lines.append(item["html_url"])
    if report.get("undated_count"):
        lines.extend(["", f"Há {report['undated_count']} atividade(s) sem prazo definido."])
    if report["count"]:
        lines.extend(
            [
                "",
                "Quer ajuda para fazer alguma dessas atividades? "
                "Use Responder nesta mensagem ou envie o nome/link da atividade.",
            ]
        )
    else:
        lines.extend(["", "Nenhuma atividade pendente com prazo nesse período."])
    # Plain text only. 1,800 code points also fit within Telegram's UTF-16 length limit.
    text = "\n".join(lines)
    return [text[index : index + 1800] for index in range(0, len(text), 1800)]


class TelegramClient:
    def __init__(
        self, settings: TelegramSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.settings = settings
        self.transport = transport

    async def send_document(self, path: Path, content: bytes) -> None:
        """Send one already-validated coursework file. Never retry an ambiguous delivery."""
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=False, trust_env=False, transport=self.transport
        ) as http:
            try:
                response = await http.post(
                    f"https://api.telegram.org/bot{self.settings.token}/sendDocument",
                    data={"chat_id": self.settings.chat_id},
                    files={"document": (path.name, content, "application/octet-stream")},
                )
            except httpx.RequestError:
                raise TelegramError(
                    "Envio de anexo interrompido; confira o chat antes de repetir."
                ) from None
        try:
            result = response.json()
        except ValueError:
            raise TelegramError("Telegram não confirmou o anexo; confira o chat.") from None
        if (
            not 200 <= response.status_code < 300
            or not isinstance(result, dict)
            or result.get("ok") is not True
        ):
            raise TelegramError("Telegram recusou o anexo; o envio não foi repetido.")

    async def _call(self, method: str, payload: dict) -> object:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False, transport=self.transport
        ) as http:
            try:
                response = await http.post(
                    f"https://api.telegram.org/bot{self.settings.token}/{method}", json=payload
                )
            except httpx.RequestError:
                raise TelegramError(
                    "Conexão com Telegram interrompida; confira o chat antes de repetir. "
                    "O envio não é repetido automaticamente."
                ) from None
        if not 200 <= response.status_code < 300:
            raise TelegramError(f"Telegram recusou a operação: HTTP {response.status_code}.")
        try:
            result = response.json()
        except ValueError:
            raise TelegramError("Telegram retornou uma resposta inválida.") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise TelegramError(
                "Telegram não confirmou a operação. Confira o bot e o chat configurados."
            )
        return result.get("result")

    async def send_report(self, report: dict) -> int:
        if not re.fullmatch(r"-?[0-9]+", self.settings.chat_id):
            raise TelegramError("Configure TELEGRAM_CHAT_ID antes de enviar.")
        messages = reminder_messages(report)
        for message in messages:
            result = await self._call(
                "sendMessage",
                {
                    "chat_id": self.settings.chat_id,
                    "text": message,
                    "link_preview_options": {"is_disabled": True},
                },
            )
            if not isinstance(result, dict) or not result.get("message_id"):
                raise TelegramError(
                    "Telegram não confirmou um ID de mensagem; confira o chat antes de repetir."
                )
        return len(messages)

    async def private_chat_ids(self) -> list[int]:
        updates = await self._call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
        if not isinstance(updates, list):
            raise TelegramError("Telegram retornou uma lista de conversas inválida.")
        ids = set()
        for update in updates:
            chat = (update.get("message") or {}).get("chat") or {}
            if chat.get("type") == "private" and isinstance(chat.get("id"), int):
                ids.add(chat["id"])
        return sorted(ids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Listar IDs de chats privados que escreveram ao bot, sem enviar mensagens."
    )
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        settings = TelegramSettings.load(args.env_file, require_chat=False)
        ids = asyncio.run(TelegramClient(settings).private_chat_ids())
        for chat in ids:
            print(chat)
        if not ids:
            print("Nenhum chat privado encontrado. Envie /start ao bot e repita.", file=sys.stderr)
    except (TelegramError, OSError) as error:
        print(
            str(error)
            if isinstance(error, TelegramError)
            else "Não foi possível ler a configuração local.",
            file=sys.stderr,
        )
        return 1
    return 0
