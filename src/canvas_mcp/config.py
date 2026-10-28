"""Explicit local configuration; credentials never appear in diagnostics."""

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values


class ConfigurationError(ValueError):
    """Invalid or missing local settings."""


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_token: str = field(repr=False)
    default_course_id: int | None = None
    timezone: str = "America/Sao_Paulo"
    token_expires_at: date | None = None
    read_only: bool = False

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        path = env_file if env_file is not None else Path.cwd() / ".env"
        if env_file is not None and not path.is_file():
            raise ConfigurationError("The file specified by --env-file does not exist.")
        values = dotenv_values(path, interpolate=False) if path.is_file() else {}

        def read(name: str, default: str = "") -> str:
            return str(os.environ.get(name, values.get(name) or default)).strip()

        raw_url = read("CANVAS_API_URL")
        try:
            url = urlsplit(raw_url)
            valid = (
                url.scheme == "https"
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
                and url.path.rstrip("/") in {"", "/api/v1"}
            )
            # Accessing port also validates malformed port values.
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise ConfigurationError(
                "CANVAS_API_URL must be your institution's HTTPS URL, with or without /api/v1."
            )
        api_url = urlunsplit(("https", url.netloc, "/api/v1", "", ""))
        token = read("CANVAS_API_TOKEN")
        if not token or any(char.isspace() for char in token):
            raise ConfigurationError("Set CANVAS_API_TOKEN to a valid token in .env.")

        course = read("CANVAS_DEFAULT_COURSE_ID")
        if course and (not course.isdecimal() or int(course) < 1):
            raise ConfigurationError("CANVAS_DEFAULT_COURSE_ID must be a positive integer.")
        timezone = read("CANVAS_TIMEZONE", "America/Sao_Paulo")
        try:
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ConfigurationError("CANVAS_TIMEZONE must be a valid IANA timezone.") from None
        expiry = read("CANVAS_TOKEN_EXPIRES_AT")
        try:
            expires_at = date.fromisoformat(expiry) if expiry else None
        except ValueError:
            raise ConfigurationError("CANVAS_TOKEN_EXPIRES_AT must use YYYY-MM-DD.") from None
        read_only = read("CANVAS_READ_ONLY", "false").lower()
        if read_only not in {"true", "false", "1", "0"}:
            raise ConfigurationError("CANVAS_READ_ONLY must be true or false.")
        return cls(
            api_url,
            token,
            int(course) if course else None,
            timezone,
            expires_at,
            read_only in {"true", "1"},
        )

    def public_info(self) -> dict:
        today = datetime.now(ZoneInfo(self.timezone)).date()
        return {
            "api_url": self.api_url,
            "token_configured": bool(self.api_token),
            "token_expires_at": self.token_expires_at.isoformat()
            if self.token_expires_at
            else None,
            "days_until_declared_expiry": (
                (self.token_expires_at - today).days if self.token_expires_at else None
            ),
            "default_course_id": self.default_course_id,
            "timezone": self.timezone,
            "transport": "stdio",
            "read_only": self.read_only,
        }
