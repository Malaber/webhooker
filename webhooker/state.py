from __future__ import annotations

import logging
from pathlib import Path

from pydantic import ValidationError

from webhooker.models import ProjectState
from webhooker.paths import ensure_parent_dir

logger = logging.getLogger(__name__)


def load_state(path: str, project_id: str) -> ProjectState:
    state_path = Path(path)
    if not state_path.exists():
        return ProjectState(project_id=project_id)

    raw_state = state_path.read_text(encoding="utf-8")
    if not raw_state.strip():
        logger.warning(
            "State file is empty; reinitializing state project_id=%s path=%s",
            project_id,
            state_path,
        )
        return ProjectState(project_id=project_id)

    try:
        return ProjectState.model_validate_json(raw_state)
    except ValidationError:
        preview = raw_state[:160].replace("\n", "\\n")
        logger.exception(
            "Failed to parse state file project_id=%s path=%s bytes=%s preview=%r",
            project_id,
            state_path,
            len(raw_state.encode("utf-8")),
            preview,
        )
        raise


def save_state(path: str, state: ProjectState) -> None:
    ensure_parent_dir(path)
    Path(path).write_text(state.model_dump_json(indent=2), encoding="utf-8")
