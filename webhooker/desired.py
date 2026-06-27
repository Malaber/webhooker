from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from webhooker.paths import ensure_parent_dir


class DesiredProjectSelection(BaseModel):
    enabled: bool = True
    review_prs: list[int] | None = None


class DesiredDeployments(BaseModel):
    projects: dict[str, DesiredProjectSelection] = Field(default_factory=dict)


def desired_deployments_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "desired-deployments.json"


def load_desired_deployments(path: str | Path) -> DesiredDeployments:
    selection_path = Path(path)
    if not selection_path.exists():
        return DesiredDeployments()
    raw = selection_path.read_text(encoding="utf-8")
    if not raw.strip():
        return DesiredDeployments()
    return DesiredDeployments.model_validate_json(raw)


def save_desired_deployments(path: str | Path, desired: DesiredDeployments) -> None:
    ensure_parent_dir(path)
    Path(path).write_text(desired.model_dump_json(indent=2), encoding="utf-8")


def project_selection(desired: DesiredDeployments, project_id: str) -> DesiredProjectSelection:
    return desired.projects.get(project_id, DesiredProjectSelection())
