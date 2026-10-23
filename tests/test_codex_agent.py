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


def permission_event(*, method="mcpServer/elicitation/request", identifier=99, schema=None):
    return {
        "id": identifier,
        "method": method,
        "params": {
            "threadId": "thread",
            "turnId": "turn",
            "mode": "form",
            "message": 'Allow tool "download_canvas_file"?',
            "command": "python check.py",
            "requestedSchema": schema or {"type": "object", "properties": {}},
        },
    }


@pytest.mark.parametrize(
    "reply",
    ["Sim", "yes i allow", "/answer yes i allow", "/answer {code} yes i allow", "/approve {code}"],
)
async def test_empty_mcp_confirmation_accepts_human_reply_without_json(bridge, reply):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(permission_event())
    code = next(iter(bridge.pending))
    prompt = bridge.telegram._call.call_args.args[1]["text"]
    assert "Sim ou Não" in prompt and "JSON" not in prompt
    await bridge.handle_message(message(reply.format(code=code)))
    bridge.rpc.respond.assert_awaited_once_with(99, {"action": "accept", "content": {}})
    bridge.rpc.request.assert_not_called()
    assert not bridge.pending


@pytest.mark.parametrize("reply", ["Não", "/deny {code}", "/answer {code} não"])
async def test_empty_mcp_confirmation_denies_without_running_a_new_turn(bridge, reply):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(permission_event())
    code = next(iter(bridge.pending))
    await bridge.handle_message(message(reply.format(code=code)))
    bridge.rpc.respond.assert_awaited_once_with(99, {"action": "decline", "content": None})
    bridge.rpc.request.assert_not_called()


async def test_plain_yes_also_answers_shell_permission_and_cannot_be_reused(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(permission_event(method="item/commandExecution/requestApproval"))
    await bridge.handle_message(message("Sim", sender=999))
    bridge.rpc.respond.assert_not_called()
    await bridge.handle_message(message("Sim"))
    await bridge.handle_message(message("Sim"))
    bridge.rpc.respond.assert_awaited_once_with(99, {"decision": "accept"})
    bridge.rpc.request.assert_not_called()


async def test_general_mcp_form_is_not_a_permission_and_validates_required_content(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    await bridge.handle_event(permission_event(schema=schema))
    code = next(iter(bridge.pending))
    await bridge.handle_message(message("Sim"))
    await bridge.handle_message(message("/approve " + code))
    await bridge.handle_message(message("/answer " + code + " {}"))
    bridge.rpc.respond.assert_not_called()
    await bridge.handle_message(message('{"name": "Maria"}'))
    bridge.rpc.respond.assert_awaited_once_with(
        99, {"action": "accept", "content": {"name": "Maria"}}
    )
    bridge.rpc.request.assert_not_called()


async def test_multiple_pending_requests_require_code_or_reply_to_specific_message(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(permission_event(identifier=99))
    first_code = next(iter(bridge.pending))
    bridge.telegram._call.return_value = {"message_id": 2}
    await bridge.handle_event(permission_event(identifier=100))
    await bridge.handle_message(message("Sim"))
    await bridge.handle_message(message("/approve 000000"))
    bridge.rpc.respond.assert_not_called()
    incoming = message("Sim")
    incoming["reply_to_message"] = {"message_id": 1}
    await bridge.handle_message(incoming)
    bridge.rpc.respond.assert_awaited_once_with(99, {"action": "accept", "content": {}})
    assert first_code not in bridge.pending and len(bridge.pending) == 1


async def test_resolved_or_expired_prompt_never_accepts_a_late_yes(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(permission_event())
    code = next(iter(bridge.pending))
    bridge.pending[code]["expires"] = time.monotonic() - 1
    await bridge.handle_message(message("Sim"))
    await bridge.handle_message(message("/approve " + code))
    bridge.rpc.respond.assert_not_called()
    await bridge.handle_event({"method": "serverRequest/resolved", "params": {"requestId": 99}})
    assert not bridge.pending
    await bridge.handle_message(message("Sim"))
    bridge.rpc.request.assert_not_called()


async def test_plain_question_response_continues_same_request(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_event(
        {
            "id": 77,
            "method": "item/tool/requestUserInput",
            "params": {
                "threadId": "thread",
                "questions": [{"id": "format", "question": "Formato?"}],
            },
        }
    )
    await bridge.handle_message(message("Markdown"))
    bridge.rpc.respond.assert_awaited_once_with(
        77, {"answers": {"format": {"answers": ["Markdown"]}}}
    )
    bridge.rpc.request.assert_not_called()


async def test_message_during_work_steers_existing_turn_and_keeps_history(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    await bridge.handle_message(
        message("Estou falando de https://canvas.example.test/courses/7/assignments/8")
    )
    call = bridge.rpc.request.call_args
    assert call.args[0] == "turn/steer"
    assert call.args[1]["threadId"] == "thread" and call.args[1]["expectedTurnId"] == "turn"
    assert "assignments/8" in call.args[1]["input"][0]["text"]
    assert bridge.state["assignment_context"]["assignment_id"] == 8
    assert bridge.turn_id == "turn"


async def test_explicit_current_assignment_overrides_old_context_and_old_quoted_message(bridge):
    bridge.save(assignment_context={"course_id": 1, "assignment_id": 2})
    incoming = message("https://canvas.example.test/courses/7/assignments/8")
    incoming["reply_to_message"] = {"text": "https://canvas.example.test/courses/1/assignments/2"}
    await bridge.contextual_input(incoming, incoming["text"])
    assert bridge.state["assignment_context"]["assignment_id"] == 8
    reloaded = CodexBridge(bridge.project, bridge.env_file, "/bin/codex")
    assert reloaded.state["assignment_context"]["assignment_id"] == 8
    assert "previous_assignment" in await reloaded.contextual_input(message("Continue"), "Continue")
    await bridge.handle_message(message("/reset"))
    assert bridge.state["assignment_context"] is None


@pytest.mark.parametrize("count", [0, 1, 2])
async def test_unquoted_reminder_reference_reads_all_courses_and_never_selects_old_default(
    bridge, monkeypatch, count
):
    from canvas_mcp.codex_agent import collect_report

    collect = AsyncMock(
        spec=collect_report,
        return_value={
            "assignments": [
                {
                    "id": 8 + index,
                    "course_id": 7,
                    "name": "Current work",
                    "html_url": f"https://canvas.example.test/courses/7/assignments/{8 + index}",
                }
                for index in range(count)
            ]
        },
    )
    monkeypatch.setattr("canvas_mcp.codex_agent.collect_report", collect)
    bridge.save(assignment_context={"course_id": 1, "assignment_id": 2})
    text = "Faça essa atividade por completo e envie"
    result = await bridge.contextual_input(message(text), text)
    collect.assert_awaited_once_with(bridge.canvas, all_courses=True)
    assert "current_deadlines" in result
    if count == 1:
        assert bridge.state["assignment_context"]["assignment_id"] == 8
    else:
        assert bridge.state["assignment_context"] is None
        assert '"selected_assignment": null' in result


async def test_reminder_context_failure_never_uses_old_course_or_starts_a_turn(bridge, monkeypatch):
    monkeypatch.setattr(
        "canvas_mcp.codex_agent.collect_report", AsyncMock(side_effect=ValueError("secret"))
    )
    bridge.save(assignment_context={"course_id": 1, "assignment_id": 2})
    with pytest.raises(CodexError) as error:
        await bridge.contextual_input(message("Faça essa atividade"), "Faça essa atividade")
    assert error.value.category == "assignment_context_unavailable"
    assert "secret" not in str(error.value)
    bridge.turn_id = "still-working"
    await bridge.handle_message(message("Faça essa atividade"))
    assert bridge.turn_id == "still-working"
    assert bridge.state["assignment_context"] is None
    bridge.rpc.request.assert_not_called()


async def test_continuation_keeps_selected_assignment_without_refreshing_to_another_deadline(
    bridge, monkeypatch
):
    collect = AsyncMock()
    monkeypatch.setattr("canvas_mcp.codex_agent.collect_report", collect)
    bridge.save(assignment_context={"course_id": 7, "assignment_id": 8})
    text = "Continue essa atividade"
    result = await bridge.contextual_input(message(text), text)
    assert '"assignment_id": 8' in result
    collect.assert_not_called()


async def test_approval_prompt_masks_signed_download_url(bridge):
    bridge.save(thread_id="thread")
    bridge.turn_id = "turn"
    event = permission_event(method="item/commandExecution/requestApproval")
    event["params"]["command"] = (
        "curl 'https://canvas.example.test/files/1/download?download_frd=1&verifier=signed-secret'"
    )
    await bridge.handle_event(event)
    prompt = "".join(call.args[1]["text"] for call in bridge.telegram._call.call_args_list)
    assert "signed-secret" not in prompt and "files/1/download" in prompt


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
