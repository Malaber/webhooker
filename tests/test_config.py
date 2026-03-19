from __future__ import annotations

import textwrap

import pytest
from webhooker.config import load_project_config
from webhooker.models import ValidationError


def test_valid_yaml_loads(tmp_path) -> None:
    config_file = tmp_path / "project.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            project_id: demo
            github:
              owner: example
              repo: repo
              token_env: GITHUB_TOKEN
              webhook_secret_env: GITHUB_WEBHOOK_SECRET
            deployment:
              compose_file: /tmp/compose.yml
              working_directory: /tmp
              project_name_prefix: demo-pr-
              preview_base_domain: pr.example.test
              hostname_template: "{pr}.pr.example.test"
            image:
              registry: ghcr.io
              repository: example/repo
              tag_template: "pr-{pr}-{sha7}"
            preview:
              base_dir: /tmp/previews
              data_dir_template: "/tmp/previews/pr-{pr}"
              sqlite_path_template: "/tmp/previews/pr-{pr}/app.db"
            reconcile:
              poll_interval_seconds: 600
            traefik:
              certresolver: letsencrypt
            state:
              state_file: /tmp/state.json
            wake:
              wake_file: /tmp/wake
            """
        ).strip(),
        encoding="utf-8",
    )

    config = load_project_config(config_file)

    assert config.project_id == "demo"
    assert config.github.repo == "repo"


def test_missing_required_fields_fail(tmp_path) -> None:
    config_file = tmp_path / "project.yaml"
    config_file.write_text("project_id: demo\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_project_config(config_file)
