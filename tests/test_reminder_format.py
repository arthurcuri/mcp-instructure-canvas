from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from canvas_mcp.notifications import TelegramClient, TelegramError, TelegramSettings
from canvas_mcp.reminder_format import reminder_messages, utf16_length


def digest():
    return {
        "count": 1,
        "timezone": "America/Sao_Paulo",
        "undated_count": 1,
        "assignments": [
            {
                "id": 1,
                "course_id": 1,
                "course_name": "Computing - Evening - 2030/2",
                "name": "Final project",
                "due_at_local": "2030-06-30T23:59:00-03:00",
                "html_url": "https://canvas.example.test/courses/1/assignments/1",
            }
        ],
        "updates": {
            "count": 6,
            "start_inclusive": "2030-06-24T00:00:00-03:00",
            "end_exclusive": "2030-06-28T12:00:00-03:00",
            "undated_count": 0,
            "items": [
                news(kind, index)
                for index, kind in enumerate(
                    ["file", "announcement", "assignment", "discussion", "page", "calendar_event"],
                    2,
                )
            ],
            "source_errors": [],
        },
    }


def news(kind, identifier):
    return {
        "kind": kind,
        "id": identifier,
        "course_id": 1,
        "course_name": "Computing - Evening - 2030/2",
        "title": f"{kind} title {identifier}",
        "changed_at_local": "2030-06-27T14:00:00-03:00",
        "html_url": f"https://canvas.example.test/courses/1/{kind}/{identifier}",
    }


def test_grouped_sections_have_short_courses_and_leave_structured_report_unchanged():
    report = digest()
    before = deepcopy(report)
    messages = reminder_messages(report)
    headings = [message.splitlines()[0] for message in messages]
    assert len(messages) == 7
    for heading, expected in zip(
        headings,
        [
            "ASSIGNMENTS WITH DEADLINES",
            "NEW OR UPDATED ASSIGNMENTS",
            "ANNOUNCEMENTS",
            "DISCUSSIONS",
            "MATERIALS",
            "CALENDAR EVENTS",
            "CHECK STATUS",
        ],
        strict=True,
    ):
        assert expected in heading
    announcement = next(message for message in messages if "ANNOUNCEMENTS" in message)
    assert "announcement title 3" in announcement
    assert "file title" not in announcement and "assignment title" not in announcement
    assert "Computing\n" in announcement
    assert "Evening - 2030/2" not in "".join(messages)
    assert report == before


def test_different_courses_with_the_same_short_name_keep_their_distinct_labels():
    report = digest()
    report["updates"]["items"][0]["course_name"] = "Computing - Morning - 2030/2"
    text = "\n".join(reminder_messages(report))
    assert "Computing - Morning - 2030/2" in text
    assert "Computing - Evening - 2030/2" in text


def test_utc_deadline_fallback_is_displayed_in_the_configured_timezone():
    report = digest()
    report["assignments"][0].pop("due_at_local")
    report["assignments"][0]["due_at"] = "2030-07-01T02:59:00Z"
    messages = reminder_messages(report, language="pt-BR")
    assert "Prazo: 30/06/2030 às 23:59" in messages[0]


@pytest.mark.parametrize("matching", ["id", "url"])
def test_due_assignments_are_not_repeated_in_the_weekly_assignment_section(matching):
    report = digest()
    item = report["updates"]["items"][2]
    if matching == "id":
        item.update(id=1)
    else:
        item["html_url"] = report["assignments"][0]["html_url"]
    text = "\n".join(reminder_messages(report))
    assert "Final project" in text
    assert item["title"] not in text
    assert "NEW OR UPDATED ASSIGNMENTS" not in text


def test_normal_items_and_links_remain_whole_with_category_on_every_page():
    report = digest()
    items = [news("announcement", index) for index in range(40)]
    for item in items:
        item["title"] = f"News {item['id']}: " + "Complete words stay together. " * 12
    report["updates"].update(items=items, count=len(items))
    messages = reminder_messages(report)
    pages = [message for message in messages if "ANNOUNCEMENTS" in message.splitlines()[0]]
    assert len(pages) > 1
    assert all(utf16_length(message) <= 4000 for message in messages)
    assert all("continued" in message.splitlines()[0] for message in pages[1:])
    for item in items:
        containing = [message for message in pages if item["html_url"] + "\n" in message + "\n"]
        assert len(containing) == 1
        assert item["title"] in containing[0]


def test_brazilian_portuguese_uses_local_dates_and_clear_aggregated_check_status():
    report = digest()
    report["updates"]["source_errors"] = [
        {
            "source": source,
            "course_id": index,
            "course_name": f"Long private course {index}",
            "error": "Your account does not have permission to perform this operation.",
        }
        for source, count in [("page", 8), ("file", 7)]
        for index in range(count)
    ]
    messages = reminder_messages(report, language="pt-BR")
    text = "\n".join(messages)
    assert "📚 ATIVIDADES COM PRAZO (1)" in messages[0]
    assert "Prazo: 30/06/2030 às 23:59" in text
    assert "📢 COMUNICADOS (1)" in text
    assert "Sem prazo informado no Canvas: 1 atividade." in text
    assert "Páginas: consulta indisponível em 8 disciplinas." in messages[-1]
    assert "Arquivos: consulta indisponível em 7 disciplinas." in messages[-1]
    assert "até domingo" in messages[-1]
    assert "Long private course" not in text
    assert "Your account" not in text and "snapshot" not in text


@pytest.mark.parametrize("language", ["pt", "pt-BR", "PT-br"])
def test_notification_language_is_loaded_without_exposing_credentials(
    tmp_path, monkeypatch, language
):
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CANVAS_NOTIFICATION_LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / ".env"
    config.write_text(
        "TELEGRAM_BOT_TOKEN=123:synthetic-secret\nTELEGRAM_CHAT_ID=123\n"
        f"CANVAS_NOTIFICATION_LANGUAGE={language}\n"
    )
    settings = TelegramSettings.load(config)
    assert settings.language == "pt-BR"
    assert "synthetic-secret" not in repr(settings)
    monkeypatch.setenv("CANVAS_NOTIFICATION_LANGUAGE", "en")
    assert TelegramSettings.load(config).language == "en"
    monkeypatch.setenv("CANVAS_NOTIFICATION_LANGUAGE", "do-not-echo-this-value")
    with pytest.raises(TelegramError, match="CANVAS_NOTIFICATION_LANGUAGE") as error:
        TelegramSettings.load(config)
    assert "do-not-echo" not in str(error.value)


async def test_partial_delivery_does_not_retry_and_waits_between_section_messages(monkeypatch):
    client = TelegramClient(TelegramSettings("123:synthetic-secret", "123", "pt-BR"))
    client._call = AsyncMock(side_effect=[{"message_id": 1}, TelegramError("Uncertain delivery")])
    pause = AsyncMock()
    monkeypatch.setattr("canvas_mcp.notifications.asyncio.sleep", pause)
    with pytest.raises(TelegramError, match="Uncertain"):
        await client.send_report(digest())
    assert client._call.await_count == 2
    assert "ATIVIDADES COM PRAZO" in client._call.call_args_list[0].args[1]["text"]
    pause.assert_awaited_once()


async def test_an_unrepresentable_link_is_rejected_before_any_delivery():
    report = digest()
    report["assignments"][0]["html_url"] = "https://canvas.example.test/" + "x" * 5000
    client = TelegramClient(TelegramSettings("123:synthetic-secret", "123"))
    client._call = AsyncMock()
    with pytest.raises(ValueError, match="link exceeds"):
        await client.send_report(report)
    client._call.assert_not_called()
