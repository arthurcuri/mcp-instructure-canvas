import json
import plistlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from canvas_mcp.agent_auto import AutoRunner, schedule
from canvas_mcp.agent_policy import AgentPolicy


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in (
        "CANVAS_AGENT_AUTO",
        "CANVAS_READ_ONLY",
        "CANVAS_API_URL",
        "CANVAS_API_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "CANVAS_API_URL=https://canvas.example.test/api/v1\nCANVAS_API_TOKEN=synthetic-canvas\n"
        "TELEGRAM_BOT_TOKEN=12345:synthetic-telegram\nTELEGRAM_CHAT_ID=123\n"
    )
    prompt = tmp_path / "automation/agent_instructions.md"
    prompt.parent.mkdir()
    prompt.write_text("Keep coursework facts accurate and use Canvas.")
    return tmp_path


@pytest.mark.parametrize("value,expected", [("false", False), ("true", True), ("TRUE", True)])
def test_boolean_policy_is_explicit(project, value, expected):
    env = project / ".env"
    env.write_text(env.read_text() + "CANVAS_AGENT_AUTO=" + value + "\n")
    assert AgentPolicy.load(env).automatic is expected


def test_invalid_boolean_never_silently_enables_automatic_delivery(project):
    (project / ".env").write_text("CANVAS_AGENT_AUTO=yes\n")
    with pytest.raises(ValueError, match="true ou false"):
        AgentPolicy.load(project / ".env")


async def test_default_false_makes_no_canvas_or_model_calls(project, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No external call is authorized")

    monkeypatch.setattr("canvas_mcp.agent_auto.CanvasClient", forbidden)
    monkeypatch.setattr("canvas_mcp.agent_auto.TelegramClient", forbidden)
    result = await AutoRunner(project, project / ".env", "codex").run()
    assert result == {"automatic": False, "processed": 0}


async def test_automatic_read_only_conflict_fails_before_external_calls(project, monkeypatch):
    env = project / ".env"
    env.write_text(env.read_text() + "CANVAS_AGENT_AUTO=true\nCANVAS_READ_ONLY=true\n")
    client = AsyncMock()
    monkeypatch.setattr("canvas_mcp.agent_auto.CanvasClient", lambda *args: client)
    with pytest.raises(ValueError, match="CANVAS_READ_ONLY=false"):
        await AutoRunner(project, env, "codex").run()
    client.assert_not_called()


@pytest.mark.parametrize("confirmed", [False, True])
async def test_submission_is_verified_independently_and_claims_prevent_duplicates(
    project, monkeypatch, confirmed
):
    env = project / ".env"
    env.write_text(env.read_text() + "CANVAS_AGENT_AUTO=true\n")
    task = {
        "id": 8,
        "course_id": 7,
        "key": "7/8",
        "completed": False,
        "submission_types": ["online_upload"],
        "due_at": None,
    }
    service = AsyncMock()
    service.settings = SimpleNamespace(timezone="America/Sao_Paulo")
    service.list_courses.return_value = {"courses": [{"id": 7}]}
    service.list_assignments.return_value = {"assignments": [task]}
    service.get_assignment.side_effect = [
        task,
        {
            "completed": confirmed,
            "submitted_at": "2030-01-01T12:00:00Z" if confirmed else None,
            "submission_status": "submitted" if confirmed else "unsubmitted",
        },
    ]
    monkeypatch.setattr("canvas_mcp.agent_auto.CanvasService", lambda *args: service)
    client = AsyncMock()
    monkeypatch.setattr("canvas_mcp.agent_auto.CanvasClient", lambda *args: client)
    telegram = AsyncMock()
    telegram.settings = SimpleNamespace(chat_id="123")
    monkeypatch.setattr("canvas_mcp.agent_auto.TelegramClient", lambda *args: telegram)
    runner = AutoRunner(project, env, "codex")

    async def solve(candidate):
        ledger = json.loads(runner.ledger_path.read_text())
        assert ledger["7/8"]["status"] == "claimed"
        assert candidate["id"] == 8

    worker = AsyncMock(side_effect=solve)
    monkeypatch.setattr(runner, "codex", worker)
    result = await runner.run()
    assert result["submitted"] == int(confirmed)
    assert runner.ledger["7/8"]["status"] == ("submitted" if confirmed else "needs_attention")
    assert runner.ledger_path.stat().st_mode & 0o777 == 0o600
    result = await runner.run()
    assert result["processed"] == 0
    worker.assert_awaited_once()


async def test_scanner_excludes_submitted_locked_external_and_quiz_work(project):
    runner = AutoRunner(project, project / ".env", "codex")
    service = AsyncMock()
    service.settings = SimpleNamespace(timezone="America/Sao_Paulo")
    service.list_courses.return_value = {"courses": [{"id": 1}]}
    base = {
        "course_id": 1,
        "completed": False,
        "due_at": None,
        "submission_types": ["online_text_entry"],
    }
    service.list_assignments.return_value = {
        "assignments": [
            {**base, "id": 1, "completed": True},
            {**base, "id": 2, "submission_types": ["online_quiz"]},
            {**base, "id": 3, "submission_types": ["external_tool"]},
            {**base, "id": 4},
            {**base, "id": 5},
        ]
    }
    service.get_assignment.side_effect = [
        {**base, "id": 4, "locked_for_user": True},
        {**base, "id": 5},
    ]
    tasks, skipped = await runner.candidates(service)
    assert [task["id"] for task in tasks] == [5]
    assert skipped == 3


def test_local_schedule_contains_no_secrets_and_false_removes_only_its_job(project, monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    env = project / ".env"
    env.write_text(env.read_text() + "CANVAS_AGENT_AUTO=true\n")
    calls = []
    manager = SimpleNamespace(
        label="com.canvas-mcp.codex-fixture",
        runtime=project,
        plist=project / "LaunchAgents/receiver.plist",
        launchctl=lambda args, **kwargs: calls.append(args),
    )
    result = schedule(manager, "codex", env)
    assert result["scheduled"]
    path = manager.plist.with_name("com.canvas-mcp.auto-fixture.plist")
    data = plistlib.loads(path.read_bytes())
    assert data["StartCalendarInterval"] == {"Hour": 8, "Minute": 0}
    assert "auto-run" in data["ProgramArguments"]
    assert "synthetic" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    env.write_text(env.read_text().replace("CANVAS_AGENT_AUTO=true", "CANVAS_AGENT_AUTO=false"))
    assert not schedule(manager, "codex", env)["scheduled"]
    assert not path.exists()
    assert all("com.canvas-mcp.codex-fixture" not in str(call) for call in calls)


def test_automatic_authorization_is_scoped_to_trusted_scheduled_work(project):
    with pytest.raises(ValueError, match="desativado"):
        AgentPolicy(False).instructions(project, automated_task=True)
    prompt = AgentPolicy(True).instructions(project, automated_task=True)
    assert "standing authorization" in prompt and "specific assignment" in prompt
    assert "never invent" in prompt
    assert "interactive conversation" in AgentPolicy(True).instructions(project)


async def test_claude_automatic_worker_uses_subscription_without_channels_or_permission_bypass(
    project, monkeypatch
):
    env = project / ".env"
    env.write_text(env.read_text() + "CANVAS_AGENT_AUTO=true\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unwanted-paid-api-key")
    monkeypatch.setattr("canvas_mcp.agent.shutil.which", lambda name: "/bin/claude")
    monkeypatch.setattr(
        "canvas_mcp.agent.AgentManager.authentication", lambda self: {"authMethod": "claude.ai"}
    )
    captured = {}
    process = SimpleNamespace(returncode=0)
    process.communicate = AsyncMock(return_value=(b'{"is_error":false,"result":"Done"}', None))

    async def create(*args, **kwargs):
        captured.update(arguments=args, options=kwargs)
        return process

    monkeypatch.setattr("canvas_mcp.agent_auto.asyncio.create_subprocess_exec", create)
    telegram = AsyncMock()
    telegram.settings = SimpleNamespace(token="12345:synthetic-telegram", chat_id="123")
    runner = AutoRunner(project, env, "claude")
    await runner.claude({"course_id": 7, "id": 8}, telegram)
    arguments = captured["arguments"]
    assert "-p" in arguments and "--strict-mcp-config" in arguments
    assert "--channels" not in arguments
    assert "--bare" not in arguments and "--dangerously-skip-permissions" not in arguments
    assert arguments[arguments.index("--permission-prompts") + 1] == "none"
    assert "ANTHROPIC_API_KEY" not in captured["options"]["env"]
    assert "TELEGRAM_BOT_TOKEN" not in captured["options"]["env"]
    settings = json.loads((runner.directory / "claude-settings.json").read_text())
    assert settings["enabledPlugins"]["telegram@claude-plugins-official"] is False
    assert "mcp__canvas-pucminas__submit_assignment" in settings["permissions"]["allow"]
    assert not any("Bash" in rule for rule in settings["permissions"]["allow"])
