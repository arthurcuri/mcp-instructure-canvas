from datetime import date

import pytest

from canvas_mcp.config import ConfigurationError, Settings


@pytest.fixture(autouse=True)
def clean_canvas_environment(monkeypatch):
    for name in (
        "CANVAS_API_URL",
        "CANVAS_API_TOKEN",
        "CANVAS_TOKEN_EXPIRES_AT",
        "CANVAS_DEFAULT_COURSE_ID",
        "CANVAS_TIMEZONE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_explicit_env_works_outside_repository_without_revealing_token(tmp_path, monkeypatch):
    path = tmp_path / "config.env"
    path.write_text(
        "CANVAS_API_URL=https://canvas.example.test\n"
        "CANVAS_API_TOKEN=test-secret\n"
        "CANVAS_TOKEN_EXPIRES_AT=2030-06-30\n"
        "CANVAS_DEFAULT_COURSE_ID=286470\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path.parent)
    settings = Settings.load(path)
    assert settings.api_url == "https://canvas.example.test/api/v1"
    assert settings.token_expires_at == date(2030, 6, 30)
    assert settings.default_course_id == 286470
    assert "test-secret" not in repr(settings)
    assert "test-secret" not in str(settings.public_info())


@pytest.mark.parametrize(
    "url",
    [
        "http://canvas.example.test",
        "https://user:password@canvas.example.test",
        "https://canvas.example.test/api/v1?token=secret",
        "https://canvas.example.test/courses/1",
        "https://canvas.example.test:bad",
    ],
)
def test_invalid_canvas_url_is_rejected_without_echoing_input(tmp_path, url):
    path = tmp_path / "config.env"
    path.write_text(f"CANVAS_API_URL={url}\nCANVAS_API_TOKEN=test-secret\n")
    with pytest.raises(ConfigurationError) as error:
        Settings.load(path)
    assert "secret" not in str(error.value)
    assert "password" not in str(error.value)


def test_missing_token_and_missing_explicit_file_fail(tmp_path):
    path = tmp_path / "config.env"
    with pytest.raises(ConfigurationError, match="não existe"):
        Settings.load(path)
    path.write_text("CANVAS_API_URL=https://canvas.example.test\n")
    with pytest.raises(ConfigurationError, match="CANVAS_API_TOKEN"):
        Settings.load(path)


def test_process_environment_takes_precedence(tmp_path, monkeypatch):
    path = tmp_path / "config.env"
    path.write_text("CANVAS_API_URL=https://canvas.example.test\nCANVAS_API_TOKEN=old\n")
    monkeypatch.setenv("CANVAS_API_TOKEN", "new")
    assert Settings.load(path).api_token == "new"
