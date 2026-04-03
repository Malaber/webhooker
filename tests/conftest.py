from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from webhooker.models import ProjectConfig


@pytest.fixture
def review_project_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project_id": "review-demo",
            "github": {
                "owner": "example",
                "repo": "repo",
                "token_env": "GITHUB_TOKEN",
                "webhook_secret_env": "GITHUB_WEBHOOK_SECRET",
            },
            "deployment": {
                "mode": "review",
                "compose_file": "/tmp/compose.yml",
                "working_directory": str(tmp_path),
                "project_name_prefix": "demo-pr-",
                "preview_base_domain": "review.example.test",
                "hostname_template": "pr-{pr}.review.example.test",
            },
            "image": {
                "registry": "ghcr.io",
                "repository": "example/repo",
                "tag_template": "pr-{pr}-{sha7}",
            },
            "preview": {
                "base_dir": str(tmp_path / "reviews"),
                "data_dir_template": str(tmp_path / "reviews" / "pr-{pr}"),
                "sqlite_path_template": str(tmp_path / "reviews" / "pr-{pr}" / "app.db"),
                "seed_command": [],
            },
            "reconcile": {
                "poll_interval_seconds": 600,
                "cleanup_closed_prs": True,
                "redeploy_on_sha_change": True,
            },
            "traefik": {"certresolver": "letsencrypt", "enable_labels": True},
            "state": {"state_file": str(tmp_path / "review-state.json")},
            "wake": {"wake_file": str(tmp_path / "review-wake")},
        }
    )


@pytest.fixture
def production_project_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project_id": "production-demo",
            "github": {
                "owner": "example",
                "repo": "repo",
                "token_env": "GITHUB_TOKEN",
                "webhook_secret_env": "GITHUB_WEBHOOK_SECRET",
                "required_event_types": ["push", "ping"],
            },
            "deployment": {
                "mode": "production",
                "compose_file": "/tmp/compose.yml",
                "working_directory": str(tmp_path),
                "project_name_prefix": "demo-",
                "production_project_name": "demo-production",
                "production_hostname": "app.example.test",
            },
            "image": {
                "registry": "ghcr.io",
                "repository": "example/repo",
                "tag_template": "unused",
                "production_tag_template": "sha-{sha7}",
            },
            "production": {
                "branch": "main",
                "data_dir": str(tmp_path / "production"),
                "sqlite_path": str(tmp_path / "production" / "app.db"),
                "backup_dir": str(tmp_path / "production" / "backups"),
                "backup_keep": 3,
                "backup_max_age_days": None,
                "seed_command": [],
            },
            "reconcile": {
                "poll_interval_seconds": 600,
                "cleanup_closed_prs": False,
                "redeploy_on_sha_change": True,
            },
            "traefik": {"certresolver": "letsencrypt", "enable_labels": True},
            "state": {"state_file": str(tmp_path / "production-state.json")},
            "wake": {"wake_file": str(tmp_path / "production-wake")},
        }
    )


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    config_path = tmp_path / "configs"
    config_path.mkdir()
    (config_path / "review-demo.yaml").write_text(
        textwrap.dedent("""
            project_id: review-demo
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
              state_file: /tmp/review-state.json
            wake:
              wake_file: /tmp/review-wake
            """).strip(),
        encoding="utf-8",
    )
    return config_path
