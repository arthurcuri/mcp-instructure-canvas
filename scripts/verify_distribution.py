"""Check release versions, archive contents and checksums; no credentials or network."""

import argparse
import hashlib
import json
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_names(names: list[str]) -> None:
    for name in names:
        parts = Path(name).parts
        if any(part in {".local", ".venv", "auth.json", "settings.local.json"} for part in parts):
            raise ValueError("The package contains a private path.")
        if any(part.startswith(".env") and part != ".env.example" for part in parts):
            raise ValueError("The package contains private configuration.")


def verify(directory: Path, version: str) -> dict:
    wheel = directory / f"mcp_instructure_canvas-{version}-py3-none-any.whl"
    source = directory / f"mcp_instructure_canvas-{version}.tar.gz"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        check_names(names)
        metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
        if metadata["Version"] != version or metadata["Name"] != "mcp-instructure-canvas":
            raise ValueError("Wheel version/name mismatch.")
        init = archive.read("canvas_mcp/__init__.py").decode()
        if f'__version__ = "{version}"' not in init:
            raise ValueError("Runtime version mismatch.")
        catalog = json.loads(archive.read("canvas_mcp/data/operations.json"))
        if catalog["operation_count"] != len(catalog["operations"]):
            raise ValueError("Incomplete catalog in the wheel.")
        wheel_count = len(names)
    with tarfile.open(source) as archive:
        names = archive.getnames()
        check_names(names)
        metadata_path = next(name for name in names if name.endswith("/PKG-INFO"))
        metadata = BytesParser().parsebytes(archive.extractfile(metadata_path).read())
        if metadata["Version"] != version:
            raise ValueError("Source distribution version mismatch.")
        source_count = len(names)
    sums = directory / "SHA256SUMS"
    sums.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (wheel, source)
        )
    )
    return {
        "version": version,
        "wheel_files": wheel_count,
        "source_files": source_count,
        "canvas_operations": catalog["operation_count"],
        "checksums": sums.name,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--tag")
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if args.tag and args.tag != "v" + version:
        raise ValueError("The tag does not match the project version.")
    if args.version_only:
        print(version)
    else:
        print(json.dumps(verify(args.dist, version), indent=2))


if __name__ == "__main__":
    main()
