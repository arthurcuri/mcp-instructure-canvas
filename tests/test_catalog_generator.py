import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def generator():
    path = Path(__file__).resolve().parents[1] / "scripts/sync_api_catalog.py"
    spec = importlib.util.spec_from_file_location("catalog_generator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_preserves_schema_facts_and_resolves_duplicate_operation_ids(generator):
    index = [{"path": "/Example.json", "description": "Example"}]
    resource = {
        "basePath": "https://canvas.instructure.com/api",
        "models": {
            "Record": {
                "description": "Long prose",
                "properties": {"id": {"type": "integer", "description": "Prose", "example": 99}},
            }
        },
        "apis": [
            {
                "path": "/v1/records/{id}",
                "operations": [
                    {
                        "nickname": "record",
                        "method": "GET",
                        "summary": "Read record",
                        "parameters": [
                            {
                                "name": "id",
                                "paramType": "path",
                                "type": "string",
                                "required": True,
                                "description": "Long prose",
                            }
                        ],
                        "type": "Record",
                    },
                    {
                        "nickname": "record",
                        "method": "DELETE",
                        "summary": "Delete record",
                        "parameters": [],
                        "type": "void",
                    },
                ],
            }
        ],
    }
    catalog = generator.build_catalog(index, [resource])
    assert catalog["operation_count"] == 2
    assert len({item["id"] for item in catalog["operations"]}) == 2
    assert all(item["id"].startswith("example.record_") for item in catalog["operations"])
    assert catalog["resources"]["example"]["models"]["Record"] == {
        "properties": {"id": {"type": "integer"}}
    }
    get = next(item for item in catalog["operations"] if item["method"] == "GET")
    assert get["parameters"][0]["required"] is True
    assert "description" not in get["parameters"][0]
    assert get["response"]["type"] == "Record"
    assert get["path"] == "/api/v1/records/{id}"


def test_generator_rejects_unexpected_origin(generator):
    with pytest.raises(ValueError, match="base path"):
        generator.build_catalog(
            [{"path": "/example.json", "description": "Example"}],
            [{"basePath": "https://attacker.test/api", "apis": []}],
        )
