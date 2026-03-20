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


def test_review_state_string_keys_are_normalized(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"project_id":"demo","reviews":{"7":{"pr":7,"sha":"abcdef0","compose_project":"demo-pr-7","hostname":"pr-7.review.example.test","data_dir":"/tmp/demo/pr-7","sqlite_path":"/tmp/demo/pr-7/app.db","image":"ghcr.io/example/repo:pr-7-abcdef0"}}}',
        encoding="utf-8",
    )

    state = load_state(str(state_file), project_id="ignored")

    assert 7 in state.reviews


def test_non_mapping_review_state_value_is_left_unchanged() -> None:
    assert ProjectState.normalize_review_keys(["not", "a", "dict"]) == ["not", "a", "dict"]
