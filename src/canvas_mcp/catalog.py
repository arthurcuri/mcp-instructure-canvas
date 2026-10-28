"""Offline discovery and parameter facts for every operation in the bundled Canvas catalog."""

import json
import re
from functools import lru_cache
from importlib.resources import files
from urllib.parse import quote

from canvas_mcp.client import CanvasError


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    return json.loads(
        files("canvas_mcp").joinpath("data/operations.json").read_text(encoding="utf-8")
    )


class ApiCatalog:
    def __init__(self):
        self.data = load_catalog()
        self.operations = {operation["id"]: operation for operation in self.data["operations"]}

    def get(self, operation_id: str) -> dict:
        operation = self.operations.get(operation_id)
        if operation is None:
            raise CanvasError("Unknown operation. Use search_canvas_operations to find its ID.")
        return operation

    def search(
        self,
        query: str = "",
        method: str | None = None,
        resource: str | None = None,
        limit: int = 10,
    ) -> dict:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50.")
        if resource and resource not in self.data["resources"]:
            raise ValueError("Unknown resource group in the API catalog.")
        tokens = query.casefold().split()
        matches = []
        for operation in self.operations.values():
            if method and operation["method"] != method.upper():
                continue
            if resource and operation["resource"] != resource:
                continue
            text = " ".join(
                str(operation[key]) for key in ("id", "resource", "method", "path", "summary")
            ).casefold()
            if all(token in text for token in tokens):
                matches.append(
                    {key: operation[key] for key in ("id", "resource", "method", "path", "summary")}
                )
        return {
            "catalog_operations": self.data["operation_count"],
            "catalog_resources": self.data["resource_count"],
            "catalog_generated_on": self.data["generated_on"],
            "total_matches": len(matches),
            "returned": min(limit, len(matches)),
            "operations": matches[:limit],
        }

    def schema(self, operation_id: str, include_response_models: bool = False) -> dict:
        operation = self.get(operation_id)
        result = dict(operation)
        if include_response_models:
            result["models"] = self.data["resources"][operation["resource"]]["models"]
        return result

    def render_path(self, operation: dict, parameters: dict | None = None) -> str:
        supplied = parameters or {}
        names = set(re.findall(r"\{([^}]+)\}", operation["path"]))
        if set(supplied) != names:
            missing = names - set(supplied)
            extra = set(supplied) - names
            if missing:
                raise ValueError("Provide path parameters: " + ", ".join(sorted(missing)))
            raise ValueError("Unrecognized path parameters: " + ", ".join(sorted(extra)))
        path = operation["path"]
        for name in names:
            value = supplied[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (str, int))
                or str(value) in {"", ".", ".."}
            ):
                raise ValueError("Path parameters must be IDs or nonempty strings.")
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        return path


def parameter_value(name: str, values: dict) -> tuple[bool, object]:
    """Accept both Canvas bracket notation and nested JSON request bodies."""
    for alias in (name, name.removesuffix("[]"), name + "[]"):
        if alias in values:
            return True, values[alias]
    value = values
    for segment in re.findall(r"[^\[\]]+", name):
        if not isinstance(value, dict) or segment not in value:
            return False, None
        value = value[segment]
    return True, value


def validate_required(
    operation: dict, query: dict | None, body: object, file_parameters: dict | None = None
) -> None:
    for parameter in operation["parameters"]:
        location = parameter["paramType"]
        if location == "path":
            continue
        if location == "query":
            sources = [query or {}]
        else:
            # Canvas also accepts many form fields in the query string.
            sources = [body if isinstance(body, dict) else {}, query or {}, file_parameters or {}]
        found = False
        value = None
        for source in sources:
            found, value = parameter_value(parameter["name"], source)
            if found:
                break
        if parameter.get("required") and (not found or value is None):
            raise ValueError(f"Missing required parameter: {parameter['name']}")
        if found and value is not None and parameter.get("enum"):
            values = value if isinstance(value, list) else [value]
            if any(item not in parameter["enum"] for item in values):
                raise ValueError(f"Value outside the documented choices: {parameter['name']}")
