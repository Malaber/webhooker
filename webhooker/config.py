from __future__ import annotations

import os
from pathlib import Path

import yaml

from webhooker.models import ProjectConfig



def load_project_config(path: str | Path) -> ProjectConfig:
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return ProjectConfig.model_validate(raw)



def load_project_configs(config_dir: str | Path) -> list[ProjectConfig]:
    config_path = Path(config_dir)
    return [load_project_config(path) for path in sorted(config_path.glob("*.yaml"))]



def env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value
