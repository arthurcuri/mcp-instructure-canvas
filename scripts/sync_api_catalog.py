"""Generate an offline operation catalog from Instructure's public Swagger metadata."""

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

SOURCE = "https://canvas.instructure.com/doc/api"
ROOT = Path(__file__).resolve().parents[1]


def schema_facts(value):
    """Keep schema facts, not long documentation prose or example values."""
    if isinstance(value, list):
        return [schema_facts(item) for item in value]
    if isinstance(value, dict):
        return {
            key: schema_facts(item)
            for key, item in value.items()
            if key not in {"description", "notes", "example", "deprecation_description"}
        }
    return value


async def fetch_resources(cache: Path | None) -> tuple[list, list]:
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(
        timeout=45,
        follow_redirects=False,
        headers={"User-Agent": "mcp-instructure-canvas/catalog-generator"},
    ) as client:
        response = await client.get(f"{SOURCE}/api-docs.json")
        response.raise_for_status()
        index = response.json()["apis"]

        async def fetch(entry):
            filename = entry["path"].lstrip("/")
            if "/" in filename or not filename.endswith(".json"):
                raise ValueError("Unexpected resource name in the official index.")
            cached = cache / filename if cache else None
            if cached and await asyncio.to_thread(cached.is_file):
                return json.loads(await asyncio.to_thread(cached.read_text, encoding="utf-8"))
            async with semaphore:
                resource = await client.get(f"{SOURCE}/{filename}")
                resource.raise_for_status()
            data = resource.json()
            if cached:
                await asyncio.to_thread(cached.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(cached.write_text, json.dumps(data), encoding="utf-8")
            return data

        resources = await asyncio.gather(*(fetch(entry) for entry in index))
    return index, resources


def build_catalog(index: list, resources: list) -> dict:
    operations = []
    groups = {}
    for entry, resource in zip(index, resources, strict=True):
        original = entry["path"].lstrip("/").removesuffix(".json")
        name = re.sub(r"[^a-z0-9_]+", "_", original.lower()).strip("_")
        if name in groups:
            raise ValueError("Resource names must be unique.")
        groups[name] = {
            "name": entry["description"],
            "documentation": f"{SOURCE}/{original}.html",
            "models": schema_facts(resource.get("models", {})),
        }
        if resource.get("basePath") != "https://canvas.instructure.com/api":
            raise ValueError("The generator must be updated for a new official API base path.")
        for route in resource.get("apis", []):
            path = "/api" + route["path"]
            if not path.startswith("/api/") or any(item in path for item in ("?", "#", "..", "\\")):
                raise ValueError("Unexpected operation path in the official metadata.")
            for operation in route.get("operations", []):
                method = operation["method"].upper()
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                    raise ValueError("Unsupported HTTP method in the official metadata.")
                operations.append(
                    {
                        "id": f"{name}.{operation['nickname']}",
                        "resource": name,
                        "method": method,
                        "path": path,
                        "summary": operation["summary"],
                        "parameters": schema_facts(operation.get("parameters", [])),
                        "response": {
                            key: schema_facts(operation[key])
                            for key in ("type", "items", "response_fields")
                            if key in operation
                        },
                        "deprecated": operation.get("deprecated", False),
                        "documentation": groups[name]["documentation"],
                    }
                )
    identifiers = Counter(operation["id"] for operation in operations)
    for operation in operations:
        if identifiers[operation["id"]] > 1:
            digest = hashlib.sha256(
                f"{operation['method']} {operation['path']}".encode()
            ).hexdigest()[:8]
            operation["id"] += f"_{digest}"
    if len({operation["id"] for operation in operations}) != len(operations):
        raise ValueError("The official catalog contains duplicate operation identifiers.")
    operations.sort(key=lambda operation: operation["id"])
    return {
        "source": f"{SOURCE}/api-docs.json",
        "generated_on": datetime.now(UTC).date().isoformat(),
        "resource_count": len(groups),
        "operation_count": len(operations),
        "methods": dict(sorted(Counter(operation["method"] for operation in operations).items())),
        "resources": groups,
        "operations": operations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "src/canvas_mcp/data/operations.json")
    args = parser.parse_args()
    index, resources = asyncio.run(fetch_resources(args.cache_dir))
    catalog = build_catalog(index, resources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: catalog[key] for key in ("resource_count", "operation_count", "methods")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
