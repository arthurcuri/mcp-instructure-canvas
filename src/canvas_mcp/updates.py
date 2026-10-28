"""Compact weekly course updates without changing Canvas state."""

from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from canvas_mcp.client import CanvasClient, CanvasError
from canvas_mcp.config import Settings
from canvas_mcp.service import parse_datetime


class CanvasUpdates:
    def __init__(self, settings: Settings, client: CanvasClient):
        self.client = client
        self.timezone = ZoneInfo(settings.timezone)
        self.origin = settings.api_url.removesuffix("/api/v1")

    def _date(self, value: object) -> datetime | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("Canvas returned an invalid update date.")
        return parse_datetime(value)

    def _item(self, kind: str, record: dict, course: dict, end: datetime) -> dict | None:
        if not isinstance(record, dict):
            raise ValueError("Canvas returned an invalid update record.")
        if record.get("published") is False or record.get("workflow_state") == "deleted":
            return None
        if kind == "file" and (record.get("hidden_for_user") or record.get("locked_for_user")):
            return None
        if kind == "discussion" and record.get("is_announcement"):
            return None
        publication = self._date(record.get("posted_at"))
        delayed = self._date(record.get("delayed_post_at"))
        if kind in {"announcement", "discussion"} and publication is None:
            return None
        if (publication and publication >= end) or (delayed and delayed >= end):
            return None
        fields = {
            "announcement": ("posted_at",),
            "discussion": ("posted_at", "last_reply_at"),
            "page": ("created_at", "updated_at"),
            "file": ("created_at", "updated_at", "modified_at"),
            "assignment": ("created_at", "updated_at"),
            "calendar_event": ("created_at", "updated_at"),
        }[kind]
        dates = [self._date(record.get(field)) for field in fields]
        changed = max((value for value in dates if value is not None), default=None)
        identifier = record.get("page_id") if kind == "page" else record.get("id")
        if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 1:
            raise ValueError("Canvas returned an invalid update ID.")
        course_id = course["id"]
        if kind in {"announcement", "discussion"}:
            path = f"courses/{course_id}/discussion_topics/{identifier}"
        elif kind == "page":
            slug = record.get("url")
            if not isinstance(slug, str) or not slug:
                raise ValueError("Canvas returned a page without a slug.")
            path = f"courses/{course_id}/pages/{quote(slug, safe='')}"
        elif kind == "calendar_event":
            path = f"calendar?event_id={identifier}&include_contexts=course_{course_id}"
        else:
            resource = "files" if kind == "file" else "assignments"
            path = f"courses/{course_id}/{resource}/{identifier}"
        title = record.get("title") or record.get("display_name") or record.get("name") or kind
        result = {
            "kind": kind,
            "id": identifier,
            "course_id": course_id,
            "course_name": course.get("name") or f"Course {course_id}",
            "title": str(title),
            "changed_at": changed.isoformat() if changed else None,
            "changed_at_local": changed.astimezone(self.timezone).isoformat() if changed else None,
            # Build institution links rather than exposing signed storage URLs.
            "html_url": f"{self.origin}/{path}",
        }
        if kind == "calendar_event":
            starts = self._date(record.get("start_at"))
            result["starts_at_local"] = (
                starts.astimezone(self.timezone).isoformat() if starts else None
            )
        return result

    async def collect(self, courses: list[dict], *, now: datetime) -> dict:
        if now.tzinfo is None:
            raise ValueError("The update window requires a timezone-aware current time.")
        current = now.astimezone(self.timezone)
        week_start = (current - timedelta(days=current.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start = week_start
        items = {}
        errors = []
        undated = 0
        for course in courses:
            course_id = course["id"]
            sources = (
                (
                    "announcement",
                    "announcements",
                    {
                        "context_codes[]": f"course_{course_id}",
                        "start_date": start.isoformat(),
                        "end_date": current.isoformat(),
                        "active_only": "true",
                    },
                ),
                (
                    "discussion",
                    f"courses/{course_id}/discussion_topics",
                    {"order_by": "recent_activity", "exclude_context_module_locked_topics": "true"},
                ),
                (
                    "page",
                    f"courses/{course_id}/pages",
                    {"sort": "updated_at", "order": "desc", "published": "true"},
                ),
                (
                    "file",
                    f"courses/{course_id}/files",
                    {"sort": "updated_at", "order": "desc"},
                ),
                (
                    "assignment",
                    f"courses/{course_id}/assignments",
                    {"override_assignment_dates": "true"},
                ),
                (
                    "calendar_event",
                    "calendar_events",
                    {
                        "context_codes[]": f"course_{course_id}",
                        "type": "event",
                        "start_date": week_start.isoformat(),
                        "end_date": (current + timedelta(days=7)).isoformat(),
                    },
                ),
            )
            for kind, path, params in sources:
                try:
                    records = await self.client.list(path, params)
                except CanvasError as error:
                    errors.append(
                        {
                            "course_id": course_id,
                            "course_name": course.get("name") or f"Course {course_id}",
                            "source": kind,
                            "error": str(error),
                        }
                    )
                    continue
                for record in records:
                    item = self._item(kind, record, course, current)
                    if item is None:
                        continue
                    changed = self._date(item["changed_at"])
                    if changed is None:
                        undated += 1
                    elif start <= changed < current:
                        items[kind, course_id, item["id"]] = item
        results = sorted(items.values(), key=lambda item: self._date(item["changed_at"]))
        return {
            "start_inclusive": start.isoformat(),
            "end_exclusive": current.isoformat(),
            "count": len(results),
            "items": results,
            "undated_count": undated,
            "complete": not errors,
            "source_errors": errors,
        }
