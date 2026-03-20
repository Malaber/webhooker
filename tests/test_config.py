from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from webhooker.config import env_required, load_project_config, load_project_configs



def test_valid_review_yaml_loads(tmp_path: Path) -> None:
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
              mode: review
              compose_file: /tmp/compose.yml
              working_directory: /tmp
              project_name_prefix: demo-pr-
              preview_base_domain: review.example.test
              hostname_template: "pr-{pr}.review.example.test"
            image:
              registry: ghcr.io
              repository: example/repo
              tag_template: "pr-{pr}-{sha7}"
            preview:
              base_dir: /tmp/reviews
              data_dir_template: "/tmp/reviews/pr-{pr}"
              sqlite_path_template: "/tmp/reviews/pr-{pr}/app.db"
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
    assert config.deployment.mode == "review"



def test_valid_production_yaml_loads(tmp_path: Path) -> None:
    config_file = tmp_path / "production.yaml"
    config_file.write_text(
        textwrap.dedent(
            """
            project_id: production-demo
            github:
              owner: example
              repo: repo
              token_env: GITHUB_TOKEN
              webhook_secret_env: GITHUB_WEBHOOK_SECRET
              required_event_types: [push, ping]
            deployment:
              mode: production
              compose_file: /tmp/compose.yml
              working_directory: /tmp
              project_name_prefix: demo-
              production_project_name: demo-production
              production_hostname: app.example.test
            image:
              registry: ghcr.io
              repository: example/repo
              tag_template: "unused"
              production_tag_template: "sha-{sha7}"
            production:
              branch: main
              data_dir: /tmp/production
              sqlite_path: /tmp/production/app.db
              backup_dir: /tmp/production/backups
              backup_keep: 3
            reconcile:
              poll_interval_seconds: 600
              cleanup_closed_prs: false
            traefik:
              certresolver: letsencrypt
            state:
              state_file: /tmp/production-state.json
            wake:
              wake_file: /tmp/production-wake
            """
        ).strip(),
        encoding="utf-8",
    )

    config = load_project_config(config_file)

    assert config.project_id == "production-demo"
    assert config.deployment.mode == "production"
    assert config.production is not None



def test_missing_required_fields_fail(tmp_path: Path) -> None:
    config_file = tmp_path / "project.yaml"
    config_file.write_text("project_id: demo\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_project_config(config_file)



def test_load_project_configs_reads_all_yaml_files(config_dir: Path) -> None:
    configs = load_project_configs(config_dir)

    assert [config.project_id for config in configs] == ["review-demo"]



def test_env_required_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN", "present")

    assert env_required("TOKEN") == "present"



def test_env_required_raises_for_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN", raising=False)

    with pytest.raises(RuntimeError):
        env_required("TOKEN")
