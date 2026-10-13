import pytest

from canvas_mcp.config import Settings


@pytest.fixture
def settings():
    return Settings(
        api_url="https://canvas.example.test/api/v1",
        api_token="test-secret-never-print",
        default_course_id=286470,
    )
