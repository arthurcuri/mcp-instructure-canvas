"""Offline MCP handshake against a container; synthetic credentials, no Canvas calls."""

import argparse
import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from canvas_mcp import __version__


async def verify(image: str) -> None:
    parameters = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "--rm",
            "-i",
            "--pull=never",
            "-e",
            "CANVAS_API_URL=https://canvas.example.test/api/v1",
            "-e",
            "CANVAS_API_TOKEN=synthetic-container-check",
            image,
        ],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            if initialized.serverInfo.version != __version__:
                raise ValueError("A versão anunciada pelo MCP diverge da versão do projeto.")
            tools = (await session.list_tools()).tools
            if len(tools) != 18 or not any(tool.name == "submit_assignment" for tool in tools):
                raise ValueError("A imagem não registrou o conjunto esperado de ferramentas MCP.")
            result = await session.call_tool(
                "search_canvas_operations", {"query": "assignment", "limit": 1}
            )
            if result.isError or not result.structuredContent:
                raise ValueError("A imagem não conseguiu consultar o catálogo embarcado.")
            print(
                json.dumps(
                    {"container_mcp_verified": True, "tools": len(tools), "network_calls": 0}
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    asyncio.run(verify(parser.parse_args().image))
