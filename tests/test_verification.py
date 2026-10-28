"""Live verifier orchestration tested entirely with a fake MCP session."""

import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from canvas_mcp import __version__

spec = importlib.util.spec_from_file_location(
    "verify_mcp", Path(__file__).parents[1] / "scripts/verify_mcp.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "course_ids, requested, selected",
    [([], None, None), ([7, 8], None, 7), ([7, 8], 8, 8), ([], 9, 9)],
)
async def test_verifier_needs_no_default_course_and_prints_no_content(
    monkeypatch, capsys, course_ids, requested, selected
):
    calls = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "list_courses":
            data = {
                "count": len(course_ids),
                "courses": [{"id": identifier} for identifier in course_ids],
            }
        elif name == "get_due_assignments":
            data = {"count": 0, "start_inclusive": "start", "end_exclusive": "end"}
        else:
            # Every course-specific read must have explicit scope, including details.
            assert arguments["course_id"] == selected
            data = {
                "get_course": {"id": selected},
                "list_assignments": {"count": 1, "assignments": [{"id": 42}]},
                "get_assignment": {
                    "description": "Private course text",
                    "description_complete": True,
                },
                "list_modules": {"count": 1, "modules": [{"items": [{"id": 1}]}]},
                "list_pages": {"count": 1, "pages": [{"url": "private-page"}]},
                "get_page": {"body": "Private page text", "body_complete": True},
            }[name]
        return SimpleNamespace(isError=False, structuredContent=data)

    session = SimpleNamespace(
        initialize=AsyncMock(
            return_value=SimpleNamespace(serverInfo=SimpleNamespace(version=__version__))
        ),
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[
                    SimpleNamespace(annotations=SimpleNamespace(readOnlyHint=index < 12))
                    for index in range(14)
                ]
            )
        ),
        call_tool=call_tool,
    )

    @asynccontextmanager
    async def stdio_context(*args, **kwargs):
        yield None, None

    @asynccontextmanager
    async def session_context(*args, **kwargs):
        yield session

    monkeypatch.setattr(module, "stdio_client", stdio_context)
    monkeypatch.setattr(module, "ClientSession", session_context)
    await module.main(course_id=requested)
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["mcp_verified"] is True
    assert result["courses"] == len(course_ids)
    assert "Private" not in output
    assert "private-page" not in output
    assert ("get_due_assignments", {"period": "next_7_days", "all_courses": True}) in calls
    if selected is None:
        assert result["course_checks_skipped"] is True
        assert len(calls) == 2
    else:
        assert result["course_id"] == selected
        assert result["description_complete"] is True
        assert result["page_body_complete"] is True
