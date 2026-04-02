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
    second = deployer.deploy_review(
        PullRequestInfo(number=3, head_sha="fedcba654321", state="open")
    )

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

    recorded: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        recorded.append((argv, env))
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

    assert recorded[0][0][-3:] == ["down", "-v", "--remove-orphans"]
    assert recorded[0][1]["APP_DATA_DIR"] == str(data_dir)
    assert recorded[0][1]["APP_HOSTNAME"] == "pr-4.review.example.test"
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

    commands: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append((argv, env))
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

    assert commands[0][0][-2:] == ["down", "--remove-orphans"]
    assert commands[0][1]["APP_IMAGE"] == "ghcr.io/example/repo:sha-oldsha1"
    assert commands[1][0][-3:] == ["up", "-d", "--remove-orphans"]
    assert deployed.image == "ghcr.io/example/repo:sha-abcdef1"
    assert len(backups) == 3


def test_production_first_deploy_seeds_without_backup(
    production_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(production_project_config)
    production = production_project_config.production
    assert production is not None
    production.seed_command = ["echo", "{compose_project}"]

    commands: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert cwd == production_project_config.deployment.working_directory
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    deployed = deployer.deploy_production("abcdef123456", previous=None)

    assert deployed.compose_project == "demo-production"
    assert commands[0][-3:] == ["up", "-d", "--remove-orphans"]
    assert commands[1] == ["echo", "demo-production"]


def test_deployment_fingerprint_changes_when_compose_env_file_changes(
    review_project_config,
    tmp_path: Path,
) -> None:
    compose_path = tmp_path / "compose.yml"
    env_path = tmp_path / "review.env"
    env_path.write_text("SECRET_KEY=first\n", encoding="utf-8")
    compose_path.write_text(
        """
services:
  app:
    env_file:
      - ./review.env
""".strip(),
        encoding="utf-8",
    )
    config = review_project_config.model_copy(deep=True)
    config.deployment.compose_file = str(compose_path)
    config.deployment.working_directory = str(tmp_path)
    deployer = Deployer(config)

    first = deployer.deployment_fingerprint()
    env_path.write_text("SECRET_KEY=second\n", encoding="utf-8")
    second = deployer.deployment_fingerprint()

    assert first != second


def test_deployment_fingerprint_supports_relative_missing_and_long_syntax_env_files(
    review_project_config,
    tmp_path: Path,
) -> None:
    compose_path = tmp_path / "compose.yml"
    nested_env = tmp_path / "nested.env"
    nested_env.write_text("TOKEN=demo\n", encoding="utf-8")
    compose_path.write_text(
        """
services:
  app:
    env_file:
      - ./missing.env
      - path: ./nested.env
  ignored: hello
""".strip(),
        encoding="utf-8",
    )
    config = review_project_config.model_copy(deep=True)
    config.deployment.compose_file = "compose.yml"
    config.deployment.working_directory = str(tmp_path)
    deployer = Deployer(config)

    fingerprint = deployer.deployment_fingerprint()
    input_paths = deployer._deployment_input_paths()

    assert fingerprint
    assert input_paths == [
        compose_path,
        tmp_path / "missing.env",
        nested_env,
    ]


def test_compose_env_file_paths_ignore_non_mapping_documents(
    review_project_config, tmp_path: Path
) -> None:
    compose_path = tmp_path / "compose.yml"
    compose_path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    config = review_project_config.model_copy(deep=True)
    config.deployment.compose_file = str(compose_path)
    deployer = Deployer(config)

    assert deployer._compose_env_file_paths(compose_path) == []


def test_compose_env_file_paths_ignore_missing_or_non_mapping_services(
    review_project_config,
    tmp_path: Path,
) -> None:
    no_services_compose = tmp_path / "no-services.yml"
    no_services_compose.write_text("services: hello\n", encoding="utf-8")
    config = review_project_config.model_copy(deep=True)
    config.deployment.compose_file = str(no_services_compose)
    deployer = Deployer(config)
    assert deployer._compose_env_file_paths(no_services_compose) == []

    service_list_compose = tmp_path / "service-list.yml"
    service_list_compose.write_text(
        """
services:
  app:
    env_file: ./review.env
  ignored:
    - not
    - a
    - mapping
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "review.env").write_text("VALUE=1\n", encoding="utf-8")
    config.deployment.compose_file = str(service_list_compose)

    assert deployer._compose_env_file_paths(service_list_compose) == [tmp_path / "review.env"]


def test_normalize_env_file_entries_returns_empty_for_unsupported_values(
    review_project_config,
) -> None:
    deployer = Deployer(review_project_config)

    assert deployer._normalize_env_file_entries(123) == []


def test_review_helper_guards_raise_when_preview_fields_are_missing(
    review_project_config,
) -> None:
    invalid_config = review_project_config.model_copy(
        update={
            "preview": None,
            "deployment": review_project_config.deployment.model_copy(
                update={"hostname_template": None}
            ),
        }
    )
    deployer = Deployer(invalid_config)

    with pytest.raises(RuntimeError):
        deployer.data_dir_for_pr(1)

    with pytest.raises(RuntimeError):
        deployer.hostname_for_pr(1)


def test_production_helper_guards_raise_when_mode_specific_fields_are_missing(
    production_project_config,
) -> None:
    deployer = Deployer(production_project_config.model_copy(update={"production": None}))

    with pytest.raises(RuntimeError):
        deployer.deploy_production("abcdef123456", previous=None)

    incomplete_config = production_project_config.model_copy(
        update={
            "deployment": production_project_config.deployment.model_copy(
                update={
                    "production_project_name": None,
                    "production_hostname": None,
                }
            )
        }
    )
    incomplete_deployer = Deployer(incomplete_config)

    with pytest.raises(RuntimeError):
        incomplete_deployer._production_project_name()

    with pytest.raises(RuntimeError):
        incomplete_deployer._production_hostname()


def test_seed_returns_immediately_when_command_is_empty(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)
    called = False

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    deployer._seed([], "demo-pr-1")

    assert called is False


def test_backup_sqlite_returns_when_database_is_missing(
    production_project_config,
    tmp_path: Path,
) -> None:
    deployer = Deployer(production_project_config)
    missing_sqlite = tmp_path / "missing.db"

    deployer._backup_sqlite(missing_sqlite)

    assert not missing_sqlite.exists()


def test_review_deploy_permission_error_explains_host_directory_requirement(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)

    def fake_ensure_dir(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr("webhooker.deployer.ensure_dir", fake_ensure_dir)

    with pytest.raises(PermissionError, match="mounted host directory"):
        deployer.deploy_review(PullRequestInfo(number=8, head_sha="abcdef123456", state="open"))


def test_production_backup_permission_error_explains_host_directory_requirement(
    production_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(production_project_config)
    production = production_project_config.production
    assert production is not None

    sqlite_path = Path(production.sqlite_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_path.write_text("db", encoding="utf-8")

    commands: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    def fake_ensure_dir(path: Path) -> None:
        if path == Path(production.backup_dir):
            raise PermissionError(13, "Permission denied", str(path))
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("webhooker.deployer.ensure_dir", fake_ensure_dir)

    with pytest.raises(PermissionError, match="production backup directory"):
        deployer.deploy_production(
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
