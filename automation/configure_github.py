"""Copy only the three reminder credentials to GitHub Secrets; optionally activate the daily job."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from canvas_mcp.config import Settings
from canvas_mcp.notifications import TelegramSettings


def github(arguments: list[str], value: str | None = None) -> None:
    try:
        result = subprocess.run(
            ["gh", *arguments],
            input=value,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Could not run GitHub CLI; check gh auth status.") from None
    if result.returncode:
        raise ValueError(
            "GitHub rejected the configuration. Check your account and repository permissions."
        )


def configure(repository: str, env_file: Path, activate: bool) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Provide the repository as owner/name.")
    canvas = Settings.load(env_file)
    telegram = TelegramSettings.load(env_file)
    # stdin prevents credentials appearing in argv, shell history or command output.
    for name, value in {
        "CANVAS_API_TOKEN": canvas.api_token,
        "TELEGRAM_BOT_TOKEN": telegram.token,
        "TELEGRAM_CHAT_ID": telegram.chat_id,
    }.items():
        github(["secret", "set", name, "--repo", repository], value)
    for name, value in {
        "CANVAS_API_URL": canvas.api_url,
        "CANVAS_TIMEZONE": canvas.timezone,
    }.items():
        github(["variable", "set", name, "--repo", repository, "--body", value])
    if activate:
        github(
            ["variable", "set", "CANVAS_WEEKLY_ENABLED", "--repo", repository, "--body", "false"]
        )
        github(["variable", "set", "CANVAS_DAILY_ENABLED", "--repo", repository, "--body", "true"])
    return {"repository": repository, "secrets_configured": 3, "daily_enabled": activate}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--env-file", type=Path, default=Path.cwd() / ".env")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(configure(args.repo, args.env_file, args.activate), indent=2))
    except (OSError, ValueError) as error:
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "Could not read the private configuration."
        )
        parser.exit(1, message + "\n")


if __name__ == "__main__":
    main()
