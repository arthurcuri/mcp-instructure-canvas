import json
import re
from collections import Counter
from dataclasses import replace
from urllib.parse import parse_qs

import httpx
import pytest

from canvas_mcp.api import CanvasApi
from canvas_mcp.catalog import ApiCatalog
from canvas_mcp.client import CanvasClient, CanvasError


def test_official_catalog_has_unique_complete_operation_inventory():
    catalog = ApiCatalog()
    assert len(catalog.operations) == catalog.data["operation_count"] == 1118
    assert len(catalog.data["resources"]) == catalog.data["resource_count"] == 144
    assert Counter(op["method"] for op in catalog.operations.values()) == {
        "GET": 563,
        "POST": 236,
        "PUT": 188,
        "PATCH": 6,
        "DELETE": 125,
    }
    assert all(op["resource"] in catalog.data["resources"] for op in catalog.operations.values())
    assert catalog.search("submit assignment", method="POST")["total_matches"] == 2
    assert catalog.schema("users.get_user_profile")["path"] == "/api/v1/users/{user_id}/profile"


async def test_every_catalog_operation_dispatches_its_method_and_route(settings):
    """Exercise the whole bundled route inventory without a live Canvas mutation."""
    expected = None
    calls = 0

    def handle(request):
        nonlocal calls
        assert request.method == expected[0]
        assert request.url.path == expected[1]
        assert request.headers["Authorization"] == f"Bearer {settings.api_token}"
        calls += 1
        return httpx.Response(204)

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        api = CanvasApi(client)
        for operation in api.catalog.operations.values():
            params = {name: "42" for name in re.findall(r"\{([^}]+)\}", operation["path"])}
            expected = (operation["method"], re.sub(r"\{[^}]+\}", "42", operation["path"]))
            query, body = {}, {}
            for parameter in operation["parameters"]:
                if parameter["paramType"] == "path" or not parameter.get("required"):
                    continue
                value = parameter.get("enum", ["42"])[0]
                if parameter.get("type") == "array":
                    value = [value]
                destination = query if parameter["paramType"] == "query" else body
                destination[parameter["name"]] = value
            if operation["method"] == "GET":
                result = await api.read(operation["id"], params, query, paginate=False)
            else:
                result = await api.write(operation["id"], params, query, json_body=body)
            assert result["status_code"] == 204
        assert calls == 1118
    finally:
        await client.close()


@pytest.mark.parametrize(
    "method,status",
    [(method, status) for method in ["POST", "PUT", "PATCH", "DELETE"] for status in [429, 503]],
)
async def test_writes_are_never_automatically_retried(settings, method, status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text=settings.api_token, headers={"Retry-After": "0"})

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CanvasError, match="not retried") as error:
            await client.request(method, "/api/v1/test", full_api=True)
        assert settings.api_token not in str(error.value)
        assert len(calls) == 1
    finally:
        await client.close()


async def test_interrupted_write_reports_indeterminate_result(settings):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout(f"private: {settings.api_token}", request=request)

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CanvasError, match="uncertain") as error:
            await client.request("POST", "/api/v1/test", full_api=True)
        assert settings.api_token not in str(error.value)
        assert len(calls) == 1
    finally:
        await client.close()


async def test_json_form_multipart_and_binary_request_bodies(settings, tmp_path):
    captured = []

    async def handle(request):
        await request.aread()
        captured.append(request)
        return httpx.Response(200, json={"id": 9})

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        api = CanvasApi(client)
        operation = "submissions.submit_assignment_courses"
        params = {"course_id": 1, "assignment_id": 2}
        await api.write(
            operation,
            params,
            json_body={
                "submission": {"submission_type": "online_url", "url": "https://example.test/work"}
            },
        )
        assert json.loads(captured[-1].content)["submission"]["submission_type"] == "online_url"
        await api.write(
            operation,
            params,
            form_parameters={
                "submission": {
                    "submission_type": "online_upload",
                    "file_ids": [7, 8],
                    "group_comment": False,
                }
            },
        )
        form = parse_qs(captured[-1].content.decode())
        assert form["submission[file_ids][]"] == ["7", "8"]
        assert form["submission[group_comment]"] == ["false"]
        attachment = tmp_path / "rubric.csv"
        attachment.write_text("Title,Points\nCriteria,10\n")
        await api.write(
            "rubrics.creates_rubric_using_csv_file_courses",
            {"course_id": 1},
            file_parameters={"attachment": str(attachment)},
        )
        assert b'filename="rubric.csv"' in captured[-1].content
        assert b"Criteria,10" in captured[-1].content
        await api.write(
            "pages.create_page_courses",
            {"course_id": 1},
            query_parameters={"wiki_page[title]": "Page"},
            raw_body="plain body",
            content_type="text/plain",
        )
        assert captured[-1].content == b"plain body"
        assert captured[-1].headers["Content-Type"] == "text/plain"
        await api.write(
            "pages.create_page_courses",
            {"course_id": 1},
            query_parameters={"wiki_page[title]": "Page"},
            binary_body_file=str(attachment),
        )
        assert captured[-1].content == attachment.read_bytes()
    finally:
        await client.close()


async def test_required_fields_and_method_separation_fail_before_network(settings):
    def handle(request):
        pytest.fail("Invalid request reached HTTP transport")

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        api = CanvasApi(client)
        with pytest.raises(ValueError, match="required"):
            await api.write(
                "submissions.submit_assignment_courses", {"course_id": 1, "assignment_id": 2}
            )
        with pytest.raises(ValueError, match="choices"):
            await api.write(
                "submissions.submit_assignment_courses",
                {"course_id": 1, "assignment_id": 2},
                json_body={"submission": {"submission_type": "invalid"}},
            )
        with pytest.raises(ValueError, match="read operation"):
            await api.write("users.get_user_profile", {"user_id": "self"})
        with pytest.raises(ValueError, match="write operation"):
            await api.read("submissions.submit_assignment_courses")
        with pytest.raises(ValueError, match="path parameters"):
            await api.read("users.get_user_profile", {"user_id": "self", "unexpected": 1})
    finally:
        await client.close()


async def test_catalog_read_follows_links_and_redacts_reflected_token(settings):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json=[{"value": settings.api_token}],
                headers={"Link": '</api/v1/courses?cursor=opaque>; rel="next"'},
            )
        assert dict(request.url.params) == {"cursor": "opaque"}
        return httpx.Response(200, json=[{"id": 2}])

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = await CanvasApi(client).read(
            "courses.list_your_courses", query_parameters={"include[]": ["syllabus_body"]}
        )
        assert result["pages"] == 2
        assert result["data"] == [{"value": "[REDACTED]"}, {"id": 2}]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "query,name,mutation,valid",
    [
        ("{ __typename }", None, False, True),
        ("# mutation in comment\nquery Q { __typename }", "Q", False, True),
        ("query Q { __typename } mutation M { createPage { id } }", "Q", False, True),
        ("query Q { __typename } mutation M { createPage { id } }", None, False, False),
        ("mutation M { createPage { id } }", "M", False, False),
        ("query { __typename }", None, True, False),
        ("mutation { createPage { id } }", None, True, True),
        ("subscription { events { id } }", None, False, False),
        ("query {", None, False, False),
    ],
)
async def test_graphql_classifies_selected_operation(settings, query, name, mutation, valid):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.path == "/api/graphql"
        assert json.loads(request.content)["operationName"] == name
        return httpx.Response(200, json={"data": {"__typename": "Query"}})

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        api = CanvasApi(client)
        if valid:
            await api.graphql(query, operation_name=name, mutation=mutation)
            assert len(calls) == 1
        else:
            with pytest.raises(ValueError):
                await api.graphql(query, operation_name=name, mutation=mutation)
            assert not calls
    finally:
        await client.close()


async def test_readonly_blocks_mutations_but_allows_graphql_queries(settings):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"__typename": "Query"}})

    client = CanvasClient(replace(settings, read_only=True), transport=httpx.MockTransport(handle))
    try:
        await CanvasApi(client).graphql("{ __typename }")
        with pytest.raises(CanvasError, match="READ_ONLY"):
            await CanvasApi(client).graphql("mutation { remove { id } }", mutation=True)
        with pytest.raises(CanvasError, match="exception"):
            await client.request("POST", "/api/v1/test", full_api=True, graphql_query=True)
        assert len(calls) == 1
    finally:
        await client.close()


async def test_api_download_keeps_binary_out_of_context_and_refuses_overwrite(settings, tmp_path):
    client = CanvasClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"file content", headers={"Content-Type": "application/zip"}
            )
        ),
    )
    try:
        output = tmp_path / "report.zip"
        result = await CanvasApi(client).download(
            "users.get_user_profile", str(output), {"user_id": "self"}
        )
        assert result["bytes"] == 12
        assert output.read_bytes() == b"file content"
        assert output.stat().st_mode & 0o777 == 0o600
        assert "file content" not in json.dumps(result)
        with pytest.raises(CanvasError, match="already exists"):
            await CanvasApi(client).download(
                "users.get_user_profile", str(output), {"user_id": "self"}
            )
    finally:
        await client.close()
