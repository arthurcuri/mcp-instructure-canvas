"""Student-focused queries with compact summaries and explicit local date boundaries."""

from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from canvas_mcp.client import CanvasClient
from canvas_mcp.config import Settings
from canvas_mcp.content import html_to_text


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Canvas returned an invalid date.") from None
    if parsed.tzinfo is None:
        raise ValueError("Canvas returned a date without a timezone.")
    return parsed


class CanvasService:
    def __init__(self, settings: Settings, client: CanvasClient):
        self.settings = settings
        self.client = client
        self.timezone = ZoneInfo(settings.timezone)

    def course_id(self, value: int | None) -> int:
        result = value if value is not None else self.settings.default_course_id
        if result is None or isinstance(result, bool) or result < 1:
            raise ValueError("Provide a positive course_id or set CANVAS_DEFAULT_COURSE_ID.")
        return result

    def _assignment(self, item: dict, *, description: bool = False) -> dict:
        submission = item.get("submission") or {}
        due = parse_datetime(item.get("due_at"))
        completed = bool(
            submission.get("excused")
            or submission.get("submitted_at")
            or submission.get("workflow_state") in {"submitted", "pending_review"}
            or (submission.get("workflow_state") == "graded" and not submission.get("missing"))
        )
        result = {
            "id": item.get("id"),
            "course_id": item.get("course_id"),
            "name": item.get("name"),
            "due_at": item.get("due_at"),
            "due_at_local": due.astimezone(self.timezone).isoformat() if due else None,
            "html_url": item.get("html_url"),
            "points_possible": item.get("points_possible"),
            "submission_types": item.get("submission_types", []),
            "locked_for_user": item.get("locked_for_user", False),
            "submission_status": submission.get("workflow_state"),
            "submitted_at": submission.get("submitted_at"),
            "completed": completed,
            "missing": submission.get("missing"),
            "late": submission.get("late"),
            "excused": submission.get("excused"),
        }
        if description:
            result.update(
                description=html_to_text(item.get("description")),
                description_complete=True,
                unlock_at=item.get("unlock_at"),
                lock_at=item.get("lock_at"),
                lock_explanation=html_to_text(item.get("lock_explanation")),
                rubric=item.get("rubric"),
            )
        return result

    async def list_courses(self, include_completed: bool = False) -> dict:
        params = {} if include_completed else {"enrollment_state": "active"}
        courses = await self.client.list("courses", params)
        fields = ("id", "name", "course_code", "workflow_state", "time_zone")
        results = [{key: item.get(key) for key in fields} for item in courses]
        return {"count": len(results), "courses": results}

    async def get_course(self, course_id: int | None = None) -> dict:
        course_id = self.course_id(course_id)
        item = await self.client.get(f"courses/{course_id}", {"include[]": "syllabus_body"})
        fields = ("id", "name", "course_code", "workflow_state", "time_zone", "start_at", "end_at")
        return {
            **{key: item.get(key) for key in fields},
            "syllabus": html_to_text(item.get("syllabus_body")),
            "html_url": f"{self.settings.api_url.removesuffix('/api/v1')}/courses/{course_id}",
        }

    async def _assignments(self, course_id: int, search: str | None = None) -> list[dict]:
        params = {"include[]": "submission", "override_assignment_dates": "true"}
        if search:
            params["search_term"] = search
        return await self.client.list(f"courses/{course_id}/assignments", params)

    async def list_assignments(
        self, course_id: int | None = None, search: str | None = None
    ) -> dict:
        course_id = self.course_id(course_id)
        items = [self._assignment(item) for item in await self._assignments(course_id, search)]
        items.sort(key=lambda item: (item["due_at"] is None, parse_datetime(item["due_at"])))
        return {"course_id": course_id, "count": len(items), "assignments": items}

    async def get_assignment(self, assignment_id: int, course_id: int | None = None) -> dict:
        course_id = self.course_id(course_id)
        if isinstance(assignment_id, bool) or assignment_id < 1:
            raise ValueError("assignment_id must be a positive integer.")
        item = await self.client.get(
            f"courses/{course_id}/assignments/{assignment_id}", {"include[]": "submission"}
        )
        return self._assignment(item, description=True)

    async def get_due_assignments(
        self,
        course_id: int | None = None,
        period: Literal["this_week", "next_7_days"] = "this_week",
        include_completed: bool = False,
        all_courses: bool = False,
        *,
        now: datetime | None = None,
    ) -> dict:
        if all_courses and course_id is not None:
            raise ValueError("Use either course_id or all_courses, without combining them.")
        current = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        if period == "this_week":
            start = (current - timedelta(days=current.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif period == "next_7_days":
            start = current
        else:
            raise ValueError("period must be this_week or next_7_days.")
        end = start + timedelta(days=7)
        if all_courses:
            courses = (await self.list_courses())["courses"]
        else:
            courses = [{"id": self.course_id(course_id)}]

        items = []
        undated_count = 0
        excluded_completed_count = 0
        for course in courses:
            for assignment in await self._assignments(self.course_id(course["id"])):
                due = parse_datetime(assignment.get("due_at"))
                if due is None:
                    undated_count += 1
                    continue
                if not start <= due < end:
                    continue
                item = self._assignment(assignment)
                if item["completed"] and not include_completed:
                    excluded_completed_count += 1
                    continue
                if course.get("name"):
                    item["course_name"] = course["name"]
                items.append(item)
        items.sort(key=lambda item: parse_datetime(item["due_at"]))
        return {
            "period": period,
            "timezone": self.settings.timezone,
            "start_inclusive": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "checked_at": current.isoformat(),
            "courses_checked": [course["id"] for course in courses],
            "count": len(items),
            "undated_count": undated_count,
            "excluded_completed_count": excluded_completed_count,
            "assignments": items,
        }

    async def list_modules(self, course_id: int | None = None) -> dict:
        course_id = self.course_id(course_id)
        modules = await self.client.list(f"courses/{course_id}/modules")
        result = []
        for module in modules:
            items = await self.client.list(f"courses/{course_id}/modules/{module['id']}/items")
            fields = ("id", "title", "type", "content_id", "page_url", "html_url", "external_url")
            result.append(
                {
                    "id": module["id"],
                    "name": module.get("name"),
                    "position": module.get("position"),
                    "items": [{key: item.get(key) for key in fields} for item in items],
                }
            )
        return {"course_id": course_id, "count": len(result), "modules": result}

    async def list_pages(self, course_id: int | None = None) -> dict:
        course_id = self.course_id(course_id)
        pages = await self.client.list(f"courses/{course_id}/pages")
        fields = ("page_id", "url", "title", "html_url", "updated_at")
        return {
            "course_id": course_id,
            "count": len(pages),
            "pages": [{key: item.get(key) for key in fields} for item in pages],
        }

    async def get_page(self, page_url: str, course_id: int | None = None) -> dict:
        course_id = self.course_id(course_id)
        if not page_url or any(char in page_url for char in "/%?#") or page_url in {".", ".."}:
            raise ValueError("page_url must be a slug returned by list_pages or list_modules.")
        item = await self.client.get(f"courses/{course_id}/pages/{quote(page_url, safe='-')}")
        return {
            "course_id": course_id,
            "page_id": item.get("page_id"),
            "title": item.get("title"),
            "html_url": item.get("html_url"),
            "updated_at": item.get("updated_at"),
            "body": html_to_text(item.get("body")),
            "body_complete": True,
            "locked_for_user": item.get("locked_for_user", False),
        }
