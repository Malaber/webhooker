from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from webhooker.models import ProjectConfig


@pytest.fixture
def project_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project_id": "demo",
            "github": {
                "owner": "example",
                "repo": "repo",
                "token_env": "GITHUB_TOKEN",
                "webhook_secret_env": "GITHUB_WEBHOOK_SECRET",
            },
            "deployment": {
                "compose_file": "/tmp/compose.yml",
                "working_directory": str(tmp_path),
                "project_name_prefix": "demo-pr-",
                "preview_base_domain": "pr.example.test",
                "hostname_template": "{pr}.pr.example.test",
            },
            "image": {
                "registry": "ghcr.io",
                "repository": "example/repo",
                "tag_template": "pr-{pr}-{sha7}",
            },
            "preview": {
                "base_dir": str(tmp_path / "previews"),
                "data_dir_template": str(tmp_path / "previews" / "pr-{pr}"),
                "sqlite_path_template": str(tmp_path / "previews" / "pr-{pr}" / "app.db"),
                "seed_command": [],
            },
            "reconcile": {
                "poll_interval_seconds": 600,
                "cleanup_closed_prs": True,
                "redeploy_on_sha_change": True,
            },
            "traefik": {"certresolver": "letsencrypt", "enable_labels": True},
            "state": {"state_file": str(tmp_path / "state.json")},
            "wake": {"wake_file": str(tmp_path / "wake")},
        }
    )


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    config_path = tmp_path / "configs"
    config_path.mkdir()
    (config_path / "demo.yaml").write_text(
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
    return config_path
