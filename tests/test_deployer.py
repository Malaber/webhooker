from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from webhooker.deployer import Deployer
from webhooker.models import DeployedPreview, PullRequestInfo



def test_deploy_preview_runs_compose_and_seed(
    project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(project_config)
    commands: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert cwd == project_config.deployment.working_directory
        commands.append((argv, env))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    project_config.preview.seed_command = ["echo", "{compose_project}"]

    deployed = deployer.deploy_preview(
        PullRequestInfo(number=3, head_sha="abcdef123456", state="open")
    )

    assert deployed.compose_project == "demo-pr-3"
    assert commands[0][0][:3] == ["docker", "compose", "-p"]
    assert commands[0][1]["APP_IMAGE"] == "ghcr.io/example/repo:pr-3-abcdef1"
    assert commands[1][0] == ["echo", "demo-pr-3"]


def test_remove_preview_runs_compose_down_and_deletes_data_dir(
    project_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployer = Deployer(project_config)
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

    deployer.remove_preview(
        DeployedPreview(
            pr=4,
            sha="abcdef0",
            compose_project="demo-pr-4",
            hostname="4.pr.example.test",
            data_dir=str(data_dir),
            image="ghcr.io/example/repo:pr-4-abcdef0",
        )
    )

    assert recorded[0][-3:] == ["down", "-v", "--remove-orphans"]
    assert not data_dir.exists()
