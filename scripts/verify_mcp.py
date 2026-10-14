"""Opt-in live verification over stdio. Prints counts, never credentials or course bodies."""

import argparse
import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main(container: str | None = None) -> None:
    command = ROOT / ".venv" / "bin" / "canvas-mcp-server"
    parameters = StdioServerParameters(
        command=str(command),
        args=["--env-file", str(ROOT / ".env")],
        cwd="/tmp",
    )
    if container:
        parameters = StdioServerParameters(
            command="docker",
            args=["run", "--rm", "-i", "--env-file", str(ROOT / ".env"), container],
        )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert len(tools) in {14, 18}
            reads = [tool for tool in tools if tool.annotations.readOnlyHint]
            assert len(reads) == 12
            results = {}

            async def call(name: str, arguments: dict | None = None) -> dict:
                result = await session.call_tool(name, arguments or {})
                if result.isError:
                    raise RuntimeError(f"Falha na verificação MCP de {name}.")
                assert result.structuredContent is not None
                return result.structuredContent

            results["courses"] = (await call("list_courses"))["count"]
            results["course_id"] = (await call("get_course"))["id"]
            assignments = await call("list_assignments")
            results["assignments"] = assignments["count"]
            due = await call("get_due_assignments")
            results["due_this_week"] = due["count"]
            results["week_start"] = due["start_inclusive"]
            results["week_end_exclusive"] = due["end_exclusive"]
            await call("get_due_assignments", {"period": "next_7_days"})
            results["due_next_7_days_all_courses"] = (
                await call("get_due_assignments", {"period": "next_7_days", "all_courses": True})
            )["count"]
            if assignments["assignments"]:
                assignment = assignments["assignments"][0]
                details = await call("get_assignment", {"assignment_id": assignment["id"]})
                results["description_characters"] = len(details["description"])
                results["description_complete"] = details["description_complete"]
            modules = await call("list_modules")
            results["modules"] = modules["count"]
            results["module_items"] = sum(len(module["items"]) for module in modules["modules"])
            pages = await call("list_pages")
            results["pages"] = pages["count"]
            if pages["pages"]:
                page = await call("get_page", {"page_url": pages["pages"][0]["url"]})
                results["page_body_characters"] = len(page["body"])
                results["page_body_complete"] = page["body_complete"]
            print(
                json.dumps(
                    {
                        "mcp_verified": True,
                        "tools": len(tools),
                        "read_only_tools": len(reads),
                        **results,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", help="Verificar uma imagem Docker com o .env local.")
    asyncio.run(main(parser.parse_args().container))
