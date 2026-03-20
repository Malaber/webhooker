from __future__ import annotations

from pathlib import Path

from webhooker.models import ProjectState
from webhooker.paths import ensure_parent_dir


def load_state(path: str, project_id: str) -> ProjectState:
    state_path = Path(path)
    if not state_path.exists():
        return ProjectState(project_id=project_id)

    return ProjectState.model_validate_json(state_path.read_text(encoding="utf-8"))


def save_state(path: str, state: ProjectState) -> None:
    ensure_parent_dir(path)
    Path(path).write_text(state.model_dump_json(indent=2), encoding="utf-8")
