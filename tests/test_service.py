from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from canvas_mcp.client import CanvasClient
from canvas_mcp.content import html_to_text
from canvas_mcp.service import CanvasService


async def test_week_uses_sao_paulo_boundaries_and_own_submission_status(settings):
    # Monday 00:00 locally is 03:00 UTC; Sunday night remains in this week in UTC Monday.
    records = [
        {"id": 1, "due_at": "2026-10-12T02:59:59Z"},
        {"id": 2, "due_at": "2026-10-12T03:00:00Z"},
        {"id": 3, "due_at": "2026-10-19T02:59:59Z"},
        {"id": 4, "due_at": "2026-10-19T03:00:00Z"},
        {"id": 5, "due_at": "2026-10-14T03:00:00Z", "submission": {"submitted_at": "date"}},
        {"id": 6, "due_at": "2026-10-15T03:00:00Z", "submission": {"excused": True}},
        {
            "id": 7,
            "due_at": "2026-10-16T03:00:00Z",
            "submission_types": ["on_paper"],
            "submission": {"workflow_state": "graded", "missing": False},
        },
        {"id": 8, "due_at": None},
        {
            "id": 9,
            "due_at": "2026-10-17T03:00:00Z",
            "submission": {"workflow_state": "graded", "missing": True},
        },
    ]

    def handle(request):
        assert request.method == "GET"
        assert request.url.params["include[]"] == "submission"
        assert request.url.params["override_assignment_dates"] == "true"
        return httpx.Response(200, json=records)

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        service = CanvasService(settings, client)
        now = datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("America/Sao_Paulo"))
        result = await service.get_due_assignments(now=now)
        assert [item["id"] for item in result["assignments"]] == [2, 9, 3]
        assert result["start_inclusive"] == "2026-10-12T00:00:00-03:00"
        assert result["end_exclusive"] == "2026-10-19T00:00:00-03:00"
        assert result["undated_count"] == 1
        assert result["excluded_completed_count"] == 3
        result = await service.get_due_assignments(now=now, include_completed=True)
        assert result["count"] == 6
    finally:
        await client.close()


async def test_next_seven_days_starts_at_current_instant_and_does_not_invent_missing(settings):
    def handle(request):
        return httpx.Response(
            200,
            json=[
                {"id": 1, "due_at": "2026-10-13T14:59:59Z"},
                {"id": 2, "due_at": "2026-10-13T15:00:00Z", "submission_types": ["external_tool"]},
                {"id": 3, "due_at": "2026-10-20T15:00:00Z"},
            ],
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        service = CanvasService(settings, client)
        result = await service.get_due_assignments(
            period="next_7_days",
            now=datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("America/Sao_Paulo")),
        )
        assert [item["id"] for item in result["assignments"]] == [2]
        assert result["assignments"][0]["missing"] is None
    finally:
        await client.close()


async def test_full_description_is_preserved_while_list_omits_it(settings):
    description = "<p>Leia com atenção.</p>" * 1000

    def handle(request):
        record = {"id": 1, "due_at": None, "description": description}
        return httpx.Response(
            200, json=[record] if request.url.path.endswith("assignments") else record
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        service = CanvasService(settings, client)
        summary = await service.list_assignments()
        details = await service.get_assignment(1)
        assert "description" not in summary["assignments"][0]
        assert details["description"].count("Leia com atenção.") == 1000
        assert details["description_complete"] is True
    finally:
        await client.close()


async def test_all_courses_aggregates_active_courses_and_fails_on_ambiguous_scope(settings):
    def handle(request):
        if request.url.path.endswith("/courses"):
            assert request.url.params["enrollment_state"] == "active"
            return httpx.Response(200, json=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
        course_id = int(request.url.path.split("/")[-2])
        return httpx.Response(
            200,
            json=[{"id": course_id, "course_id": course_id, "due_at": "2026-10-16T03:00:00Z"}],
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        service = CanvasService(settings, client)
        result = await service.get_due_assignments(
            all_courses=True, now=datetime(2026, 10, 13, tzinfo=ZoneInfo("UTC"))
        )
        assert result["courses_checked"] == [1, 2]
        assert [item["course_name"] for item in result["assignments"]] == ["A", "B"]
        with pytest.raises(ValueError, match="sem combinar"):
            await service.get_due_assignments(course_id=1, all_courses=True)
    finally:
        await client.close()


async def test_module_items_are_paginated_separately(settings):
    def handle(request):
        if request.url.path.endswith("/modules"):
            # Canvas can omit embedded module items, so always request each collection.
            return httpx.Response(200, json=[{"id": 10, "name": "Módulo", "items_count": 2}])
        assert request.url.path.endswith("/modules/10/items")
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 2, "title": "Two"}])
        return httpx.Response(
            200,
            json=[{"id": 1, "title": "One"}],
            headers={"Link": '<?page=2>; rel="next"'},
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = await CanvasService(settings, client).list_modules()
        assert [item["id"] for item in result["modules"][0]["items"]] == [1, 2]
    finally:
        await client.close()


def test_html_text_preserves_readable_links_and_skips_scripts():
    result = html_to_text(
        '<p>Leia &amp; responda <a href="/courses/1/files/2">o PDF</a>.</p>'
        '<script>secret()</script><style>hide</style><img alt="Diagrama">'
    )
    assert "Leia & responda o PDF (/courses/1/files/2)." in result
    assert "[Imagem: Diagrama]" in result
    assert "secret" not in result
    assert "hide" not in result
