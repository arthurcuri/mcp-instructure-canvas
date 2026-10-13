import json
import os
import sys

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from canvas_mcp.client import CanvasClient
from canvas_mcp.server import create_server


async def test_registered_tools_are_read_only_and_return_structured_results(settings):
    client = CanvasClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{"id": 1, "due_at": None}])
        ),
    )
    try:
        server = create_server(settings, client)
        tools = await server.list_tools()
        assert len(tools) == 8
        assert all(tool.annotations.readOnlyHint for tool in tools)
        assert all(tool.annotations.destructiveHint is False for tool in tools)
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
            await session.initialize()
            tools = await session.list_tools()
            assert len(tools.tools) == 8
            result = await session.call_tool("get_assignment", {"assignment_id": -1})
            assert result.isError
            assert "inteiro positivo" in result.content[0].text
            assert "test-secret" not in json.dumps(result.model_dump())
