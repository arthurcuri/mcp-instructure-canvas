"""Weekly deadline snapshot and optional Telegram reminder, without an LLM."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Literal

from canvas_mcp.client import CanvasClient, CanvasError
from canvas_mcp.config import Settings
from canvas_mcp.notifications import TelegramClient, TelegramSettings
from canvas_mcp.service import CanvasService


async def collect_report(
    settings: Settings,
    *,
    course_id: int | None = None,
    all_courses: bool = False,
    period: Literal["this_week", "next_7_days"] = "next_7_days",
    include_completed: bool = False,
) -> dict:
    client = CanvasClient(replace(settings, read_only=True))
    try:
        return await CanvasService(settings, client).get_due_assignments(
            course_id=course_id,
            all_courses=all_courses,
            period=period,
            include_completed=include_completed,
        )
    finally:
        await client.close()


def save_report(path: Path, report: dict) -> None:
    """Replace a snapshot atomically; its file is readable only by the owner."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as file:
            temporary = Path(file.name)
            os.fchmod(file.fileno(), 0o600)
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consultar prazos, salvar relatório e opcionalmente avisar no Telegram, sem IA."
    )
    parser.add_argument("--env-file", type=Path, help="Caminho explícito do .env.")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--course-id", type=int, help="Curso específico; padrão: curso do .env.")
    scope.add_argument(
        "--all-courses", action="store_true", help="Consultar todas as matérias ativas."
    )
    parser.add_argument("--period", choices=["this_week", "next_7_days"], default="next_7_days")
    parser.add_argument("--include-completed", action="store_true")
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enviar lembrete ao chat configurado; exige TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.",
    )
    parser.add_argument(
        "--output", type=Path, help="Salvar JSON com permissão 600; padrão: stdout."
    )
    args = parser.parse_args()
    try:
        settings = Settings.load(args.env_file)
        telegram = TelegramSettings.load(args.env_file) if args.telegram else None
        report = asyncio.run(
            collect_report(
                settings,
                course_id=args.course_id,
                all_courses=args.all_courses,
                period=args.period,
                include_completed=args.include_completed,
            )
        )
        if args.output is not None:
            save_report(args.output, report)
            print(
                f"Relatório salvo: {report['count']} atividade(s), "
                f"{len(report['courses_checked'])} matéria(s)."
            )
        elif telegram is None:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        if telegram is not None:
            sent = asyncio.run(TelegramClient(telegram).send_report(report))
            print(f"Telegram confirmou {sent} mensagem(ns).")
    except (CanvasError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print("Não foi possível ler a configuração ou salvar o relatório local.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
