"""User-owned setup: choose an account, review settings, then explicitly activate."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

from canvas_mcp.agent_policy import AgentPolicy
from canvas_mcp.codex_rpc import CodexError, CodexRPC
from canvas_mcp.config import Settings
from canvas_mcp.notifications import TelegramSettings

LABELS = {"codex": "Codex / ChatGPT", "claude": "Claude Code / Claude"}


def selected_provider(env_file: Path) -> str | None:
    values = dotenv_values(env_file, interpolate=False)
    provider = str(
        os.environ.get("CANVAS_AGENT_PROVIDER", values.get("CANVAS_AGENT_PROVIDER") or "")
    )
    provider = provider.strip().lower()
    if provider and provider not in LABELS:
        raise ValueError("CANVAS_AGENT_PROVIDER must be codex or claude. Use canvas-agent setup.")
    return provider or None


def resolve_provider(explicit: str | None, env_file: Path) -> str:
    provider = explicit or selected_provider(env_file)
    if not provider:
        raise ValueError(
            "Choose an agent with canvas-agent setup, or pass --provider codex/claude. "
            "No provider has been selected automatically."
        )
    return provider


def terminal_text(value: object) -> str:
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(value or "not provided"))[:160]


def login_environment() -> dict:
    environment = dict(os.environ)
    for name in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_PROFILE",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_SIMPLE",
        "CANVAS_API_TOKEN",
        "TELEGRAM_BOT_TOKEN",
    ):
        environment.pop(name, None)
    return environment


async def codex_identity(binary: str, project: Path) -> dict:
    rpc = CodexRPC(binary, project, ["-c", 'model_provider="openai"', "-c", "mcp_servers={}"])
    try:
        await rpc.start()
        account = (await rpc.request("account/read", {"refreshToken": False}))["account"]
        return {"email": account.get("email"), "plan": account.get("planType")}
    finally:
        await rpc.close()


def identity(provider: str, project: Path) -> dict | None:
    """Read native login metadata only; never load a credential cache or start a turn."""
    binary = shutil.which(provider)
    if not binary:
        raise ValueError(f"Install {LABELS[provider]} before continuing.")
    if provider == "codex":
        try:
            return asyncio.run(codex_identity(binary, project))
        except CodexError as error:
            if error.category == "authentication":
                return None
            raise
    try:
        result = subprocess.run(
            [binary, "auth", "status"],
            cwd=project,
            env=login_environment(),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        account = json.loads(result.stdout)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise ValueError("Could not check Claude Code login status.") from None
    if not isinstance(account, dict):
        raise ValueError("Claude Code returned an invalid login status.")
    if not account.get("loggedIn") or account.get("authMethod") != "claude.ai":
        return None
    return {"email": account.get("email"), "plan": account.get("subscriptionType")}


def login(provider: str, project: Path) -> dict:
    binary = shutil.which(provider)
    if not binary:
        raise ValueError(f"Install {LABELS[provider]} before signing in.")
    print(f"Opening the official {LABELS[provider]} login. Choose your account in the browser.")
    print("This login is shared with other uses of this CLI on this computer.")
    arguments = (
        [binary, "login"] if provider == "codex" else [binary, "auth", "login", "--claudeai"]
    )
    result = subprocess.run(arguments, cwd=project, env=login_environment(), check=False)
    if result.returncode:
        raise ValueError("Login was not completed; the receiver was not started.")
    account = identity(provider, project)
    if not account:
        raise ValueError("Subscription login was not confirmed; the receiver was not started.")
    print(
        f"Account: {terminal_text(account.get('email'))} · "
        f"plan: {terminal_text(account.get('plan'))}"
    )
    print("Login completed. To configure the bot, run canvas-agent setup.")
    return {"provider": provider, "authenticated": True, "started": False}


def overview(project: Path, env_file: Path) -> dict:
    from canvas_mcp.agent import AgentManager
    from canvas_mcp.agent_runtime import CodexManager

    providers = {}
    for provider, manager in (
        ("codex", CodexManager(project, env_file)),
        ("claude", AgentManager(project, env_file)),
    ):
        try:
            state = manager.status()
            if provider == "claude":
                state["running"] = bool(
                    state.get("pid") and state.get("status") in {"busy", "waiting", "idle"}
                )
            providers[provider] = state
        except (ValueError, OSError, subprocess.TimeoutExpired):
            providers[provider] = {"running": None, "status": "unavailable"}
    return {
        "selected_provider": selected_provider(env_file),
        "automatic": AgentPolicy.load(env_file).automatic,
        "providers": providers,
    }


def describe_overview(state: dict) -> None:
    selected = state["selected_provider"]
    print(
        "Selected agent: "
        + (LABELS[selected] if selected else "not configured; use canvas-agent setup")
    )
    for provider, item in state["providers"].items():
        running = item.get("running")
        status = "running" if running else "stopped" if running is False else "not checked"
        print(f"{LABELS[provider]}: {status}")
        if item.get("channel_registration") == "blocked_by_organization":
            print("  Channels is blocked: your Team administrator must enable it.")
        if item.get("telegram"):
            print("  Telegram: " + terminal_text(item["telegram"]))
    print(
        "Selected mode: "
        + (
            "automatic — prepares and submits at 08:00 local time"
            if state["automatic"]
            else "manual — waits for your request"
        )
    )
    print("The mode above comes from .env. After changing it, stop/start to update the service.")


def choose(prompt: str, options: dict[str, str], *, default: str | None = None) -> str:
    print(prompt)
    for key, label in options.items():
        print(f"  {key}. {label}")
    while True:
        answer = input("> ").strip().lower() or default
        if answer in options:
            return answer
        print("Choose one of the displayed options.")


def interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def cancel_setup(*, login_completed: bool = False) -> dict:
    print("Cancelled. Bot choices were not saved and services were not changed.")
    if login_completed:
        print("Your completed login remains available in the CLI.")
    return {"cancelled": True}


def setup(project: Path, env_file: Path, provider: str | None = None) -> dict:
    from canvas_mcp.agent import control, display

    if not interactive_terminal():
        raise ValueError("Open an interactive terminal and run uv run canvas-agent setup.")
    print("\nCanvas · configure the Telegram agent\n")
    print("Choose the provider, account, and mode, then review before saving/starting.")
    print(
        "The Canvas token and Telegram bot settings are read from .env and will not be displayed."
    )
    canvas = Settings.load(env_file)
    telegram = TelegramSettings.load(env_file)
    if not telegram.chat_id.isdecimal() or int(telegram.chat_id) < 1:
        raise ValueError("Set TELEGRAM_CHAT_ID to your private chat before setup.")
    if not provider:
        choice = choose(
            "1/4 · Which agent would you like to use?",
            {
                "1": LABELS["codex"],
                "2": LABELS["claude"],
                "0": "Cancel",
            },
        )
        if choice == "0":
            return cancel_setup()
        provider = {"1": "codex", "2": "claude"}[choice]
    else:
        print("1/4 · Specified agent: " + LABELS[provider])
    for name in ("CANVAS_AGENT_PROVIDER", "CANVAS_AGENT_AUTO"):
        if name in os.environ:
            raise ValueError(
                f"Remove {name} from the shell environment so setup can use your .env."
            )
    print("\n2/4 · Subscription account")
    print("Checking existing login status only, without starting AI tasks.")
    account = identity(provider, project)
    if account:
        print(
            f"Account: {terminal_text(account.get('email'))} · "
            f"plan: {terminal_text(account.get('plan'))}"
        )
        choice = choose(
            "How would you like to connect?",
            {
                "1": "Explicitly use this account",
                "2": "Open official login and choose an account",
                "0": "Cancel",
            },
        )
    else:
        print("No subscription login is available in this CLI.")
        choice = choose(
            "How would you like to connect?", {"2": "Open official login", "0": "Cancel"}
        )
    if choice == "0":
        return cancel_setup()
    if choice == "2":
        login(provider, project)
        account = identity(provider, project)
    mode = choose(
        "\n3/4 · How should the agent work? (Enter = manual)",
        {
            "1": "Manual: wait for my request; submit only when I ask",
            "2": "Automatic: prepare and submit supported assignments at 08:00 on the Mac",
            "0": "Cancel",
        },
        default="1",
    )
    if mode == "0":
        return cancel_setup(login_completed=choice == "2")
    automatic = mode == "2"
    if automatic and canvas.read_only:
        raise ValueError(
            "Automatic mode requires CANVAS_READ_ONLY=false in .env. Nothing was saved."
        )
    if automatic and sys.platform != "darwin":
        print("On this system, setup does not install a schedule: configure auto-run with cron.")
    state = overview(project, env_file)
    active = [name for name, item in state["providers"].items() if item.get("running")]
    print("\n4/4 · Review configuration")
    print("Agent: " + LABELS[provider])
    print("Account: " + terminal_text((account or {}).get("email")))
    print("Canvas: " + canvas.api_url)
    print("Telegram: your private chat, ID ending in " + telegram.chat_id[-4:])
    print(
        "Mode: "
        + (
            "automatic: prepares AND submits; local 08:00 job"
            if automatic
            else "manual: waits for your request"
        )
    )
    if active:
        print("Currently running: " + ", ".join(LABELS[name] for name in active))
        print(
            "If you choose to start, these receivers will be stopped "
            "before the selected one starts."
        )
    if provider == "claude":
        print(
            "Claude Telegram requires Bun, the official plugin, and administrator-enabled Channels."
        )
    print("Saving changes only provider/mode keys in .env; it preserves tokens and notes.")
    print(
        "Login stays in the CLI. The bot has its own conversation "
        "and does not import existing chats."
    )
    print("The GitHub Actions summary remains independent of this configuration.")
    options = {"2": "Save without starting or changing services", "0": "Cancel without saving"}
    if provider == "claude" or sys.platform == "darwin":
        options = {"1": "Save and start now", **options}
    action = choose("What would you like to do? (Enter = cancel)", options, default="0")
    if action == "0":
        return cancel_setup(login_completed=choice == "2")
    if action == "1" and any(item.get("running") is None for item in state["providers"].values()):
        raise ValueError(
            "Could not check all receivers. Check canvas-agent status "
            "before starting. Choices have not been saved."
        )
    set_key(str(env_file), "CANVAS_AGENT_PROVIDER", provider, quote_mode="never")
    set_key(str(env_file), "CANVAS_AGENT_AUTO", str(automatic).lower(), quote_mode="never")
    env_file.chmod(0o600)
    print("Choice saved in .env. Login and tokens were not copied into public configuration.")
    if action == "2":
        if active:
            print("Existing services continue using their previous configuration.")
            print("To apply the change later: uv run canvas-agent setup → save and start.")
        else:
            print("To activate later: uv run canvas-agent start")
        return {"saved": True, "provider": provider, "automatic": automatic, "started": False}
    for name in active:
        print("Stopping " + LABELS[name] + "…")
        control("stop", name, project, env_file)
    print("Starting " + LABELS[provider] + "…")
    result = control("start", provider, project, env_file)
    display("start", provider, result)
    return {"saved": True, "provider": provider, "automatic": automatic, **result}
