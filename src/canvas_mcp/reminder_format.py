"""Readable, localized reminder sections packed within Telegram's UTF-16 limit."""

import re
import unicodedata
from collections import Counter
from zoneinfo import ZoneInfo

from canvas_mcp.service import parse_datetime

MESSAGE_LIMIT = 4000  # Leave room below Telegram's 4,096 UTF-16-unit limit.

TEXT = {
    "en": {
        "deadlines": "📚 ASSIGNMENTS WITH DEADLINES",
        "assignment": "📝 NEW OR UPDATED ASSIGNMENTS",
        "announcement": "📢 ANNOUNCEMENTS",
        "discussion": "💬 DISCUSSIONS",
        "materials": "📎 MATERIALS",
        "calendar_event": "📅 CALENDAR EVENTS",
        "status": "ℹ️ CHECK STATUS",
        "timezone": "Timezone",
        "week": "Updates",
        "continued": "continued",
        "due": "Due",
        "changed": "Updated",
        "posted": "Published",
        "starts": "Starts",
        "course": "Course",
        "file": "File",
        "page": "Page",
        "no_due": "No assignments are due in the selected period.",
        "undated_assignments": "Without a due date in Canvas: {count} {assignments}.",
        "no_updates": "No dated updates found this week in the checked sources.",
        "undated_updates": "Without an update date, outside this summary: {count} {items}.",
        "help": "Need help? Reply with the assignment name or link.",
        "partial": "Some areas of Canvas could not be checked:",
        "unavailable": "{source}: unavailable in {count} {courses}.",
        "course_one": "course",
        "course_many": "courses",
        "assignment_one": "assignment",
        "assignment_many": "assignments",
        "item_one": "item",
        "item_many": "items",
        "available": "The updates that could be checked are listed above.",
        "repeated": "Weekly summary: the same items may appear again until Sunday.",
        "sources": {
            "announcement": "Announcements",
            "discussion": "Discussions",
            "page": "Pages",
            "file": "Files",
            "assignment": "Assignments",
            "calendar_event": "Calendar events",
        },
        "date_format": "%Y-%m-%d at %H:%M",
        "short_date": "%Y-%m-%d",
    },
    "pt-BR": {
        "deadlines": "📚 ATIVIDADES COM PRAZO",
        "assignment": "📝 ATIVIDADES NOVAS OU ALTERADAS",
        "announcement": "📢 COMUNICADOS",
        "discussion": "💬 FÓRUNS",
        "materials": "📎 MATERIAIS",
        "calendar_event": "📅 EVENTOS",
        "status": "ℹ️ SOBRE A CONSULTA",
        "timezone": "Fuso",
        "week": "Novidades",
        "continued": "continuação",
        "due": "Prazo",
        "changed": "Atualização",
        "posted": "Publicação",
        "starts": "Início",
        "course": "Disciplina",
        "file": "Arquivo",
        "page": "Página",
        "no_due": "Nenhuma atividade com prazo no período consultado.",
        "undated_assignments": "Sem prazo informado no Canvas: {count} {assignments}.",
        "no_updates": "Nenhuma novidade com data nesta semana nas fontes consultadas.",
        "undated_updates": "Sem data de alteração, fora deste resumo: {count} {items}.",
        "help": "Quer ajuda? Responda com o nome ou link da atividade.",
        "partial": "Não foi possível consultar algumas áreas do Canvas:",
        "unavailable": "{source}: consulta indisponível em {count} {courses}.",
        "course_one": "disciplina",
        "course_many": "disciplinas",
        "assignment_one": "atividade",
        "assignment_many": "atividades",
        "item_one": "item",
        "item_many": "itens",
        "available": "As novidades que puderam ser consultadas estão listadas acima.",
        "repeated": "Resumo da semana: os mesmos itens podem reaparecer até domingo.",
        "sources": {
            "announcement": "Comunicados",
            "discussion": "Fóruns",
            "page": "Páginas",
            "file": "Arquivos",
            "assignment": "Atividades",
            "calendar_event": "Eventos",
        },
        "date_format": "%d/%m/%Y às %H:%M",
        "short_date": "%d/%m/%Y",
    },
}


def notification_language(value: str) -> str:
    language = {"en": "en", "pt": "pt-BR", "pt-br": "pt-BR"}.get(value.strip().lower())
    if language is None:
        raise ValueError("CANVAS_NOTIFICATION_LANGUAGE must be en or pt-BR.")
    return language


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _text_chunks(text: str, limit: int) -> list[str]:
    """Fallback for one oversized field; preserve words and common emoji clusters."""
    chunks = []
    while utf16_length(text) > limit:
        used = 0
        end = 0
        for char in text:
            cost = 2 if ord(char) > 0xFFFF else 1
            if used + cost > limit:
                break
            used += cost
            end += 1
        # Do not separate a ZWJ sequence, combining mark, or skin-tone modifier.
        while end and (
            text[end - 1] == "\u200d"
            or text[end] == "\u200d"
            or unicodedata.category(text[end]).startswith("M")
            or "\U0001f3fb" <= text[end] <= "\U0001f3ff"
        ):
            end -= 1
        if not end:
            raise ValueError("A reminder character sequence exceeds the message limit.")
        boundary = text.rfind(" ", 0, end + 1)
        if boundary >= end // 2:
            end = boundary + 1
        chunks.append(text[:end])
        text = text[end:]
    if text:
        chunks.append(text)
    return chunks


def _oversized_block(block: str, limit: int) -> list[str]:
    parts = []
    current = ""
    for line in block.splitlines(keepends=True):
        if utf16_length(line) > limit and re.fullmatch(r"https?://\S+\s*", line):
            raise ValueError("A reminder link exceeds Telegram's message limit.")
        if utf16_length(line) > limit:
            while utf16_length(current + line) > limit:
                available = limit - utf16_length(current)
                if available < 16:
                    parts.append(current.rstrip("\n"))
                    current = ""
                    continue
                piece = _text_chunks(line, available)[0]
                parts.append((current + piece).rstrip("\n"))
                line = line[len(piece) :]
                current = ""
            current += line
        else:
            if current and utf16_length(current + line) > limit:
                parts.append(current.rstrip("\n"))
                current = ""
            current += line
    if current:
        parts.append(current.rstrip("\n"))
    return parts


def _section(heading: str, context: str, blocks: list[str], continued: str) -> list[str]:
    header = f"Canvas · {heading}\n{context}"
    continuation = f"Canvas · {heading} ({continued})\n{context}"
    limit = MESSAGE_LIMIT - max(utf16_length(header), utf16_length(continuation)) - 2
    pages = []
    current = ""
    for block in blocks:
        parts = _oversized_block(block, limit) if utf16_length(block) > limit else [block]
        for part in parts:
            candidate = current + "\n\n" + part if current else part
            if utf16_length(candidate) > limit:
                pages.append(current)
                current = part
            else:
                current = candidate
    if current:
        pages.append(current)
    return [
        f"{header if index == 0 else continuation}\n\n{page}" for index, page in enumerate(pages)
    ]


def _course_names(items: list[dict], words: dict) -> dict[str, str]:
    names = {}
    for item in items:
        name = str(item.get("course_name") or f"{words['course']} {item.get('course_id', '')}")
        names[name] = re.split(r"\s+-\s+", name, maxsplit=1)[0].strip()
    duplicates = Counter(names.values())
    # Keep full names when shortening would make different courses look identical.
    return {name: short if duplicates[short] == 1 else name for name, short in names.items()}


def reminder_messages(report: dict, *, language: str = "en") -> list[str]:
    words = TEXT[notification_language(language)]
    timezone = ZoneInfo(report["timezone"])
    updates = report.get("updates")
    news = updates["items"] if updates else []
    due_items = report["assignments"]
    course_names = _course_names([*due_items, *news], words)
    context = f"{words['timezone']}: {report['timezone']}"
    news_context = context
    if updates:
        start = parse_datetime(updates["start_inclusive"]).astimezone(timezone)
        end = parse_datetime(updates["end_exclusive"]).astimezone(timezone)
        news_context = (
            f"{words['week']}: {start.strftime(words['short_date'])}"
            f" – {end.strftime(words['short_date'])}\n{context}"
        )

    def course(item):
        name = str(item.get("course_name") or f"{words['course']} {item.get('course_id', '')}")
        return course_names[name]

    def date(value):
        parsed = parse_datetime(value)
        return parsed.astimezone(timezone).strftime(words["date_format"]) if parsed else None

    def noun(name, count):
        return words[f"{name}_{'one' if count == 1 else 'many'}"]

    # An assignment with a deadline belongs to the deadline section only.
    due_urls = {item.get("html_url") for item in due_items if item.get("html_url")}
    due_ids = {
        (item.get("course_id"), item.get("id"))
        for item in due_items
        if item.get("course_id") is not None and item.get("id") is not None
    }
    grouped = {
        kind: []
        for kind in ("assignment", "announcement", "discussion", "materials", "calendar_event")
    }
    for item in news:
        kind = item["kind"]
        if kind == "assignment" and (
            item.get("html_url") in due_urls or (item.get("course_id"), item.get("id")) in due_ids
        ):
            continue
        grouped["materials" if kind in {"file", "page"} else kind].append(item)

    deadline_blocks = []
    for index, item in enumerate(due_items, 1):
        lines = [course(item), f"{index}. {item.get('name') or words['sources']['assignment']}"]
        due = date(item.get("due_at_local") or item.get("due_at"))
        if due:
            lines.append(f"{words['due']}: {due}")
        if item.get("html_url"):
            lines.append(item["html_url"])
        deadline_blocks.append("\n".join(lines))
    if not deadline_blocks:
        deadline_blocks.append(words["no_due"])
    if report.get("undated_count"):
        count = report["undated_count"]
        deadline_blocks.append(
            words["undated_assignments"].format(count=count, assignments=noun("assignment", count))
        )
    if due_items:
        deadline_blocks.append(words["help"])
    messages = _section(
        f"{words['deadlines']} ({len(due_items)})", context, deadline_blocks, words["continued"]
    )

    for kind, items in grouped.items():
        if not items:
            continue
        blocks = []
        for index, item in enumerate(items, 1):
            title = item["title"]
            if kind == "materials":
                title = f"{words[item['kind']]}: {title}"
            lines = [course(item), f"{index}. {title}"]
            changed = date(item["changed_at_local"])
            label = words["posted"] if kind == "announcement" else words["changed"]
            if changed:
                lines.append(f"{label}: {changed}")
            if item.get("starts_at_local"):
                lines.append(f"{words['starts']}: {date(item['starts_at_local'])}")
            lines.append(item["html_url"])
            blocks.append("\n".join(lines))
        messages.extend(
            _section(f"{words[kind]} ({len(items)})", news_context, blocks, words["continued"])
        )

    if updates is not None:
        notes = []
        if not news:
            notes.append(words["no_updates"])
        if updates["undated_count"]:
            count = updates["undated_count"]
            notes.append(words["undated_updates"].format(count=count, items=noun("item", count)))
        errors = updates["source_errors"]
        if errors:
            lines = [words["partial"]]
            for source in words["sources"]:
                courses = {
                    error.get("course_id", error.get("course_name"))
                    for error in errors
                    if error["source"] == source
                }
                if courses:
                    lines.append(
                        "• "
                        + words["unavailable"].format(
                            source=words["sources"][source],
                            count=len(courses),
                            courses=noun("course", len(courses)),
                        )
                    )
            lines.append(words["available"])
            notes.append("\n".join(lines))
        notes.append(words["repeated"])
        messages.extend(_section(words["status"], news_context, notes, words["continued"]))
    return messages
