from __future__ import annotations

from pathlib import Path

from webhooker.models import DeployedReview, ProjectState
from webhooker.state import load_state, save_state



def test_empty_state_file_creates_default_state(tmp_path: Path) -> None:
    state = load_state(str(tmp_path / "missing.json"), project_id="demo")

    assert state.project_id == "demo"
    assert state.reviews == {}
    assert state.production is None



def test_saved_state_reloads_correctly(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    original = ProjectState(
        project_id="demo",
        reviews={
            12: DeployedReview(
                pr=12,
                sha="abcdef0",
                compose_project="demo-pr-12",
                hostname="pr-12.review.example.test",
                data_dir="/tmp/demo/12",
                sqlite_path="/tmp/demo/12/app.db",
                image="ghcr.io/example/repo:pr-12-abcdef0",
            )
        },
    )

    save_state(str(state_file), original)
    loaded = load_state(str(state_file), project_id="ignored")

    assert loaded == original
