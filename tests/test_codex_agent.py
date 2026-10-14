import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from canvas_mcp.agent_runtime import CodexManager
from canvas_mcp.codex_agent import CodexBridge
from canvas_mcp.codex_rpc import CodexError, CodexRPC
from canvas_mcp.notifications import TelegramError


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    for name in ("CANVAS_API_TOKEN", "CANVAS_API_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "CANVAS_API_URL=https://canvas.example.test/api/v1\nCANVAS_API_TOKEN=canvas-private-secret\n"
        "TELEGRAM_BOT_TOKEN=12345:telegram-private-secret\nTELEGRAM_CHAT_ID=123\n"
    )
    binary = tmp_path / ".venv/bin/canvas-mcp-server"
    binary.parent.mkdir(parents=True)
    binary.touch()
    prompt = tmp_path / "automation/agent_instructions.md"
    prompt.parent.mkdir()
    prompt.write_text("Wait for the user; only deliver coursework when explicitly asked.")
    instance = CodexBridge(tmp_path, tmp_path / ".env", "/bin/codex")
    instance.rpc = AsyncMock()
    instance.telegram = AsyncMock()
    instance.telegram._call.return_value = {"message_id": 1}
    return instance


def message(text, *, owner=123, sender=123, kind="private"):
    return {"chat": {"id": owner, "type": kind}, "from": {"id": sender}, "text": text}


@pytest.mark.parametrize(
    "text", ["/start", "/help", "/status", "/reset", "/cancel", "/unknown", ""]
)
async def test_control_commands_never_start_inference(bridge, text):
    await bridge.handle_message(message(text))
    bridge.rpc.request.assert_not_called()
    bridge.telegram._call.assert_called()


@pytest.mark.parametrize(
    "incoming",
    [
        message("Resolve", owner=999),
        message("Resolve", sender=999),
        message("Resolve", kind="group"),
        {**message("Resolve"), "from": {"id": 123, "is_bot": True}},
    ],
)
async def test_other_chats_and_senders_cannot_call_the_agent_or_approve(bridge, incoming):
    await bridge.handle_message(incoming)
    bridge.rpc.request.assert_not_called()
    bridge.rpc.respond.assert_not_called()
    bridge.telegram._call.assert_not_called()


async def test_real_request_creates_conversation_with_permissions_and_quoted_context(bridge):
    bridge.rpc.request.side_effect = [
        {"thread": {"id": "own-thread"}},
        {"turn": {"id": "own-turn"}},
    ]
    incoming = message("Me explique esta atividade")
    incoming["reply_to_message"] = {"text": "https://canvas.example.test/courses/7/assignments/8"}
    await bridge.handle_message(incoming)
    calls = bridge.rpc.request.call_args_list
    assert calls[0].args[0] == "thread/start"
    config = calls[0].args[1]
    assert config["approvalPolicy"] == "on-request"
    assert config["sandbox"] == "workspace-write"
    assert config["approvalsReviewer"] == "user"
    assert calls[1].args[0] == "turn/start"
    assert "courses/7/assignments/8" in calls[1].args[1]["input"][0]["text"]
    assert bridge.state["thread_id"] == "own-thread"
    assert bridge.turn_id == "own-turn"
    assert bridge.state["in_progress"] is True
    assert bridge.state_path.stat().st_mode & 0o777 == 0o600
    assert "private-secret" not in bridge.state_path.read_text()


async def test_restart_resumes_history_without_starting_a_new_thread(bridge):
    bridge.save(thread_id="previous")
    bridge.rpc.request.return_value = {"thread": {"id": "previous"}}
    assert await bridge.thread() == "previous"
    assert bridge.rpc.request.call_args.args[0] == "thread/resume"
    assert bridge.rpc.request.call_args.args[1]["threadId"] == "previous"
    await bridge.thread()
    assert bridge.rpc.request.call_count == 1


async def test_an_unused_thread_without_rollout_recovers_without_reset(bridge):
    bridge.save(thread_id="reserved-but-empty")
    bridge.rpc.request.side_effect = [
        CodexError("No saved history", category="thread_missing"),
        {"thread": {"id": "fresh"}},
    ]
    assert await bridge.thread() == "fresh"
    assert [call.args[0] for call in bridge.rpc.request.call_args_list] == [
        "thread/resume",
        "thread/start",
    ]
    assert bridge.state["recovered_empty_thread"] is True


@pytest.mark.parametrize("state", [{"has_turns": True}, {"in_progress": True}])
async def test_missing_real_or_uncertain_history_is_never_silently_replaced(bridge, state):
    bridge.save(thread_id="real-history", **state)
    bridge.rpc.request.side_effect = CodexError("Missing", category="thread_missing")
    with pytest.raises(CodexError):
        await bridge.thread()
    assert bridge.rpc.request.call_count == 1
    assert bridge.state["thread_id"] == "real-history"


async def test_approval_requires_matching_code_and_never_grants_session_wide_rules(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    event = {
        "id": 99,
        "method": "item/commandExecution/requestApproval",
        "params": {
            "threadId": "thread",
            "turnId": "turn",
            "command": "python check.py",
            "reason": "Run test",
        },
    }
    await bridge.handle_event(event)
    bridge.rpc.respond.assert_not_called()
    code = next(iter(bridge.pending))
    await bridge.handle_message(message("/approve " + code, sender=999))
    bridge.rpc.respond.assert_not_called()
    await bridge.answer("/approve", "wrong")
    bridge.rpc.respond.assert_not_called()
    await bridge.answer("/approve", code)
    bridge.rpc.respond.assert_awaited_once_with(99, {"decision": "accept"})
    assert not bridge.pending
    await bridge.answer("/approve", code)
    assert bridge.rpc.respond.call_count == 1


async def test_structured_permission_denial_grants_no_network_or_filesystem_access(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    event = {
        "id": 88,
        "method": "item/permissions/requestApproval",
        "params": {
            "threadId": "thread",
            "permissions": {"network": {"enabled": True}},
        },
    }
    await bridge.handle_event(event)
    await bridge.answer("/deny", next(iter(bridge.pending)))
    bridge.rpc.respond.assert_awaited_once_with(88, {"permissions": {}, "scope": "turn"})


async def test_an_old_turn_cannot_request_approval_in_a_new_turn(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "new-turn"
    await bridge.handle_event(
        {
            "id": 56,
            "method": "item/commandExecution/requestApproval",
            "params": {"threadId": "thread", "turnId": "old-turn", "command": "old command"},
        }
    )
    assert not bridge.pending
    bridge.rpc.send.assert_awaited_once()
    bridge.telegram._call.assert_not_called()


async def test_automatic_worker_denies_extra_privileges_without_prompting_owner(bridge):
    bridge.automated_task = True
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(
        {
            "id": 33,
            "method": "item/permissions/requestApproval",
            "params": {
                "threadId": "thread",
                "turnId": "turn",
                "permissions": {"network": {"enabled": True}},
            },
        }
    )
    bridge.rpc.respond.assert_awaited_once_with(33, {"permissions": {}, "scope": "turn"})
    bridge.telegram._call.assert_not_called()


async def test_file_permission_prompt_includes_the_prepared_changes(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(
        {
            "method": "item/started",
            "params": {
                "threadId": "thread",
                "item": {
                    "type": "fileChange",
                    "id": "file",
                    "changes": [{"path": "solution.md", "diff": "+Requested work"}],
                },
            },
        }
    )
    await bridge.handle_event(
        {
            "id": 44,
            "method": "item/fileChange/requestApproval",
            "params": {
                "threadId": "thread",
                "turnId": "turn",
                "itemId": "file",
                "reason": "Create requested draft",
            },
        }
    )
    text = "".join(call.args[1]["text"] for call in bridge.telegram._call.call_args_list)
    assert "solution.md" in text and "+Requested work" in text
    bridge.rpc.respond.assert_not_called()


async def test_expired_approvals_do_not_execute(bridge):
    bridge.pending["code"] = {"expires": time.monotonic() - 1}
    await bridge.answer("/approve", "code")
    bridge.rpc.respond.assert_not_called()


async def test_questions_route_answers_back_to_the_same_rpc(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    event = {
        "id": 77,
        "method": "item/tool/requestUserInput",
        "params": {
            "threadId": "thread",
            "questions": [{"id": "format", "question": "Qual formato?"}],
        },
    }
    await bridge.handle_event(event)
    await bridge.answer("/answer", next(iter(bridge.pending)) + " Markdown")
    bridge.rpc.respond.assert_awaited_once_with(
        77, {"answers": {"format": {"answers": ["Markdown"]}}}
    )
    bridge.rpc.request.assert_not_called()


async def test_completed_turn_sends_final_text_but_not_reasoning_or_commentary(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    for item in [
        {"type": "reasoning", "id": "a", "text": "private reasoning"},
        {"type": "agentMessage", "id": "b", "phase": "commentary", "text": "Intermediate"},
        {"type": "agentMessage", "id": "c", "phase": "final_answer", "text": "Final answer"},
    ]:
        await bridge.handle_event(
            {"method": "item/completed", "params": {"threadId": "thread", "item": item}}
        )
    await bridge.handle_event(
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread",
                "turn": {"id": "turn", "status": "completed"},
            },
        }
    )
    assert bridge.telegram._call.call_args.args[1]["text"] == "Final answer"
    assert bridge.turn_id is None and bridge.state["in_progress"] is False


async def test_only_coursework_files_can_be_attached_and_credentials_are_redacted(bridge):
    root = bridge.project / ".local/activities"
    root.mkdir(parents=True)
    (root / "solution.md").write_text("Requested solution")
    (root / "leak.md").write_text(bridge.canvas.api_token)
    (root / "symlink").symlink_to(bridge.env_file)
    await bridge.deliver(
        "Response "
        + bridge.canvas.api_token
        + " "
        + bridge.settings.token
        + " [[arquivo: solution.md]] [[arquivo: leak.md]]"
        + " [[arquivo: ../../.env]] [[arquivo: symlink]]"
    )
    bridge.telegram.send_document.assert_awaited_once_with(
        root / "solution.md", b"Requested solution"
    )
    for call in bridge.telegram._call.call_args_list:
        assert "private-secret" not in call.args[1]["text"]


async def test_delivery_failure_is_not_retried(bridge):
    bridge.telegram._call.side_effect = TelegramError("Ambiguous delivery")
    with pytest.raises(TelegramError):
        await bridge.reply("Response")
    assert bridge.telegram._call.call_count == 1


async def test_rpc_matches_interleaved_events_and_responses_without_deadlock(tmp_path):
    rpc = CodexRPC("unused", tmp_path, [])
    output = asyncio.StreamReader()
    rpc.process = type("Process", (), {"stdout": output})()
    future = asyncio.get_running_loop().create_future()
    rpc.pending[1] = future
    task = asyncio.create_task(rpc.read())
    output.feed_data(b'{"method":"item/completed","params":{}}\n')
    output.feed_data(b'{"id":1,"result":{"ok":true}}\n')
    output.feed_eof()
    assert await future == {"ok": True}
    await task
    assert (await rpc.events.get())["method"] == "item/completed"


async def test_rpc_errors_never_expose_raw_provider_output(tmp_path):
    rpc = CodexRPC("unused", tmp_path, [])
    output = asyncio.StreamReader()
    rpc.process = type("Process", (), {"stdout": output})()
    future = asyncio.get_running_loop().create_future()
    rpc.pending[1] = future
    task = asyncio.create_task(rpc.read())
    output.feed_data(b'{"id":1,"error":{"message":"private-secret"}}\n')
    output.feed_eof()
    with pytest.raises(CodexError) as error:
        await future
    await task
    assert "private-secret" not in str(error.value)


def test_launchd_config_contains_paths_but_never_credentials_or_provider_api_keys(
    bridge, monkeypatch
):
    monkeypatch.setattr("canvas_mcp.agent_runtime.sys.platform", "linux")
    monkeypatch.setattr("canvas_mcp.agent_runtime.shutil.which", lambda name: "/bin/codex")
    manager = CodexManager(bridge.project, bridge.env_file)
    manager.prepare()
    text = (manager.directory / "launchd.plist").read_text()
    assert "private-secret" not in text
    assert "OPENAI_API_KEY" not in text
    assert "canvas_mcp.agent" in text and "KeepAlive" in text
    assert (manager.directory / "launchd.plist").stat().st_mode & 0o777 == 0o600


def test_runtime_install_preserves_state_and_artifacts_and_keeps_credentials_private(
    bridge, monkeypatch, tmp_path
):
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE", "AGENTS.md", "CLAUDE.md"):
        (bridge.project / name).write_text("placeholder")
    (bridge.project / "src").mkdir()
    bridge.save(thread_id="preserved", offset=91)
    root = bridge.project / ".local/activities"
    root.mkdir()
    (root / "solution.md").write_text("Existing work")
    monkeypatch.setattr("canvas_mcp.agent_runtime.shutil.which", lambda name: "/bin/" + name)
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("canvas_mcp.agent_runtime.subprocess.run", run)
    manager = CodexManager(bridge.project, bridge.env_file)
    manager.runtime = tmp_path / "private-runtime"
    manager.install_runtime()
    assert (manager.runtime / ".env").stat().st_mode & 0o777 == 0o600
    assert (manager.runtime / ".env").read_text() == bridge.env_file.read_text()
    assert manager.directory.is_symlink() and root.is_symlink()
    assert json.loads((manager.directory / "state.json").read_text())["offset"] == 91
    assert (root / "solution.md").read_text() == "Existing work"
    assert list((bridge.project / ".local").glob("activities.before-runtime-*"))
    assert all("private-secret" not in str(arguments) for arguments in calls)
    # Refresh credentials without replacing state or creating another backup.
    bridge.env_file.write_text(
        bridge.env_file.read_text().replace("canvas-private", "updated-private")
    )
    manager.install_runtime()
    assert "updated-private" in (manager.runtime / ".env").read_text()
    assert json.loads((manager.directory / "state.json").read_text())["thread_id"] == "preserved"
