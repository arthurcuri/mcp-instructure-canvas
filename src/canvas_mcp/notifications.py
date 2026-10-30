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

from canvas_mcp.reminder_format import notification_language, reminder_messages


class TelegramError(ValueError):
    """A Telegram failure safe to display without its token-bearing URL."""


@dataclass(frozen=True)
class TelegramSettings:
    token: str = field(repr=False)
    chat_id: str = ""
    language: str = "en"

    @classmethod
    def load(cls, env_file: Path | None = None, *, require_chat: bool = True):
        path = env_file if env_file is not None else Path.cwd() / ".env"
        if env_file is not None and not path.is_file():
            raise TelegramError("The Telegram configuration file does not exist.")
        values = dotenv_values(path, interpolate=False) if path.is_file() else {}
        token = str(
            os.environ.get("TELEGRAM_BOT_TOKEN", values.get("TELEGRAM_BOT_TOKEN") or "")
        ).strip()
        chat = str(os.environ.get("TELEGRAM_CHAT_ID", values.get("TELEGRAM_CHAT_ID") or "")).strip()
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise TelegramError("Set TELEGRAM_BOT_TOKEN to the token from BotFather.")
        if require_chat and not re.fullmatch(r"-?[0-9]+", chat):
            raise TelegramError("Set TELEGRAM_CHAT_ID to the numeric chat ID.")
        raw_language = str(
            os.environ.get(
                "CANVAS_NOTIFICATION_LANGUAGE", values.get("CANVAS_NOTIFICATION_LANGUAGE") or "en"
            )
        )
        try:
            language = notification_language(raw_language)
        except ValueError as error:
            raise TelegramError(str(error)) from None
        return cls(token, chat, language)


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
                    "Attachment delivery interrupted; check the chat before repeating it."
                ) from None
        try:
            result = response.json()
        except ValueError:
            raise TelegramError(
                "Telegram did not confirm the attachment; check the chat."
            ) from None
        if (
            not 200 <= response.status_code < 300
            or not isinstance(result, dict)
            or result.get("ok") is not True
        ):
            raise TelegramError("Telegram rejected the attachment; delivery was not retried.")

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
                    "Telegram connection interrupted; check the chat before repeating. "
                    "Delivery is not retried automatically."
                ) from None
        if not 200 <= response.status_code < 300:
            raise TelegramError(f"Telegram rejected the operation: HTTP {response.status_code}.")
        try:
            result = response.json()
        except ValueError:
            raise TelegramError("Telegram returned an invalid response.") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise TelegramError(
                "Telegram did not confirm the operation. Check the configured bot and chat."
            )
        return result.get("result")

    async def send_report(self, report: dict) -> int:
        if not re.fullmatch(r"-?[0-9]+", self.settings.chat_id):
            raise TelegramError("Set TELEGRAM_CHAT_ID before sending.")
        messages = reminder_messages(report, language=self.settings.language)
        for index, message in enumerate(messages):
            if index:
                await asyncio.sleep(1.05)
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
                    "Telegram did not confirm a message ID; check the chat before repeating."
                )
        return len(messages)

    async def private_chat_ids(self) -> list[int]:
        updates = await self._call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
        if not isinstance(updates, list):
            raise TelegramError("Telegram returned an invalid chat list.")
        ids = set()
        for update in updates:
            chat = (update.get("message") or {}).get("chat") or {}
            if chat.get("type") == "private" and isinstance(chat.get("id"), int):
                ids.add(chat["id"])
        return sorted(ids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List IDs of private chats that messaged the bot, without sending messages."
    )
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        settings = TelegramSettings.load(args.env_file, require_chat=False)
        ids = asyncio.run(TelegramClient(settings).private_chat_ids())
        for chat in ids:
            print(chat)
        if not ids:
            print("No private chat found. Send /start to the bot and try again.", file=sys.stderr)
    except (TelegramError, OSError) as error:
        print(
            str(error)
            if isinstance(error, TelegramError)
            else "Could not read the local configuration.",
            file=sys.stderr,
        )
        return 1
    return 0
