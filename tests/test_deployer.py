from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from webhooker.deployer import Deployer
from webhooker.models import DeployedProduction, DeployedReview, PullRequestInfo



def test_review_deploy_seeds_only_on_first_creation(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)
    commands: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert cwd == review_project_config.deployment.working_directory
        commands.append((argv, env))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert review_project_config.preview is not None
    review_project_config.preview.seed_command = ["echo", "{compose_project}"]

    first = deployer.deploy_review(PullRequestInfo(number=3, head_sha="abcdef123456", state="open"))
    second = deployer.deploy_review(PullRequestInfo(number=3, head_sha="fedcba654321", state="open"))

    assert first.compose_project == "demo-pr-3"
    assert second.sqlite_path == first.sqlite_path
    assert commands[0][0][:3] == ["docker", "compose", "-p"]
    assert commands[0][1]["APP_IMAGE"] == "ghcr.io/example/repo:pr-3-abcdef1"
    assert commands[1][0] == ["echo", "demo-pr-3"]
    assert len(commands) == 3



def test_remove_review_runs_compose_down_and_deletes_data_dir(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployer = Deployer(review_project_config)
    data_dir = tmp_path / "preview"
    data_dir.mkdir()
    (data_dir / "db.sqlite3").write_text("demo", encoding="utf-8")

    recorded: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        recorded.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    deployer.remove_review(
        DeployedReview(
            pr=4,
            sha="abcdef0",
            compose_project="demo-pr-4",
            hostname="pr-4.review.example.test",
            data_dir=str(data_dir),
            sqlite_path=str(data_dir / "db.sqlite3"),
            image="ghcr.io/example/repo:pr-4-abcdef0",
        )
    )

    assert recorded[0][-3:] == ["down", "-v", "--remove-orphans"]
    assert not data_dir.exists()



def test_production_deploy_backs_up_sqlite_and_keeps_three_versions(
    production_project_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployer = Deployer(production_project_config)
    production = production_project_config.production
    assert production is not None

    sqlite_path = Path(production.sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_path.write_text("db", encoding="utf-8")
    backup_dir = Path(production.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(1, 4):
        (backup_dir / f"app-2024010100000{idx}.db").write_text("old", encoding="utf-8")

    commands: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    deployed = deployer.deploy_production(
        "abcdef123456",
        previous=DeployedProduction(
            sha="oldsha1",
            compose_project="demo-production",
            hostname="app.example.test",
            data_dir=production.data_dir,
            sqlite_path=production.sqlite_path,
            image="ghcr.io/example/repo:sha-oldsha1",
            branch="main",
        ),
    )

    backups = sorted(backup_dir.glob("app-*.db"))

    assert commands[0][-2:] == ["down", "--remove-orphans"]
    assert commands[1][-3:] == ["up", "-d", "--remove-orphans"]
    assert deployed.image == "ghcr.io/example/repo:sha-abcdef1"
    assert len(backups) == 3
