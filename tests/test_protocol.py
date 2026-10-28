import json
import os
import sys
from dataclasses import replace

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from canvas_mcp import __version__
from canvas_mcp.client import CanvasClient
from canvas_mcp.server import create_server


async def test_registered_tools_classify_writes_and_return_structured_results(settings):
    client = CanvasClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{"id": 1, "due_at": None}])
        ),
    )
    try:
        server = create_server(settings, client)
        tools = await server.list_tools()
        assert len(tools) == 18
        writes = {tool.name for tool in tools if tool.annotations.destructiveHint}
        assert writes == {
            "canvas_api_write",
            "canvas_upload_file",
            "submit_assignment",
            "canvas_graphql_write",
        }
        assert all(tool.annotations.destructiveHint == (tool.name in writes) for tool in tools)
        assert {tool.name for tool in tools if not tool.annotations.readOnlyHint} == writes | {
            "canvas_api_download",
            "download_canvas_file",
        }
        assert all(tool.outputSchema for tool in tools)
        _, structured = await server.call_tool("list_assignments", {})
        assert structured["count"] == 1
        with pytest.raises(ToolError, match="slug"):
            await server.call_tool("get_page", {"page_url": "../../users"})
    finally:
        await client.close()


async def test_stdio_handshake_and_tool_errors_work_without_network(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CANVAS_API_URL=https://canvas.example.test\n"
        "CANVAS_API_TOKEN=test-secret\nCANVAS_DEFAULT_COURSE_ID=286470\n"
    )
    environment = {key: value for key, value in os.environ.items() if not key.startswith("CANVAS_")}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "canvas_mcp", "--env-file", str(env_file)],
        env=environment,
        cwd=str(tmp_path),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.version == __version__
            tools = await session.list_tools()
            assert len(tools.tools) == 18
            result = await session.call_tool("get_assignment", {"assignment_id": -1})
            assert result.isError
            assert "positive integer" in result.content[0].text
            assert "test-secret" not in json.dumps(result.model_dump())


async def test_read_only_mode_omits_all_write_tools(settings):
    readonly = replace(settings, read_only=True)
    client = CanvasClient(
        readonly, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    try:
        server = create_server(readonly, client)
        tools = await server.list_tools()
        assert len(tools) == 14
        assert sum(bool(tool.annotations.readOnlyHint) for tool in tools) == 12
        assert all(tool.annotations.destructiveHint is False for tool in tools)
        with pytest.raises(ToolError, match="canvas_api_write"):
            await server.call_tool(
                "canvas_api_read", {"operation_id": "submissions.submit_assignment_courses"}
            )
        with pytest.raises(ToolError, match="matches"):
            await server.call_tool(
                "canvas_graphql_read", {"query": "mutation { deleteCourse(id: 1) { id } }"}
            )
    finally:
        await client.close()


async def test_assignment_submission_posts_content_and_never_placeholder(settings):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/courses/286470/assignments/7/submissions"
        assert json.loads(request.content) == {
            "submission": {"submission_type": "online_upload", "file_ids": [123]},
            "comment": {"text_comment": "Entrega"},
        }
        return httpx.Response(201, json={"id": 44, "workflow_state": "submitted"})

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        server = create_server(settings, client)
        with pytest.raises(ToolError, match="content"):
            await server.call_tool(
                "submit_assignment",
                {"assignment_id": 7, "submission": {"submission_type": "online_text_entry"}},
            )
        assert not calls
        _, result = await server.call_tool(
            "submit_assignment",
            {
                "assignment_id": 7,
                "submission": {"submission_type": "online_upload", "file_ids": [123]},
                "comment": {"text_comment": "Entrega"},
            },
        )
        assert result["data"]["workflow_state"] == "submitted"
        assert len(calls) == 1
    finally:
        await client.close()
