import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from canvas_mcp.notifications import (
    TelegramClient,
    TelegramError,
    TelegramSettings,
    reminder_messages,
)


@pytest.fixture
def telegram_settings():
    return TelegramSettings("12345:synthetic-secret", "123")


@pytest.fixture
def report():
    return {
        "count": 1,
        "timezone": "America/Sao_Paulo",
        "undated_count": 2,
        "assignments": [
            {
                "name": "Work <b>plain text</b>",
                "course_name": "Course",
                "due_at_local": "2030-06-30T09:00:00-03:00",
                "html_url": "https://canvas.example.test/courses/1/assignments/2",
            }
        ],
    }


async def test_reminder_sends_plain_text_only_to_configured_chat(telegram_settings, report):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "api.telegram.org"
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload["chat_id"] == "123"
        assert "parse_mode" not in payload
        assert "Work <b>plain text</b>" in payload["text"]
        assert "30/06 às 09:00" in payload["text"]
        assert "Quer ajuda" in payload["text"]
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    client = TelegramClient(telegram_settings, transport=httpx.MockTransport(handle))
    assert await client.send_report(report) == 1
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", ["timeout", "rate_limit", "invalid_json", "not_ok", "missing_id"]
)
async def test_telegram_failures_do_not_retry_or_expose_token(telegram_settings, report, failure):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(str(request.url), request=request)
        if failure == "rate_limit":
            return httpx.Response(429, text=telegram_settings.token)
        if failure == "invalid_json":
            return httpx.Response(200, text=telegram_settings.token)
        if failure == "not_ok":
            return httpx.Response(200, json={"ok": False, "description": telegram_settings.token})
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = TelegramClient(telegram_settings, transport=httpx.MockTransport(handle))
    with pytest.raises(TelegramError) as error:
        await client.send_report(report)
    assert telegram_settings.token not in str(error.value)
    assert len(calls) == 1


def test_long_reminder_is_split_without_losing_text(report):
    report["assignments"][0]["name"] = "👩‍💻" * 3000
    messages = reminder_messages(report)
    assert len(messages) > 1
    assert all(0 < len(message.encode("utf-16-le")) // 2 < 4096 for message in messages)
    assert "👩‍💻" * 3000 in "".join(messages)
    assert "Quer ajuda" in messages[-1]


async def test_setup_lists_only_private_chat_ids_without_sending(telegram_settings):
    def handle(request):
        assert request.url.path.endswith("/getUpdates")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {
                        "message": {
                            "text": "private message",
                            "chat": {"type": "private", "id": 123},
                        }
                    },
                    {"message": {"chat": {"type": "private", "id": 123}}},
                    {"message": {"chat": {"type": "group", "id": -777}}},
                ],
            },
        )

    client = TelegramClient(telegram_settings, transport=httpx.MockTransport(handle))
    assert await client.private_chat_ids() == [123]


def test_telegram_settings_keep_token_private_and_obey_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN=12345:private-secret\nTELEGRAM_CHAT_ID=123\n")
    settings = TelegramSettings.load(path)
    assert "private-secret" not in repr(settings)
    assert settings.chat_id == "123"
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
    assert TelegramSettings.load(path).chat_id == "456"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "https://attacker.test/token")
    with pytest.raises(TelegramError) as error:
        TelegramSettings.load(path)
    assert "attacker.test" not in str(error.value)


def test_weekly_notification_is_opt_in_and_stays_canvas_readonly(tmp_path, monkeypatch, capsys):
    import sys

    from canvas_mcp.client import CanvasClient
    from canvas_mcp.weekly import main

    for name in (
        "CANVAS_API_URL",
        "CANVAS_API_TOKEN",
        "CANVAS_DEFAULT_COURSE_ID",
        "CANVAS_READ_ONLY",
        "CANVAS_TIMEZONE",
        "CANVAS_TOKEN_EXPIRES_AT",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / ".env"
    config.write_text(
        "CANVAS_API_URL=https://canvas.example.test\nCANVAS_API_TOKEN=test-secret\nCANVAS_DEFAULT_COURSE_ID=1\nTELEGRAM_BOT_TOKEN=12345:test-secret\nTELEGRAM_CHAT_ID=123\n"
    )
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    def canvas(settings):
        assert settings.read_only
        return CanvasClient(
            settings,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json=[{"id": 2, "name": "Private assignment", "due_at": due}]
                )
            ),
        )

    monkeypatch.setattr("canvas_mcp.weekly.CanvasClient", canvas)
    deliveries = []

    class FakeTelegram:
        def __init__(self, settings):
            assert settings.chat_id == "123"

        async def send_report(self, report):
            deliveries.append(report)
            return 1

    monkeypatch.setattr("canvas_mcp.weekly.TelegramClient", FakeTelegram)
    argv = [
        "canvas-weekly-check",
        "--env-file",
        str(config),
        "--output",
        str(tmp_path / "report.json"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 0
    assert deliveries == []
    monkeypatch.setattr(sys, "argv", [*argv, "--telegram"])
    assert main() == 0
    assert len(deliveries) == 1
    logs = capsys.readouterr()
    assert "Private assignment" not in logs.out
    assert "test-secret" not in logs.out + logs.err
