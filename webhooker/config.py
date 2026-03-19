from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from webhooker.models import ProjectConfig



def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(('"', "'")) and value.endswith(('"', "'")):
        return value[1:-1]
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if value.lstrip("-").isdigit():
        return int(value)
    return value



def _parse_block(lines: list[tuple[int, str]], index: int, indent: int):
    items: dict[str, Any] | list[Any] | None = None
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"Unexpected indentation near: {content}")

        if content.startswith("- "):
            if items is None:
                items = []
            if not isinstance(items, list):
                raise ValueError("Cannot mix mapping and list items")
            remainder = content[2:].strip()
            if remainder:
                items.append(_parse_scalar(remainder))
                index += 1
            else:
                child, index = _parse_block(lines, index + 1, indent + 2)
                items.append(child)
            continue

        key, sep, remainder = content.partition(":")
        if not sep:
            raise ValueError(f"Expected ':' in line: {content}")
        if items is None:
            items = {}
        if not isinstance(items, dict):
            raise ValueError("Cannot mix list and mapping items")
        if remainder.strip():
            items[key.strip()] = _parse_scalar(remainder.strip())
            index += 1
        else:
            if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                items[key.strip()] = {}
                index += 1
            else:
                child, index = _parse_block(lines, index + 1, indent + 2)
                items[key.strip()] = child
    return items if items is not None else {}, index



def _load_yaml_text(text: str) -> dict[str, Any]:
    prepared: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.split("#", 1)[0].rstrip()
        if not stripped:
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        prepared.append((indent, stripped.lstrip()))
    parsed, _ = _parse_block(prepared, 0, 0)
    if not isinstance(parsed, dict):
        raise ValueError("Top-level YAML document must be a mapping")
    return parsed



def load_project_config(path: str | Path) -> ProjectConfig:
    raw = _load_yaml_text(Path(path).read_text(encoding="utf-8"))
    return ProjectConfig.model_validate(raw)



def load_project_configs(config_dir: str | Path) -> list[ProjectConfig]:
    config_path = Path(config_dir)
    return [load_project_config(file) for file in sorted(config_path.glob("*.yaml"))]



def env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value
