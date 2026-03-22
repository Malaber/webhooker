from __future__ import annotations

import pathlib
import re
import sys


def replace_pattern(path: pathlib.Path, pattern: str, replacement: str) -> None:
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, original, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not update version in {path}")
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: stamp_version.py <version>")

    version = sys.argv[1]
    repo_root = pathlib.Path(__file__).resolve().parents[2]

    replace_pattern(
        repo_root / "pyproject.toml",
        r'^version = "[^"]+"$',
        f'version = "{version}"',
    )
    replace_pattern(
        repo_root / "ansible_collections/malaber/webhooker/galaxy.yml",
        r"^version:\s*[^\n]+$",
        f"version: {version}",
    )


if __name__ == "__main__":
    main()
