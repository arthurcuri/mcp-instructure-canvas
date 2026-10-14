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
        raise ValueError("CANVAS_AGENT_PROVIDER deve ser codex ou claude. Use canvas-agent setup.")
    return provider or None


def resolve_provider(explicit: str | None, env_file: Path) -> str:
    provider = explicit or selected_provider(env_file)
    if not provider:
        raise ValueError(
            "Escolha seu agente com canvas-agent setup, ou informe --provider codex/claude. "
            "Nenhum provedor foi escolhido automaticamente."
        )
    return provider


def terminal_text(value: object) -> str:
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(value or "não informado"))[:160]


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
        raise ValueError(f"Instale {LABELS[provider]} antes de continuar.")
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
        raise ValueError("Não foi possível consultar o login do Claude Code.") from None
    if not isinstance(account, dict):
        raise ValueError("O Claude Code retornou um status de login inválido.")
    if not account.get("loggedIn") or account.get("authMethod") != "claude.ai":
        return None
    return {"email": account.get("email"), "plan": account.get("subscriptionType")}


def login(provider: str, project: Path) -> dict:
    binary = shutil.which(provider)
    if not binary:
        raise ValueError(f"Instale {LABELS[provider]} antes de fazer login.")
    print(f"Abrindo o login oficial de {LABELS[provider]}. Escolha sua conta no navegador.")
    print("Esse login é compartilhado com os outros usos desse CLI nesta máquina.")
    arguments = (
        [binary, "login"] if provider == "codex" else [binary, "auth", "login", "--claudeai"]
    )
    result = subprocess.run(arguments, cwd=project, env=login_environment(), check=False)
    if result.returncode:
        raise ValueError("O login não foi concluído; o receptor não foi iniciado.")
    account = identity(provider, project)
    if not account:
        raise ValueError(
            "Não foi confirmado um login pela assinatura; o receptor não foi iniciado."
        )
    print(
        f"Conta: {terminal_text(account.get('email'))} · "
        f"plano: {terminal_text(account.get('plan'))}"
    )
    print("Login concluído. Para configurar o bot, execute canvas-agent setup.")
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
        "Agente escolhido: "
        + (LABELS[selected] if selected else "não configurado; use canvas-agent setup")
    )
    for provider, item in state["providers"].items():
        running = item.get("running")
        status = "rodando" if running else "parado" if running is False else "não verificado"
        print(f"{LABELS[provider]}: {status}")
        if item.get("channel_registration") == "blocked_by_organization":
            print("  Channels bloqueado: o administrador do Team precisa habilitá-lo.")
        if item.get("telegram"):
            print("  Telegram: " + terminal_text(item["telegram"]))
    print(
        "Modo escolhido: "
        + (
            "automático — resolve e envia às 08h locais"
            if state["automatic"]
            else "manual — aguarda seu pedido"
        )
    )
    print("O modo acima vem do .env. Após alterá-lo, pare e inicie para atualizar o serviço.")


def choose(prompt: str, options: dict[str, str], *, default: str | None = None) -> str:
    print(prompt)
    for key, label in options.items():
        print(f"  {key}. {label}")
    while True:
        answer = input("> ").strip().lower() or default
        if answer in options:
            return answer
        print("Escolha uma das opções exibidas.")


def interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def cancel_setup(*, login_completed: bool = False) -> dict:
    print("Cancelado. As escolhas do bot não foram salvas e nenhum serviço foi alterado.")
    if login_completed:
        print("O login que você concluiu continua disponível no CLI.")
    return {"cancelled": True}


def setup(project: Path, env_file: Path, provider: str | None = None) -> dict:
    from canvas_mcp.agent import control, display

    if not interactive_terminal():
        raise ValueError("Abra um Terminal interativo e execute uv run canvas-agent setup.")
    print("\nCanvas · configurar o agente do Telegram\n")
    print("Você escolhe o provedor, a conta e o modo, e revisa antes de salvar/iniciar.")
    print("O token Canvas e o bot Telegram são lidos do .env; não serão exibidos.")
    canvas = Settings.load(env_file)
    telegram = TelegramSettings.load(env_file)
    if not telegram.chat_id.isdecimal() or int(telegram.chat_id) < 1:
        raise ValueError("Configure TELEGRAM_CHAT_ID da sua conversa privada antes do setup.")
    if not provider:
        choice = choose(
            "1/4 · Qual agente você quer usar?",
            {
                "1": LABELS["codex"],
                "2": LABELS["claude"],
                "0": "Cancelar",
            },
        )
        if choice == "0":
            return cancel_setup()
        provider = {"1": "codex", "2": "claude"}[choice]
    else:
        print("1/4 · Agente informado: " + LABELS[provider])
    for name in ("CANVAS_AGENT_PROVIDER", "CANVAS_AGENT_AUTO"):
        if name in os.environ:
            raise ValueError(f"Remova {name} do ambiente do shell para o setup usar seu .env.")
    print("\n2/4 · Conta da assinatura")
    print("Consultando apenas o status do login existente, sem iniciar tarefas de IA.")
    account = identity(provider, project)
    if account:
        print(
            f"Conta: {terminal_text(account.get('email'))} · "
            f"plano: {terminal_text(account.get('plan'))}"
        )
        choice = choose(
            "Como deseja conectar?",
            {
                "1": "Usar explicitamente esta conta",
                "2": "Abrir o login oficial e escolher a conta",
                "0": "Cancelar",
            },
        )
    else:
        print("Não há um login pela assinatura disponível neste CLI.")
        choice = choose("Como deseja conectar?", {"2": "Abrir o login oficial", "0": "Cancelar"})
    if choice == "0":
        return cancel_setup()
    if choice == "2":
        login(provider, project)
        account = identity(provider, project)
    mode = choose(
        "\n3/4 · Como o agente deve trabalhar? (Enter = manual)",
        {
            "1": "Manual: aguardar meu pedido; enviar somente quando eu pedir",
            "2": "Automático: resolver e enviar atividades compatíveis às 08h no Mac",
            "0": "Cancelar",
        },
        default="1",
    )
    if mode == "0":
        return cancel_setup(login_completed=choice == "2")
    automatic = mode == "2"
    if automatic and canvas.read_only:
        raise ValueError("O modo automático exige CANVAS_READ_ONLY=false no .env. Nada foi salvo.")
    if automatic and sys.platform != "darwin":
        print("Neste sistema, o setup não instala agendamento: configure o cron de auto-run.")
    state = overview(project, env_file)
    active = [name for name, item in state["providers"].items() if item.get("running")]
    print("\n4/4 · Revise a configuração")
    print("Agente: " + LABELS[provider])
    print("Conta: " + terminal_text((account or {}).get("email")))
    print("Canvas: " + canvas.api_url)
    print("Telegram: sua conversa privada, ID terminado em " + telegram.chat_id[-4:])
    print(
        "Modo: "
        + (
            "automático: prepara E envia; job local das 08h"
            if automatic
            else "manual: aguarda seu pedido"
        )
    )
    if active:
        print("Rodando agora: " + ", ".join(LABELS[name] for name in active))
        print("Se escolher iniciar, esses receptores serão parados antes de iniciar o escolhido.")
    if provider == "claude":
        print("Claude Telegram exige Bun, plugin oficial e Channels habilitado pelo administrador.")
    print("Salvar altera somente as chaves de provedor/modo no .env; preserva tokens e notas.")
    print("O login fica no CLI. A conversa do bot é própria e não importa seus chats existentes.")
    print("O resumo do GitHub Actions continua independente desta configuração.")
    options = {"2": "Salvar sem iniciar ou alterar serviços", "0": "Cancelar sem salvar"}
    if provider == "claude" or sys.platform == "darwin":
        options = {"1": "Salvar e iniciar agora", **options}
    action = choose("O que deseja fazer? (Enter = cancelar)", options, default="0")
    if action == "0":
        return cancel_setup(login_completed=choice == "2")
    if action == "1" and any(item.get("running") is None for item in state["providers"].values()):
        raise ValueError(
            "Não foi possível verificar todos os receptores. Confira canvas-agent status "
            "antes de iniciar. As escolhas não foram salvas."
        )
    set_key(str(env_file), "CANVAS_AGENT_PROVIDER", provider, quote_mode="never")
    set_key(str(env_file), "CANVAS_AGENT_AUTO", str(automatic).lower(), quote_mode="never")
    env_file.chmod(0o600)
    print("Escolha salva no .env. Login e tokens não foram copiados para a configuração pública.")
    if action == "2":
        if active:
            print("Os serviços existentes seguem com a configuração anterior.")
            print("Para aplicar a troca depois: uv run canvas-agent setup → salvar e iniciar.")
        else:
            print("Para ativar depois: uv run canvas-agent start")
        return {"saved": True, "provider": provider, "automatic": automatic, "started": False}
    for name in active:
        print("Parando " + LABELS[name] + "…")
        control("stop", name, project, env_file)
    print("Iniciando " + LABELS[provider] + "…")
    result = control("start", provider, project, env_file)
    display("start", provider, result)
    return {"saved": True, "provider": provider, "automatic": automatic, **result}
