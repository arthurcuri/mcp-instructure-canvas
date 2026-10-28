import json
from dataclasses import replace

import httpx
import pytest

from canvas_mcp.client import CanvasClient, CanvasError
from canvas_mcp.transfers import CanvasTransfers


async def test_three_stage_upload_preserves_storage_fields_and_separates_auth(settings, tmp_path):
    source = tmp_path / "work.txt"
    source.write_text("my actual work")
    api_calls, storage_calls = [], []

    def api(request):
        api_calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {settings.api_token}"
        if request.method == "POST":
            assert json.loads(request.content) == {
                "name": "work.txt",
                "size": 14,
                "content_type": "text/plain",
            }
            return httpx.Response(
                200,
                json={
                    "upload_url": "https://storage.example.test/upload",
                    "upload_params": {
                        "key": "unchanged/key",
                        "policy": "signature",
                        "success_action_redirect": "https://canvas.example.test/api/v1/files/99/create_success?uuid=opaque",
                    },
                },
            )
        assert request.url.path == "/api/v1/files/99/create_success"
        return httpx.Response(200, json={"id": 99, "filename": "work.txt"})

    async def storage(request):
        storage_calls.append(request)
        assert "Authorization" not in request.headers
        await request.aread()
        text = request.content.decode()
        assert "unchanged/key" in text and "signature" in text
        assert text.index('name="file"') > text.index('name="policy"')
        assert settings.api_token not in text
        assert "my actual work" in text
        return httpx.Response(
            303,
            headers={
                "Location": "https://canvas.example.test/api/v1/files/99/create_success?uuid=opaque"
            },
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(api))
    try:
        result = await CanvasTransfers(client, transport=httpx.MockTransport(storage)).upload(
            "submissions.upload_file_courses",
            str(source),
            {"course_id": 1, "assignment_id": 2, "user_id": "self"},
        )
        assert result["file_id"] == 99
        assert result["submission_created"] is False
        assert [request.method for request in api_calls] == ["POST", "GET"]
        assert len(storage_calls) == 1
    finally:
        await client.close()


async def test_upload_refuses_external_authenticated_completion(settings, tmp_path):
    source = tmp_path / "work.txt"
    source.write_text("work")
    api_calls = []

    def api(request):
        api_calls.append(request)
        return httpx.Response(
            200, json={"upload_url": "https://storage.example.test/upload", "upload_params": {}}
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(api))
    try:
        transfers = CanvasTransfers(
            client,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    303, headers={"Location": "https://attacker.test/api/v1/files/99"}
                )
            ),
        )
        with pytest.raises(CanvasError, match="outside the configured API"):
            await transfers.upload("files.upload_file", str(source), {"folder_id": 1})
        assert len(api_calls) == 1
    finally:
        await client.close()


async def test_readonly_refuses_upload_before_opening_or_posting(settings):
    client = CanvasClient(replace(settings, read_only=True))
    try:
        with pytest.raises(CanvasError, match="READ_ONLY"):
            await CanvasTransfers(client).upload(
                "files.upload_file", "/nonexistent", {"folder_id": 1}
            )
    finally:
        await client.close()


async def test_signed_file_download_redirects_without_canvas_token(settings, tmp_path):
    def api(request):
        assert request.headers["Authorization"] == f"Bearer {settings.api_token}"
        return httpx.Response(200, json={"id": 10, "url": "https://storage.example.test/signed"})

    calls = []

    def storage(request):
        calls.append(request)
        assert "Authorization" not in request.headers
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "https://cdn.example.test/signed"})
        return httpx.Response(200, content=b"actual attachment")

    client = CanvasClient(settings, transport=httpx.MockTransport(api))
    try:
        output = tmp_path / "attachment.bin"
        result = await CanvasTransfers(
            client, transport=httpx.MockTransport(storage)
        ).download_file(10, str(output))
        assert result["bytes"] == 17
        assert output.read_bytes() == b"actual attachment"
        assert output.stat().st_mode & 0o777 == 0o600
        assert len(calls) == 2
        assert len(list(tmp_path.iterdir())) == 1
    finally:
        await client.close()


async def test_pre_attachment_upload_keeps_initial_job_and_completes_file(settings, tmp_path):
    source = tmp_path / "course.zip"
    source.write_bytes(b"zip data")
    calls = []

    def api(request):
        calls.append(request)
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload["migration_type"] == "canvas_cartridge_importer"
        assert payload["pre_attachment"] == {
            "name": "course.zip",
            "size": 8,
            "content_type": "application/zip",
        }
        return httpx.Response(
            201,
            json={
                "id": 7,
                "workflow_state": "pre_processing",
                "pre_attachment": {
                    "upload_url": "https://storage.example.test/upload",
                    "upload_params": {},
                },
            },
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(api))
    try:
        transfers = CanvasTransfers(
            client,
            transport=httpx.MockTransport(lambda request: httpx.Response(201, json={"id": 88})),
        )
        result = await transfers.upload(
            "content_migrations.create_content_migration_courses",
            str(source),
            {"course_id": 1},
            {"migration_type": "canvas_cartridge_importer"},
            pre_attachment=True,
        )
        assert result["file_id"] == 88
        assert result["pre_attachment"] is True
        assert len(calls) == 1
    finally:
        await client.close()


async def test_failed_download_leaves_no_partial_file(settings, tmp_path):
    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"incomplete"
            raise httpx.ReadError("private network error")

    def api(request):
        return httpx.Response(200, json={"url": "https://storage.example.test/file"})

    client = CanvasClient(settings, transport=httpx.MockTransport(api))
    try:
        transfers = CanvasTransfers(
            client,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Interrupted())
            ),
        )
        with pytest.raises(CanvasError, match="interrupted"):
            await transfers.download_file(1, str(tmp_path / "file.bin"))
        assert list(tmp_path.iterdir()) == []
    finally:
        await client.close()
