import httpx
import pytest

from canvas_mcp.client import CanvasClient, CanvasError


async def test_pagination_follows_opaque_link_and_only_gets(settings):
    seen = []

    def handle(request):
        assert request.method == "GET"
        assert request.headers["Authorization"] == f"Bearer {settings.api_token}"
        seen.append(request)
        if len(seen) == 1:
            assert request.url.params["per_page"] == "100"
            assert request.url.params["include[]"] == "submission"
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers={
                    "Link": "<https://canvas.example.test/api/v1/courses/286470/assignments"
                    '?cursor=opaque>; rel="next"'
                },
            )
        assert dict(request.url.params) == {"cursor": "opaque"}
        return httpx.Response(200, json=[{"id": 2}])

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = await client.list("courses/286470/assignments", {"include[]": "submission"})
        assert result == [{"id": 1}, {"id": 2}]
        assert len(seen) == 2
    finally:
        await client.close()


@pytest.mark.parametrize(
    "target",
    [
        "https://attacker.test/api/v1/courses",
        "http://canvas.example.test/api/v1/courses",
        "https://canvas.example.test/login",
        "https://user:pass@canvas.example.test/api/v1/courses",
        "https://canvas.example.test/api/v1/courses/%2e%2e/users",
        "https://canvas.example.test/api/v1/courses/%252e%252e/users",
    ],
)
async def test_unsafe_pagination_never_sends_token_to_next_url(settings, target):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=[{"id": 1}], headers={"Link": f'<{target}>; rel="next"'})

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CanvasError, match="outside the configured API"):
            await client.list("courses")
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
async def test_http_errors_do_not_return_sensitive_response_body(settings, status):
    def handle(request):
        return httpx.Response(
            status,
            text=f"secret={settings.api_token}",
            headers={"Location": "https://attacker.test"},
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CanvasError) as error:
            await client.get("users/self/profile")
        assert settings.api_token not in str(error.value)
        assert "attacker.test" not in str(error.value)
    finally:
        await client.close()


async def test_rate_limit_retries_are_bounded(settings, monkeypatch):
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("canvas_mcp.client.asyncio.sleep", sleep)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "500"})

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CanvasError, match="429"):
            await client.get("courses/1")
        assert len(calls) == 3
        assert delays == [10.0, 10.0]
    finally:
        await client.close()


async def test_cyclic_pagination_fails_instead_of_returning_partial_data(settings):
    def handle(request):
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": '<https://canvas.example.test/api/v1/courses>; rel="next"'},
        )

    client = CanvasClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CanvasError, match="cycle"):
            await client.list("courses")
    finally:
        await client.close()


async def test_invalid_json_is_a_redacted_failure(settings):
    client = CanvasClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=settings.api_token)),
    )
    try:
        with pytest.raises(CanvasError, match="non-JSON") as error:
            await client.get("courses/1")
        assert settings.api_token not in str(error.value)
    finally:
        await client.close()
