from __future__ import annotations

import json
from pathlib import Path

from webhooker.deployer import Deployer
from webhooker.models import DeployedProduction, DeployedReview


def _write_fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    log_path = tmp_path / "docker-calls.jsonl"
    docker_path = tmp_path / "docker"
    docker_path.write_text(
        f"""#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

log_path = Path({str(log_path)!r})
record = {{
    "argv": sys.argv[1:],
    "env": {{
        "APP_IMAGE": os.environ.get("APP_IMAGE"),
        "APP_HOSTNAME": os.environ.get("APP_HOSTNAME"),
        "APP_DATA_DIR": os.environ.get("APP_DATA_DIR"),
        "APP_SQLITE_PATH": os.environ.get("APP_SQLITE_PATH"),
    }},
}}
with log_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(record, sort_keys=True) + "\\n")
""",
        encoding="utf-8",
    )
    docker_path.chmod(0o755)
    return docker_path, log_path


def _read_calls(log_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_review_removal_e2e_deletes_undeployed_commit_image(
    review_project_config,
    tmp_path: Path,
) -> None:
    docker_path, log_path = _write_fake_docker(tmp_path)
    review_project_config.deployment.compose_bin = str(docker_path)
    deployer = Deployer(review_project_config)
    data_dir = tmp_path / "review-data"
    data_dir.mkdir()

    deployer.remove_review(
        DeployedReview(
            pr=12,
            sha="abcdef123456",
            compose_project="demo-pr-12",
            hostname="pr-12.review.example.test",
            data_dir=str(data_dir),
            sqlite_path=str(data_dir / "app.db"),
            image="ghcr.io/example/repo:pr-12-abcdef1",
        )
    )

    calls = _read_calls(log_path)
    assert calls[0]["argv"] == [
        "compose",
        "-p",
        "demo-pr-12",
        "-f",
        review_project_config.deployment.compose_file,
        "down",
        "-v",
        "--remove-orphans",
    ]
    assert calls[0]["env"]["APP_IMAGE"] == "ghcr.io/example/repo:pr-12-abcdef1"
    assert calls[1]["argv"] == ["image", "rm", "ghcr.io/example/repo:pr-12-abcdef1"]
    assert not data_dir.exists()


def test_production_roll_forward_e2e_deletes_previous_commit_image(
    production_project_config,
    tmp_path: Path,
) -> None:
    docker_path, log_path = _write_fake_docker(tmp_path)
    production_project_config.deployment.compose_bin = str(docker_path)
    production = production_project_config.production
    assert production is not None
    sqlite_path = Path(production.sqlite_path)
    sqlite_path.parent.mkdir(parents=True)
    sqlite_path.write_text("db", encoding="utf-8")
    deployer = Deployer(production_project_config)

    deployed = deployer.deploy_production(
        "abcdef123456",
        previous=DeployedProduction(
            sha="oldsha123456",
            compose_project="demo-production",
            hostname="app.example.test",
            data_dir=production.data_dir,
            sqlite_path=production.sqlite_path,
            image="ghcr.io/example/repo:sha-oldsha1",
            branch="main",
        ),
    )

    calls = _read_calls(log_path)
    assert calls[0]["argv"][-2:] == ["down", "--remove-orphans"]
    assert calls[0]["env"]["APP_IMAGE"] == "ghcr.io/example/repo:sha-oldsha1"
    assert calls[1]["argv"] == ["image", "rm", "ghcr.io/example/repo:sha-oldsha1"]
    assert calls[2]["argv"][-3:] == ["up", "-d", "--remove-orphans"]
    assert calls[2]["env"]["APP_IMAGE"] == "ghcr.io/example/repo:sha-abcdef1"
    assert deployed.image == "ghcr.io/example/repo:sha-abcdef1"
