import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from canvas_mcp.agent import main
from canvas_mcp.agent_setup import (
    codex_identity,
    identity,
    login,
    resolve_provider,
    selected_provider,
    setup,
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    for key in (
        "CANVAS_AGENT_PROVIDER",
        "CANVAS_AGENT_AUTO",
        "CANVAS_API_URL",
        "CANVAS_API_TOKEN",
        "CANVAS_READ_ONLY",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_BOT_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# My private note\nCANVAS_API_URL=https://canvas.example.test/api/v1\n"
        "CANVAS_API_TOKEN=synthetic-canvas\nTELEGRAM_BOT_TOKEN=123:synthetic-telegram\n"
        "TELEGRAM_CHAT_ID=123\nCANVAS_AGENT_AUTO=false\n"
    )
    monkeypatch.setattr("canvas_mcp.agent_setup.interactive_terminal", lambda: True)
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "canvas_mcp.agent_setup.identity",
        lambda *args: {
            "email": "student@example.test",
            "plan": "team",
        },
    )
    monkeypatch.setattr(
        "canvas_mcp.agent_setup.overview",
        lambda *args: {
            "selected_provider": None,
            "automatic": False,
            "providers": {"codex": {"running": False}, "claude": {"running": False}},
        },
    )
    return tmp_path


def answers(monkeypatch, values):
    iterator = iter(values)
    monkeypatch.setattr("builtins.input", lambda *args: next(iterator))


def test_no_provider_is_implicitly_chosen_and_explicit_flag_is_not_persisted(project):
    env = project / ".env"
    assert selected_provider(env) is None
    with pytest.raises(ValueError, match="setup"):
        resolve_provider(None, env)
    assert resolve_provider("claude", env) == "claude"
    assert selected_provider(env) is None
    env.write_text(env.read_text() + "CANVAS_AGENT_PROVIDER=codex\n")
    assert resolve_provider(None, env) == "codex"
    assert resolve_provider("claude", env) == "claude"
    assert selected_provider(env) == "codex"


def test_cancel_never_saves_or_activates_and_does_not_accept_cached_account_implicitly(
    project, monkeypatch, capsys
):
    env = project / ".env"
    before = env.read_bytes()
    control = Mock()
    native_login = Mock()
    monkeypatch.setattr("canvas_mcp.agent.control", control)
    monkeypatch.setattr("canvas_mcp.agent_setup.login", native_login)
    # Choose Codex, explicitly use the shown account, manual mode, then cancel review.
    answers(monkeypatch, ["1", "1", "1", "0"])
    assert setup(project, env) == {"cancelled": True}
    assert env.read_bytes() == before
    control.assert_not_called()
    native_login.assert_not_called()
    output = capsys.readouterr().out
    assert "student@example.test" in output and "Review" in output
    assert "synthetic-canvas" not in output and "synthetic-telegram" not in output


def test_save_only_preserves_tokens_notes_and_running_provider(project, monkeypatch):
    env = project / ".env"
    control = Mock()
    monkeypatch.setattr("canvas_mcp.agent.control", control)
    monkeypatch.setattr(
        "canvas_mcp.agent_setup.overview",
        lambda *args: {
            "selected_provider": "codex",
            "automatic": False,
            "providers": {"codex": {"running": True}, "claude": {"running": False}},
        },
    )
    answers(monkeypatch, ["2", "1", "1", "2"])
    result = setup(project, env)
    assert result["provider"] == "claude" and not result["started"]
    assert selected_provider(env) == "claude"
    assert "# My private note\n" in env.read_text()
    assert "CANVAS_API_TOKEN=synthetic-canvas\n" in env.read_text()
    assert env.stat().st_mode & 0o777 == 0o600
    control.assert_not_called()


def test_switch_stops_old_provider_only_after_final_review(project, monkeypatch, capsys):
    env = project / ".env"
    monkeypatch.setattr(
        "canvas_mcp.agent_setup.overview",
        lambda *args: {
            "selected_provider": "codex",
            "automatic": False,
            "providers": {"codex": {"running": True}, "claude": {"running": False}},
        },
    )
    calls = []

    def control(action, provider, *args):
        assert "Review" in capsys.readouterr().out if not calls else True
        assert selected_provider(env) == "claude"
        calls.append((action, provider))
        return {"started": action == "start"}

    monkeypatch.setattr("canvas_mcp.agent.control", control)
    answers(monkeypatch, ["2", "1", "1", "1"])
    setup(project, env)
    assert calls == [("stop", "codex"), ("start", "claude")]


def test_automatic_requires_explicit_choice_and_read_only_conflict_saves_nothing(
    project, monkeypatch
):
    env = project / ".env"
    env.write_text(env.read_text() + "CANVAS_READ_ONLY=true\n")
    before = env.read_bytes()
    control = Mock()
    monkeypatch.setattr("canvas_mcp.agent.control", control)
    answers(monkeypatch, ["1", "1", "2"])
    with pytest.raises(ValueError, match="CANVAS_READ_ONLY=false"):
        setup(project, env)
    assert env.read_bytes() == before
    control.assert_not_called()


def test_enter_defaults_to_manual_and_cancels_final_review(project, monkeypatch):
    env = project / ".env"
    before = env.read_bytes()
    answers(monkeypatch, ["1", "1", "", ""])
    assert setup(project, env)["cancelled"]
    assert env.read_bytes() == before


def test_no_login_is_opened_without_choosing_it(project, monkeypatch):
    monkeypatch.setattr("canvas_mcp.agent_setup.identity", lambda *args: None)
    native_login = Mock()
    monkeypatch.setattr("canvas_mcp.agent_setup.login", native_login)
    answers(monkeypatch, ["1", "0"])
    assert setup(project, project / ".env")["cancelled"]
    native_login.assert_not_called()


def test_new_login_is_explicit_and_cancel_keeps_bot_configuration_untouched(project, monkeypatch):
    env = project / ".env"
    before = env.read_bytes()
    native_login = Mock()
    monkeypatch.setattr("canvas_mcp.agent_setup.login", native_login)
    answers(monkeypatch, ["1", "2", "1", "0"])
    assert setup(project, env)["cancelled"]
    native_login.assert_called_once_with("codex", project)
    assert env.read_bytes() == before


def test_noninteractive_setup_does_not_read_credentials_or_launch_login(project, monkeypatch):
    monkeypatch.setattr("canvas_mcp.agent_setup.interactive_terminal", lambda: False)
    probe = Mock()
    monkeypatch.setattr("canvas_mcp.agent_setup.identity", probe)
    with pytest.raises(ValueError, match="interactive terminal"):
        setup(project, project / "missing.env")
    probe.assert_not_called()


def test_claude_native_login_uses_browser_subscription_and_never_starts_agent(project, monkeypatch):
    captured = {}
    monkeypatch.setattr("canvas_mcp.agent_setup.shutil.which", lambda *args: "/bin/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-use-paid-api")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "do-not-forward")

    def run(arguments, **kwargs):
        captured.update(arguments=arguments, **kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("canvas_mcp.agent_setup.subprocess.run", run)
    result = login("claude", project)
    assert captured["arguments"] == ["/bin/claude", "auth", "login", "--claudeai"]
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert "TELEGRAM_BOT_TOKEN" not in captured["env"]
    assert not result["started"]


def test_claude_identity_discards_credentials_and_unrelated_fields(project, monkeypatch):
    monkeypatch.setattr("canvas_mcp.agent_setup.shutil.which", lambda *args: "/bin/claude")
    monkeypatch.setattr(
        "canvas_mcp.agent_setup.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "email": "user@example.test",
                    "subscriptionType": "pro",
                    "accessToken": "must-not-leak",
                }
            ),
        ),
    )
    assert identity("claude", project) == {"email": "user@example.test", "plan": "pro"}


def test_cli_start_uses_saved_choice_and_no_choice_fails_before_control(
    project, monkeypatch, capsys
):
    env = project / ".env"
    control = Mock(return_value={"started": True})
    monkeypatch.setattr("canvas_mcp.agent.control", control)
    monkeypatch.setattr("sys.argv", ["canvas-agent", "start", "--project-dir", str(project)])
    assert main() == 1
    control.assert_not_called()
    assert "setup" in capsys.readouterr().err
    env.write_text(env.read_text() + "CANVAS_AGENT_PROVIDER=claude\n")
    assert main() == 0
    control.assert_called_once_with("start", "claude", project, env)


def test_cli_status_reports_both_providers_without_selecting_one(project, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["canvas-agent", "status", "--project-dir", str(project)])
    assert main() == 0
    output = capsys.readouterr().out
    assert "Codex / ChatGPT: stopped" in output and "Claude Code / Claude: stopped" in output
    assert selected_provider(project / ".env") is None


async def test_codex_identity_has_no_mcp_or_turn_and_retains_only_account_metadata(
    project, monkeypatch
):
    rpc = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
        request=AsyncMock(
            return_value={
                "account": {
                    "type": "chatgpt",
                    "email": "student@example.test",
                    "planType": "team",
                    "accessToken": "must-not-leak",
                }
            }
        ),
    )
    create = Mock(return_value=rpc)
    monkeypatch.setattr("canvas_mcp.agent_setup.CodexRPC", create)
    account = await codex_identity("/bin/codex", project)
    assert account == {"email": "student@example.test", "plan": "team"}
    assert "mcp_servers={}" in create.call_args.args[2]
    rpc.request.assert_awaited_once_with("account/read", {"refreshToken": False})
    rpc.close.assert_awaited_once()


def test_unknown_receiver_prevents_activation_before_saving_or_stopping(project, monkeypatch):
    env = project / ".env"
    before = env.read_bytes()
    monkeypatch.setattr(
        "canvas_mcp.agent_setup.overview",
        lambda *args: {
            "selected_provider": None,
            "automatic": False,
            "providers": {"codex": {"running": False}, "claude": {"running": None}},
        },
    )
    control = Mock()
    monkeypatch.setattr("canvas_mcp.agent.control", control)
    answers(monkeypatch, ["1", "1", "1", "1"])
    with pytest.raises(ValueError, match="check all"):
        setup(project, env)
    assert env.read_bytes() == before
    control.assert_not_called()


def test_automatic_opt_in_is_saved_only_after_review_without_starting(project, monkeypatch):
    env = project / ".env"
    control = Mock()
    monkeypatch.setattr("canvas_mcp.agent.control", control)
    answers(monkeypatch, ["1", "1", "2", "2"])
    result = setup(project, env)
    assert result["automatic"] and not result["started"]
    assert "CANVAS_AGENT_AUTO=true\n" in env.read_text()
    control.assert_not_called()
