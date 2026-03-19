from __future__ import annotations

from webhooker.models import DeployedPreview, ProjectState
from webhooker.state import load_state, save_state


def test_empty_state_file_creates_default_state(tmp_path) -> None:
    state = load_state(str(tmp_path / "missing.json"), project_id="demo")

    assert state.project_id == "demo"
    assert state.deployed == {}


def test_saved_state_reloads_correctly(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    original = ProjectState(
        project_id="demo",
        deployed={
            12: DeployedPreview(
                pr=12,
                sha="abcdef0",
                compose_project="demo-pr-12",
                hostname="12.pr.example.test",
                data_dir="/tmp/demo/12",
                image="ghcr.io/example/repo:pr-12-abcdef0",
            )
        },
    )

    save_state(str(state_file), original)
    loaded = load_state(str(state_file), project_id="ignored")

    assert loaded == original
