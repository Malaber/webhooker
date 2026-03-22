from __future__ import annotations

from pathlib import Path

from webhooker.config import load_project_config


def test_generic_review_example_project_loads() -> None:
    path = Path(
        "ansible_collections/malaber/webhooker/examples/generic/projects/example-app-review.yaml"
    )

    config = load_project_config(path)

    assert config.project_id == "example-app-review"
    assert config.deployment.mode == "review"
    assert config.preview is not None


def test_generic_production_example_project_loads() -> None:
    path = Path(
        "ansible_collections/malaber/webhooker/examples/generic/projects/example-app-production.yaml"
    )

    config = load_project_config(path)

    assert config.project_id == "example-app-production"
    assert config.deployment.mode == "production"
    assert config.production is not None
