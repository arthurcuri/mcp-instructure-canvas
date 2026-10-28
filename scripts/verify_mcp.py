"""Opt-in live verification over stdio. Prints counts, never credentials or course bodies."""

import argparse
import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from canvas_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]


async def main(container: str | None = None, course_id: int | None = None) -> None:
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
            initialized = await session.initialize()
            assert initialized.serverInfo.version == __version__
            tools = (await session.list_tools()).tools
            assert len(tools) in {14, 18}
            reads = [tool for tool in tools if tool.annotations.readOnlyHint]
            assert len(reads) == 12
            results = {}

            async def call(name: str, arguments: dict | None = None) -> dict:
                result = await session.call_tool(name, arguments or {})
                if result.isError:
                    raise RuntimeError(f"MCP verification failed for {name}.")
                assert result.structuredContent is not None
                return result.structuredContent

            courses = await call("list_courses")
            results["courses"] = courses["count"]
            results["due_next_7_days_all_courses"] = (
                await call("get_due_assignments", {"period": "next_7_days", "all_courses": True})
            )["count"]
            selected_course = (
                course_id
                if course_id is not None
                else next((course["id"] for course in courses["courses"]), None)
            )
            if selected_course is not None:
                results.update(await verify_course(call, selected_course))
            else:
                results["course_checks_skipped"] = True
            print(
                json.dumps(
                    {
                        "mcp_verified": True,
                        "version": initialized.serverInfo.version,
                        "tools": len(tools),
                        "read_only_tools": len(reads),
                        **results,
                    },
                    indent=2,
                )
            )


async def verify_course(call, course_id: int) -> dict:
    """Use an explicit course so verification never needs a configured default."""
    results = {"course_id": (await call("get_course", {"course_id": course_id}))["id"]}
    assignments = await call("list_assignments", {"course_id": course_id})
    results["assignments"] = assignments["count"]
    due = await call("get_due_assignments", {"course_id": course_id})
    results["due_this_week"] = due["count"]
    results["week_start"] = due["start_inclusive"]
    results["week_end_exclusive"] = due["end_exclusive"]
    await call("get_due_assignments", {"course_id": course_id, "period": "next_7_days"})
    if assignments["assignments"]:
        assignment = assignments["assignments"][0]
        details = await call(
            "get_assignment", {"course_id": course_id, "assignment_id": assignment["id"]}
        )
        results["description_characters"] = len(details["description"])
        results["description_complete"] = details["description_complete"]
    modules = await call("list_modules", {"course_id": course_id})
    results["modules"] = modules["count"]
    results["module_items"] = sum(len(module["items"]) for module in modules["modules"])
    pages = await call("list_pages", {"course_id": course_id})
    results["pages"] = pages["count"]
    if pages["pages"]:
        page = await call(
            "get_page", {"course_id": course_id, "page_url": pages["pages"][0]["url"]}
        )
        results["page_body_characters"] = len(page["body"])
        results["page_body_complete"] = page["body_complete"]
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", help="Verify a Docker image with the local .env.")
    parser.add_argument(
        "--course-id", type=int, help="Course to check; default: first active course."
    )
    args = parser.parse_args()
    if args.course_id is not None and args.course_id < 1:
        parser.error("--course-id must be positive")
    asyncio.run(main(args.container, args.course_id))
