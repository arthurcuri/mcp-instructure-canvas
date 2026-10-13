"""Prepare a private launchd configuration without installing or activating it."""

import argparse
import plistlib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-courses", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    template = root / "automation/launchd/com.canvas-mcp.weekly.plist.example"
    job = plistlib.loads(template.read_bytes())
    job["ProgramArguments"][1] = str(root / "automation/run_weekly.sh")
    if args.all_courses:
        job["ProgramArguments"].append("--all-courses")
    job["WorkingDirectory"] = str(root)
    job["StandardOutPath"] = str(root / ".local/weekly.log")
    job["StandardErrorPath"] = str(root / ".local/weekly-error.log")
    directory = root / ".local"
    directory.mkdir(mode=0o700, exist_ok=True)
    destination = directory / "com.canvas-mcp.weekly.plist"
    destination.write_bytes(plistlib.dumps(job))
    destination.chmod(0o600)
    print(f"Modelo preparado em {destination}. O agendamento não foi ativado.")


if __name__ == "__main__":
    main()
