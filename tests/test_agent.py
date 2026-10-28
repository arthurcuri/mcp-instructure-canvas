import json

import pytest

from canvas_mcp.agent import AgentError, AgentManager


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in (
        "CANVAS_API_TOKEN",
        "CANVAS_API_URL",
        "CANVAS_DEFAULT_COURSE_ID",
        "CANVAS_READ_ONLY",
        "CANVAS_TIMEZONE",
        "CANVAS_TOKEN_EXPIRES_AT",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "CANVAS_API_URL=https://canvas.example.test\nCANVAS_API_TOKEN=canvas-private-secret\n"
        "TELEGRAM_BOT_TOKEN=12345:telegram-private-secret\nTELEGRAM_CHAT_ID=123\n"
    )
    server = tmp_path / ".venv/bin/canvas-mcp-server"
    server.parent.mkdir(parents=True)
    server.touch()
    prompt = tmp_path / "automation/agent_instructions.md"
    prompt.parent.mkdir()
    prompt.write_text("Use Canvas and reply to the requesting user.")
    return tmp_path


def test_private_preparation_allowlists_only_the_owner_and_never_copies_credentials(project):
    result = AgentManager(project).prepare()
    assert result["canvas_credentials_copied"] is False
    directory = project / ".local/agent"
    access = json.loads((directory / "telegram/access.json").read_text())
    assert access["dmPolicy"] == "allowlist"
    assert access["allowFrom"] == ["123"]
    assert access["groups"] == {}
    for file in directory.rglob("*.json"):
        assert file.stat().st_mode & 0o777 == 0o600
        assert "canvas-private-secret" not in file.read_text()
        assert "telegram-private-secret" not in file.read_text()
    config = json.loads((directory / "mcp.json").read_text())
    assert config["mcpServers"]["canvas-pucminas"]["args"] == ["--env-file", str(project / ".env")]
    settings = json.loads((directory / "settings.json").read_text())
    assert settings["permissions"]["defaultMode"] == "manual"
    assert not any(
        "canvas_api_write" in rule or "submit_assignment" in rule
        for rule in settings["permissions"]["allow"]
    )
    assert "Read(./.env)" in settings["permissions"]["deny"]
    runtime = directory / "telegram/.env"
    assert runtime.stat().st_mode & 0o777 == 0o600
    assert runtime.read_text() == "TELEGRAM_BOT_TOKEN=12345:telegram-private-secret\n"
    assert settings["env"]["TELEGRAM_ACCESS_MODE"] == "static"


def test_agent_environment_uses_subscription_and_passes_bot_token_only_in_environment(
    project, monkeypatch
):
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_PROFILE",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CANVAS_API_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
    ):
        monkeypatch.setenv(name, "unwanted-provider-value")
    # The Canvas credential used by the MCP will come from its explicit env file.
    environment = AgentManager(project).environment()
    assert environment["TELEGRAM_BOT_TOKEN"] == "12345:telegram-private-secret"
    assert environment["TELEGRAM_ACCESS_MODE"] == "static"
    assert environment["TELEGRAM_STATE_DIR"] == str(project / ".local/agent/telegram")
    assert not any(
        name in environment
        for name in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "CANVAS_API_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
        )
    )


def test_background_start_uses_official_channels_normal_permissions_and_no_initial_task(
    project, monkeypatch
):
    manager = AgentManager(project)
    calls = []
    monkeypatch.setattr("canvas_mcp.agent.shutil.which", lambda name: "/usr/bin/" + name)

    def call(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if arguments == ["auth", "status"]:
            return json.dumps(
                {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "team"}
            )
        return "backgrounded · abcd1234 · Canvas Telegram"

    monkeypatch.setattr(manager, "call", call)
    result = manager.start()
    assert result["started"] is True
    arguments, options = calls[-1]
    assert "--bg" in arguments and "--channels" in arguments
    assert "plugin:telegram@claude-plugins-official" in arguments
    assert "--bare" not in arguments and "--dangerously-skip-permissions" not in arguments
    assert arguments[arguments.index("--permission-mode") + 1] == "manual"
    assert all("private-secret" not in value for value in arguments)
    assert options["environment"]["TELEGRAM_BOT_TOKEN"] == "12345:telegram-private-secret"
    assert manager.state()["session_id"] == result["session_id"]


def test_start_does_not_duplicate_a_running_session(project, monkeypatch):
    manager = AgentManager(project)
    manager.directory.mkdir(parents=True)
    manager.state_file.write_text('{"session_id":"existing"}')
    monkeypatch.setattr(manager, "authentication", lambda: {"authMethod": "claude.ai"})
    monkeypatch.setattr("canvas_mcp.agent.shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(manager, "current", lambda: {"id": "short", "pid": 42, "status": "idle"})
    assert manager.start() == {"started": False, "already_running": True, "session_id": "existing"}


def test_api_authentication_is_rejected_before_agent_launch(project, monkeypatch):
    manager = AgentManager(project)
    monkeypatch.setattr(manager, "call", lambda args: '{"loggedIn":true,"authMethod":"api_key"}')
    with pytest.raises(AgentError, match="subscription"):
        manager.start()
    assert not manager.state_file.exists()


def test_stop_only_targets_our_registered_session(project, monkeypatch):
    manager = AgentManager(project)
    monkeypatch.setattr(manager, "current", lambda: {"id": "own-session", "sessionId": "uuid"})
    calls = []
    monkeypatch.setattr(manager, "call", lambda arguments: calls.append(arguments))
    assert manager.stop()["stopped"]
    assert calls == [["stop", "own-session"]]


def test_stopped_session_does_not_require_a_log_file(project, monkeypatch):
    manager = AgentManager(project)
    monkeypatch.setattr(manager, "current", lambda: {"id": "short", "state": "stopped"})
    calls = []
    monkeypatch.setattr(manager, "call", lambda arguments: calls.append(arguments))
    result = manager.status()
    assert result["channel_registration"] == "stopped"
    assert result["state"] == "stopped"
    assert not calls
