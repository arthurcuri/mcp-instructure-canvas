import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "configure_github", Path(__file__).parents[1] / "automation/configure_github.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_credentials_go_only_to_stdin_and_activation_is_explicit(tmp_path, monkeypatch):
    for name in ("CANVAS_API_TOKEN", "CANVAS_API_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "CANVAS_API_URL=https://canvas.example.test/api/v1\nCANVAS_API_TOKEN=canvas-private-secret\n"
        "TELEGRAM_BOT_TOKEN=12345:telegram-private-secret\nTELEGRAM_CHAT_ID=123\n"
    )
    calls = []
    monkeypatch.setattr(module, "github", lambda args, value=None: calls.append((args, value)))
    result = module.configure("owner/repo", env, False)
    assert result["daily_enabled"] is False
    assert len(calls) == 5
    assert calls[0][1] == "canvas-private-secret"
    assert calls[1][1] == "12345:telegram-private-secret"
    assert all("private-secret" not in str(args) for args, _ in calls)
    assert not any("CANVAS_DAILY_ENABLED" in args for args, _ in calls)
    calls.clear()
    module.configure("owner/repo", env, True)
    assert calls[-1][0][-3:] == ["owner/repo", "--body", "true"]
    assert "CANVAS_WEEKLY_ENABLED" in calls[-2][0]
    assert calls[-2][0][-1] == "false"


def test_invalid_configuration_makes_no_github_mutations(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "github", lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        module.configure("owner/repo;echo bad", tmp_path / ".env", True)
    assert not calls
