import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from canvas_mcp.client import CanvasClient
from canvas_mcp.weekly import main


@pytest.fixture
def private_configuration(tmp_path, monkeypatch):
    for name in (
        "CANVAS_API_URL",
        "CANVAS_API_TOKEN",
        "CANVAS_TOKEN_EXPIRES_AT",
        "CANVAS_DEFAULT_COURSE_ID",
        "CANVAS_TIMEZONE",
    ):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "CANVAS_API_URL=https://canvas.example.test\n"
        "CANVAS_API_TOKEN=private-test-secret\n"
        "CANVAS_DEFAULT_COURSE_ID=1\n"
        "CANVAS_TOKEN_EXPIRES_AT=2030-06-30\n",
        encoding="utf-8",
    )
    return path


def test_weekly_cli_saves_private_snapshot_without_credentials_or_personal_notes(
    private_configuration, tmp_path, monkeypatch, capsys
):
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    def handle(request):
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[{"id": 1, "course_id": 1, "name": "Private assignment", "due_at": due}],
        )

    monkeypatch.setattr(
        "canvas_mcp.weekly.CanvasClient",
        lambda settings: CanvasClient(settings, transport=httpx.MockTransport(handle)),
    )
    output = tmp_path / ".local/weekly-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["canvas-weekly-check", "--env-file", str(private_configuration), "--output", str(output)],
    )
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["count"] == 1
    assert report["courses_checked"] == [1]
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert len(list(output.parent.iterdir())) == 1
    captured = capsys.readouterr()
    assert "Private assignment" not in captured.out
    for value in ("private-test-secret", "2030-06-30"):
        assert value not in output.read_text()
        assert value not in captured.out + captured.err


def test_failed_weekly_query_preserves_previous_snapshot_and_reports_a_safe_error(
    private_configuration, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        "canvas_mcp.weekly.CanvasClient",
        lambda settings: CanvasClient(
            settings,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, text=settings.api_token)
            ),
        ),
    )
    output = tmp_path / "previous-report.json"
    output.write_text('{"checked_at":"previous-run"}\n')
    monkeypatch.setattr(
        sys,
        "argv",
        ["canvas-weekly-check", "--env-file", str(private_configuration), "--output", str(output)],
    )
    assert main() == 1
    assert output.read_text() == '{"checked_at":"previous-run"}\n'
    captured = capsys.readouterr()
    assert "permissão" in captured.err
    assert "private-test-secret" not in captured.err
    assert not captured.out


def test_weekly_scope_conflict_is_rejected_before_query(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["canvas-weekly-check", "--course-id", "1", "--all-courses"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_launcher_handles_another_cwd_and_project_paths_with_spaces(tmp_path):
    project = tmp_path / "project with spaces"
    directory = project / "automation"
    directory.mkdir(parents=True)
    original = Path(__file__).resolve().parents[1] / "automation/run_weekly.sh"
    launcher = directory / "run_weekly.sh"
    launcher.write_bytes(original.read_bytes())
    capture = tmp_path / "captured-arguments.txt"
    fake_uv = tmp_path / "fake uv"
    fake_uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CANVAS_TEST_CAPTURE"\n')
    fake_uv.chmod(0o700)
    environment = {
        **os.environ,
        "CANVAS_UV_BIN": str(fake_uv),
        "CANVAS_TEST_CAPTURE": str(capture),
    }
    subprocess.run(
        ["/bin/bash", str(launcher), "--all-courses"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
    )
    arguments = capture.read_text().splitlines()
    assert arguments[arguments.index("--directory") + 1] == str(project)
    assert arguments[arguments.index("--env-file") + 1] == str(project / ".env")
    assert arguments[arguments.index("--output") + 1] == str(project / ".local/weekly-report.json")
    assert "--all-courses" in arguments
    assert project.joinpath(".local").stat().st_mode & 0o777 == 0o700
