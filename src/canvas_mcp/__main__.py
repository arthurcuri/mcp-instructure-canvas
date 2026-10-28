"""Console entry point. stdout is reserved for MCP messages in server mode."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from canvas_mcp import __version__
from canvas_mcp.client import CanvasClient, CanvasError
from canvas_mcp.config import ConfigurationError, Settings
from canvas_mcp.server import create_server
from canvas_mcp.service import CanvasService


async def check_connection(settings: Settings) -> dict:
    client = CanvasClient(settings)
    try:
        await client.get("users/self/profile")
        result = {"connected": True, **settings.public_info()}
        service = CanvasService(settings, client)
        if settings.default_course_id:
            course = await service.get_course()
            assignments = await service.list_assignments()
            result.update(course_name=course["name"], assignment_count=assignments["count"])
        else:
            result["course_count"] = (await service.list_courses())["count"]
        return result
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local Canvas API MCP server with configurable reads and writes."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--env-file", type=Path, help="Explicit .env path; default: .env in the working directory."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--test", action="store_true", help="Test Canvas access without modifying data."
    )
    mode.add_argument(
        "--config", action="store_true", help="Show configuration without credentials."
    )
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env_file)
        if args.config:
            print(json.dumps(settings.public_info(), ensure_ascii=False, indent=2))
        elif args.test:
            print(json.dumps(asyncio.run(check_connection(settings)), ensure_ascii=False, indent=2))
        else:
            create_server(settings).run(transport="stdio")
    except (ConfigurationError, CanvasError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
