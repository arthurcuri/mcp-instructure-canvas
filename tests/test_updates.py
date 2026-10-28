from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from canvas_mcp.client import CanvasClient
from canvas_mcp.updates import CanvasUpdates

NOW = datetime(2026, 10, 28, 12, tzinfo=ZoneInfo("America/Sao_Paulo"))
START = "2026-10-26T03:00:00Z"
RECENT = "2026-10-27T15:00:00Z"
OLD = "2026-10-26T02:59:59Z"


def sources(request):
    if request.url.path.endswith("/announcements"):
        assert request.url.params["context_codes[]"] == "course_1"
        assert request.url.params["active_only"] == "true"
        # Explicit offsets keep today's posts from being lost at UTC midnight.
        assert request.url.params["end_date"] == NOW.isoformat()
        return [
            {"id": 1, "title": "New announcement", "posted_at": START},
            {"id": 2, "title": "Old announcement", "posted_at": OLD},
            {"id": 3, "title": "Unpublished", "posted_at": None, "last_reply_at": RECENT},
            {"id": 4, "title": "Draft", "posted_at": RECENT, "published": False},
            {"id": 5, "title": "Future", "posted_at": "2026-10-29T03:00:00Z"},
        ]
    if request.url.path.endswith("/discussion_topics"):
        return [
            {
                "id": 1,
                "title": "Old topic with new replies",
                "posted_at": OLD,
                "last_reply_at": RECENT,
            },
            {"id": 2, "title": "Old topic without replies", "posted_at": OLD},
            {
                "id": 3,
                "title": "Announcement duplicate",
                "is_announcement": True,
                "posted_at": RECENT,
            },
        ]
    if request.url.path.endswith("/pages"):
        assert request.url.params["published"] == "true"
        return [
            {"page_id": 1, "title": "Updated page", "url": "updated-page", "updated_at": RECENT},
            {
                "page_id": 2,
                "title": "Hidden draft",
                "url": "draft",
                "published": False,
                "updated_at": RECENT,
            },
        ]
    if request.url.path.endswith("/files"):
        return [
            {
                "id": 1,
                "display_name": "Notes.pdf",
                "modified_at": RECENT,
                "url": "https://storage.example.test/file?signature=must-not-leak",
            },
            {"id": 2, "display_name": "Hidden file", "updated_at": RECENT, "hidden_for_user": True},
            {"id": 3, "display_name": "Locked file", "updated_at": RECENT, "locked_for_user": True},
            {"id": 4, "display_name": "Undated"},
        ]
    if request.url.path.endswith("/assignments"):
        assert request.url.params["override_assignment_dates"] == "true"
        return [{"id": 1, "name": "New undated assignment", "created_at": RECENT}]
    if request.url.path.endswith("/calendar_events"):
        assert request.url.params["type"] == "event"
        assert request.url.params["context_codes[]"] == "course_1"
        return [
            {
                "id": 1,
                "title": "Office hours",
                "created_at": RECENT,
                "start_at": "2026-10-29T14:00:00Z",
            }
        ]
    pytest.fail("Unexpected Canvas endpoint")


async def test_weekly_updates_cover_sources_replies_and_local_boundaries_without_signed_urls(
    settings,
):
    calls = []

    def handle(request):
        assert request.method == "GET"
        calls.append(request)
        return httpx.Response(200, json=sources(request))

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        report = await CanvasUpdates(settings, client).collect(
            [{"id": 1, "name": "Course"}], now=NOW
        )
        assert len(calls) == 6
        assert report["count"] == 6
        assert report["start_inclusive"] == "2026-10-26T00:00:00-03:00"
        assert report["end_exclusive"] == NOW.isoformat()
        assert report["complete"] is True and report["source_errors"] == []
        assert report["undated_count"] == 1
        assert {item["kind"] for item in report["items"]} == {
            "announcement",
            "discussion",
            "page",
            "file",
            "assignment",
            "calendar_event",
        }
        assert "must-not-leak" not in str(report)
        assert "storage.example.test" not in str(report)
        event = next(item for item in report["items"] if item["kind"] == "calendar_event")
        assert event["starts_at_local"] == "2026-10-29T11:00:00-03:00"
        attachment = next(item for item in report["items"] if item["kind"] == "file")
        assert attachment["html_url"] == "https://canvas.example.test/courses/1/files/1"
    finally:
        await client.close()


async def test_update_pagination_follows_opaque_links_and_deduplicates_records(settings):
    def handle(request):
        if request.url.path.endswith("/pages"):
            record = {"page_id": 1, "title": "Page", "url": "page", "updated_at": RECENT}
            if request.url.params.get("cursor"):
                assert dict(request.url.params) == {"cursor": "opaque"}
                return httpx.Response(200, json=[record, {**record, "page_id": 2}])
            return httpx.Response(
                200, json=[record], headers={"Link": '<?cursor=opaque>; rel="next"'}
            )
        return httpx.Response(200, json=[])

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        report = await CanvasUpdates(settings, client).collect([{"id": 1}], now=NOW)
        assert report["count"] == 2
    finally:
        await client.close()


async def test_inaccessible_source_is_explicit_and_other_courses_still_get_checked(settings):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if request.url.path.endswith("/files"):
            return httpx.Response(403, text=settings.api_token)
        if request.url.path.endswith("/pages"):
            return httpx.Response(
                200, json=[{"page_id": 1, "title": "Page", "url": "page", "updated_at": RECENT}]
            )
        return httpx.Response(200, json=[])

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        report = await CanvasUpdates(settings, client).collect([{"id": 1}, {"id": 2}], now=NOW)
        assert len(calls) == 12
        assert report["count"] == 2
        assert report["complete"] is False
        assert [error["course_id"] for error in report["source_errors"]] == [1, 2]
        assert settings.api_token not in str(report)
    finally:
        await client.close()


@pytest.mark.parametrize("bad_date", ["not-a-date", "2026-10-27T12:00:00", True])
async def test_malformed_update_dates_fail_explicitly(settings, bad_date):
    client = CanvasClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{"id": 1, "posted_at": bad_date}])
        ),
    )
    try:
        with pytest.raises(ValueError, match="date|timezone"):
            await CanvasUpdates(settings, client).collect([{"id": 1}], now=NOW)
    finally:
        await client.close()


async def test_current_snapshot_cutoff_is_exclusive(settings):
    client = CanvasClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json=[{"id": 1, "posted_at": NOW.isoformat()}])
                if request.url.path.endswith("/announcements")
                else httpx.Response(200, json=[])
            )
        ),
    )
    try:
        report = await CanvasUpdates(settings, client).collect([{"id": 1}], now=NOW)
        assert report["count"] == 0
    finally:
        await client.close()
