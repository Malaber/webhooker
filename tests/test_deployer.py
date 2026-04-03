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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert cwd == review_project_config.deployment.working_directory
        assert kwargs.get("capture_output") is (argv[:2] == ["docker", "pull"])
        assert kwargs.get("text") is kwargs.get("capture_output")
        commands.append((argv, env))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert review_project_config.preview is not None
    review_project_config.preview.seed_command = ["echo", "{compose_project}"]

    first = deployer.deploy_review(PullRequestInfo(number=3, head_sha="abcdef123456", state="open"))
    Path(first.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    Path(first.sqlite_path).write_text("db", encoding="utf-8")
    second = deployer.deploy_review(
        PullRequestInfo(number=3, head_sha="fedcba654321", state="open"),
        previous=first,
    )

    assert first.compose_project == "demo-pr-3"
    assert second.sqlite_path == first.sqlite_path
    assert commands[0][0] == ["docker", "pull", "ghcr.io/example/repo:pr-3-abcdef1"]
    assert commands[1][0][:3] == ["docker", "compose", "-p"]
    assert commands[1][1]["APP_IMAGE"] == "ghcr.io/example/repo:pr-3-abcdef1"
    assert commands[2][0] == ["echo", "demo-pr-3"]
    assert commands[3][0] == ["docker", "pull", "ghcr.io/example/repo:pr-3-fedcba6"]
    assert commands[4][0][:3] == ["docker", "compose", "-p"]
    assert len(commands) == 5


def test_review_deploy_uses_placeholder_when_review_image_is_missing(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_path = Path(review_project_config.deployment.working_directory) / "compose.review.yml"
    compose_path.write_text(
        """
services:
  app:
    image: ${APP_IMAGE}
    labels:
      - traefik.enable=true
      - traefik.http.routers.${TRAEFIK_ROUTER}.rule=Host(`${APP_HOSTNAME}`)
      - traefik.http.services.${TRAEFIK_SERVICE}.loadbalancer.server.port=8000
    networks:
      - edge
networks:
  edge:
    external: true
""".strip(),
        encoding="utf-8",
    )
    review_project_config.deployment.compose_file = str(compose_path)
    deployer = Deployer(review_project_config)
    commands: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert kwargs.get("capture_output") is (argv[:2] == ["docker", "pull"])
        assert kwargs.get("text") is kwargs.get("capture_output")
        commands.append((argv, env))
        if argv[:2] == ["docker", "pull"]:
            raise subprocess.CalledProcessError(
                1,
                argv,
                stderr="manifest unknown: manifest unknown",
            )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    deployed = deployer.deploy_review(
        PullRequestInfo(number=9, head_sha="abcdef123456", state="open")
    )

    placeholder_dir = (
        Path(review_project_config.preview.base_dir) / ".webhooker-placeholder" / "pr-9"
    )
    placeholder_compose = placeholder_dir / "compose.yml"
    placeholder_html = placeholder_dir / "index.html"

    assert deployed.placeholder_active is True
    assert deployed.image == "ghcr.io/example/repo:pr-9-abcdef1"
    assert commands[0][0] == ["docker", "pull", "ghcr.io/example/repo:pr-9-abcdef1"]
    assert commands[1][0][:6] == [
        "docker",
        "compose",
        "-p",
        "demo-pr-9",
        "-f",
        str(placeholder_compose),
    ]
    assert placeholder_compose.exists()
    assert placeholder_html.exists()
    assert "webhooker is still loading your deployment for repo" in placeholder_html.read_text(
        encoding="utf-8"
    )
    assert "python:3.14-alpine" in placeholder_compose.read_text(encoding="utf-8")


def test_run_capture_uses_working_directory_and_returns_stdout(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert argv == ["docker", "compose", "ps"]
        assert cwd == review_project_config.deployment.working_directory
        assert env["EXTRA_FLAG"] == "1"
        assert check is True
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert deployer._run_capture(["docker", "compose", "ps"], env={"EXTRA_FLAG": "1"}) == "ok\n"


def test_compose_project_exists_returns_true_when_all_containers_are_running_and_healthy(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)

    def fake_run_capture(argv: list[str], env: dict[str, str] | None = None) -> str:
        del env
        assert argv[-4:] == ["ps", "--all", "--format", "json"]
        return "\n".join(
            [
                '{"Name":"demo-pr-5-app-1","State":"running","Health":"healthy"}',
                '{"Name":"demo-pr-5-sidecar-1","State":"running","Health":""}',
            ]
        )

    monkeypatch.setattr(deployer, "_run_capture", fake_run_capture)

    assert (
        deployer._compose_project_exists(
            "demo-pr-5",
            compose_file="/tmp/compose.yml",
            extra_env={"APP_IMAGE": "demo"},
        )
        is True
    )


def test_compose_project_exists_returns_false_when_ps_fails(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)

    def fake_run_capture(argv: list[str], env: dict[str, str] | None = None) -> str:
        del env
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(deployer, "_run_capture", fake_run_capture)

    assert (
        deployer._compose_project_exists(
            "demo-pr-5",
            compose_file="/tmp/compose.yml",
            extra_env={"APP_IMAGE": "demo"},
        )
        is False
    )


def test_compose_project_exists_returns_false_when_ps_is_empty(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)
    monkeypatch.setattr(deployer, "_run_capture", lambda argv, env=None: "\n \n")

    assert (
        deployer._compose_project_exists(
            "demo-pr-5",
            compose_file="/tmp/compose.yml",
            extra_env={"APP_IMAGE": "demo"},
        )
        is False
    )


def test_compose_project_exists_returns_false_when_container_is_not_running(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)
    monkeypatch.setattr(
        deployer,
        "_run_capture",
        lambda argv, env=None: '{"Name":"demo-pr-5-app-1","State":"restarting","Health":""}\n',
    )

    assert (
        deployer._compose_project_exists(
            "demo-pr-5",
            compose_file="/tmp/compose.yml",
            extra_env={"APP_IMAGE": "demo"},
        )
        is False
    )


def test_compose_project_exists_returns_false_when_container_is_unhealthy(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)
    monkeypatch.setattr(
        deployer,
        "_run_capture",
        lambda argv, env=None: '{"Name":"demo-pr-5-app-1","State":"running","Health":"unhealthy"}\n',
    )

    assert (
        deployer._compose_project_exists(
            "demo-pr-5",
            compose_file="/tmp/compose.yml",
            extra_env={"APP_IMAGE": "demo"},
        )
        is False
    )


def test_compose_project_exists_returns_false_for_non_object_json_lines(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)
    monkeypatch.setattr(deployer, "_run_capture", lambda argv, env=None: '"oops"\n')

    assert (
        deployer._compose_project_exists(
            "demo-pr-5",
            compose_file="/tmp/compose.yml",
            extra_env={"APP_IMAGE": "demo"},
        )
        is False
    )


def test_review_runtime_exists_returns_false_when_data_dir_is_missing(
    review_project_config,
) -> None:
    deployer = Deployer(review_project_config)

    assert (
        deployer.review_runtime_exists(
            DeployedReview(
                pr=7,
                sha="abcdef0",
                compose_project="demo-pr-7",
                hostname="pr-7.review.example.test",
                data_dir="/tmp/does-not-exist-pr-7",
                sqlite_path="/tmp/does-not-exist-pr-7/app.db",
                image="ghcr.io/example/repo:pr-7-abcdef0",
            )
        )
        is False
    )


def test_review_runtime_exists_checks_compose_project_when_data_dir_exists(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployer = Deployer(review_project_config)
    data_dir = tmp_path / "pr-7"
    data_dir.mkdir()
    recorded: dict[str, object] = {}

    def fake_compose_project_exists(
        compose_project: str,
        *,
        compose_file: str,
        extra_env: dict[str, str],
    ) -> bool:
        recorded["compose_project"] = compose_project
        recorded["compose_file"] = compose_file
        recorded["extra_env"] = extra_env
        return True

    monkeypatch.setattr(deployer, "_compose_project_exists", fake_compose_project_exists)

    assert (
        deployer.review_runtime_exists(
            DeployedReview(
                pr=7,
                sha="abcdef0",
                compose_project="demo-pr-7",
                hostname="pr-7.review.example.test",
                data_dir=str(data_dir),
                sqlite_path=str(data_dir / "app.db"),
                image="ghcr.io/example/repo:pr-7-abcdef0",
            )
        )
        is True
    )
    assert recorded["compose_project"] == "demo-pr-7"
    assert recorded["compose_file"] == review_project_config.deployment.compose_file


def test_production_runtime_exists_returns_false_when_data_dir_is_missing(
    production_project_config,
) -> None:
    deployer = Deployer(production_project_config)

    assert (
        deployer.production_runtime_exists(
            DeployedProduction(
                sha="abcdef0",
                compose_project="demo-production",
                hostname="app.example.test",
                data_dir="/tmp/does-not-exist-production",
                sqlite_path="/tmp/does-not-exist-production/app.db",
                image="ghcr.io/example/repo:sha-abcdef0",
                branch="main",
            )
        )
        is False
    )


def test_production_runtime_exists_returns_false_when_sqlite_parent_is_missing(
    production_project_config,
    tmp_path: Path,
) -> None:
    deployer = Deployer(production_project_config)
    data_dir = tmp_path / "production"
    data_dir.mkdir()

    assert (
        deployer.production_runtime_exists(
            DeployedProduction(
                sha="abcdef0",
                compose_project="demo-production",
                hostname="app.example.test",
                data_dir=str(data_dir),
                sqlite_path=str(tmp_path / "missing-parent" / "app.db"),
                image="ghcr.io/example/repo:sha-abcdef0",
                branch="main",
            )
        )
        is False
    )


def test_production_runtime_exists_checks_compose_project_when_paths_exist(
    production_project_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployer = Deployer(production_project_config)
    data_dir = tmp_path / "production"
    data_dir.mkdir()
    sqlite_parent = data_dir / "db"
    sqlite_parent.mkdir()
    recorded: dict[str, object] = {}

    def fake_compose_project_exists(
        compose_project: str,
        *,
        compose_file: str,
        extra_env: dict[str, str],
    ) -> bool:
        recorded["compose_project"] = compose_project
        recorded["compose_file"] = compose_file
        recorded["extra_env"] = extra_env
        return True

    monkeypatch.setattr(deployer, "_compose_project_exists", fake_compose_project_exists)

    assert (
        deployer.production_runtime_exists(
            DeployedProduction(
                sha="abcdef0",
                compose_project="demo-production",
                hostname="app.example.test",
                data_dir=str(data_dir),
                sqlite_path=str(sqlite_parent / "app.db"),
                image="ghcr.io/example/repo:sha-abcdef0",
                branch="main",
            )
        )
        is True
    )
    assert recorded["compose_project"] == "demo-production"
    assert recorded["compose_file"] == production_project_config.deployment.compose_file


def test_review_deploy_reraises_pull_errors_that_are_not_missing_images(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        if argv[:2] == ["docker", "pull"]:
            assert kwargs.get("capture_output") is True
            assert kwargs.get("text") is True
            raise subprocess.CalledProcessError(1, argv, stderr="tls handshake timeout")
        assert kwargs.get("capture_output") is False
        assert kwargs.get("text") is False
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        deployer.deploy_review(PullRequestInfo(number=9, head_sha="abcdef123456", state="open"))

    assert excinfo.value.stderr == "tls handshake timeout"


def test_review_deploy_seeds_when_replacing_placeholder_without_existing_sqlite(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployer = Deployer(review_project_config)
    commands: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        assert kwargs.get("capture_output") is (argv[:2] == ["docker", "pull"])
        assert kwargs.get("text") is kwargs.get("capture_output")
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert review_project_config.preview is not None
    review_project_config.preview.seed_command = ["echo", "{compose_project}"]

    deployed = deployer.deploy_review(
        PullRequestInfo(number=4, head_sha="abcdef123456", state="open"),
        previous=DeployedReview(
            pr=4,
            sha="abcdef123456",
            compose_project="demo-pr-4",
            hostname="pr-4.review.example.test",
            data_dir=deployer.data_dir_for_pr(4),
            sqlite_path=deployer.sqlite_path_for_pr(4),
            image="ghcr.io/example/repo:pr-4-abcdef1",
            placeholder_active=True,
        ),
    )

    assert deployed.placeholder_active is False
    assert commands[0] == ["docker", "pull", "ghcr.io/example/repo:pr-4-abcdef1"]
    assert commands[2] == ["echo", "demo-pr-4"]


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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("capture_output") is False
        assert kwargs.get("text") is False
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


def test_remove_review_uses_placeholder_compose_file_when_placeholder_is_active(
    review_project_config,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deployer = Deployer(review_project_config)
    data_dir = tmp_path / "preview"
    data_dir.mkdir()
    placeholder_dir = (
        Path(review_project_config.preview.base_dir) / ".webhooker-placeholder" / "pr-4"
    )
    placeholder_dir.mkdir(parents=True)
    placeholder_compose = placeholder_dir / "compose.yml"
    placeholder_compose.write_text("services: {}\n", encoding="utf-8")

    recorded: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: str,
        env: dict[str, str],
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        assert kwargs.get("capture_output") is False
        assert kwargs.get("text") is False
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
            placeholder_active=True,
        )
    )

    assert recorded[0][5] == str(placeholder_compose)
    assert not placeholder_dir.exists()


def test_placeholder_service_template_requires_mapping_document(review_project_config) -> None:
    compose_path = Path(review_project_config.deployment.working_directory) / "compose.review.yml"
    compose_path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    review_project_config.deployment.compose_file = str(compose_path)
    deployer = Deployer(review_project_config)

    with pytest.raises(RuntimeError, match="YAML mapping"):
        deployer._placeholder_service_template()


def test_placeholder_service_template_requires_services(review_project_config) -> None:
    compose_path = Path(review_project_config.deployment.working_directory) / "compose.review.yml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    review_project_config.deployment.compose_file = str(compose_path)
    deployer = Deployer(review_project_config)

    with pytest.raises(RuntimeError, match="at least one service"):
        deployer._placeholder_service_template()


def test_placeholder_service_template_rejects_non_mapping_services(review_project_config) -> None:
    compose_path = Path(review_project_config.deployment.working_directory) / "compose.review.yml"
    compose_path.write_text(
        """
services:
  app:
    - invalid
""".strip(),
        encoding="utf-8",
    )
    review_project_config.deployment.compose_file = str(compose_path)
    deployer = Deployer(review_project_config)

    with pytest.raises(RuntimeError, match="service entries must be YAML mappings"):
        deployer._placeholder_service_template()


def test_placeholder_service_template_prefers_traefik_labels_and_ignores_bad_networks(
    review_project_config,
) -> None:
    compose_path = Path(review_project_config.deployment.working_directory) / "compose.review.yml"
    compose_path.write_text(
        """
services:
  worker:
    image: worker
  app:
    image: ${APP_IMAGE}
    labels:
      traefik.enable: "true"
    networks:
      - edge
networks:
  - not-a-mapping
""".strip(),
        encoding="utf-8",
    )
    review_project_config.deployment.compose_file = str(compose_path)
    deployer = Deployer(review_project_config)

    service_template, top_level_networks = deployer._placeholder_service_template()

    assert service_template["networks"] == ["edge"]
    assert top_level_networks == {}
    assert deployer._service_uses_traefik({"traefik.enable": "true"}) is True


def test_placeholder_service_template_falls_back_to_first_service(
    review_project_config,
) -> None:
    compose_path = Path(review_project_config.deployment.working_directory) / "compose.review.yml"
    compose_path.write_text(
        """
services:
  app:
    image: ${APP_IMAGE}
    networks:
      - edge
""".strip(),
        encoding="utf-8",
    )
    review_project_config.deployment.compose_file = str(compose_path)
    deployer = Deployer(review_project_config)

    service_template, top_level_networks = deployer._placeholder_service_template()

    assert service_template["networks"] == ["edge"]
    assert top_level_networks == {}


def test_app_display_name_falls_back_to_project_id_when_repository_is_empty(
    review_project_config,
) -> None:
    review_project_config.image.repository = ""
    deployer = Deployer(review_project_config)

    assert deployer._app_display_name() == review_project_config.project_id


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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("capture_output") is False
        assert kwargs.get("text") is False
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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert cwd == production_project_config.deployment.working_directory
        assert kwargs.get("capture_output") is False
        assert kwargs.get("text") is False
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
        **kwargs: object,
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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("capture_output") is False
        assert kwargs.get("text") is False
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
