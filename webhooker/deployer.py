from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from webhooker.models import (
    DeployedProduction,
    DeployedReview,
    PreviewConfig,
    ProductionConfig,
    ProjectConfig,
    PullRequestInfo,
)
from webhooker.paths import ensure_dir

logger = logging.getLogger(__name__)


class Deployer:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    def compose_project_name(self, pr: int) -> str:
        return f"{self.config.deployment.project_name_prefix}{pr}"

    def hostname_for_pr(self, pr: int) -> str:
        template = self.config.deployment.hostname_template
        if template is None:
            raise RuntimeError("hostname_template is required for review deployments")
        return template.format(pr=pr)

    def review_image_for_pr(self, pr: int, sha: str) -> str:
        sha7 = sha[:7]
        tag = self.config.image.tag_template.format(pr=pr, sha=sha, sha7=sha7)
        return f"{self.config.image.registry}/{self.config.image.repository}:{tag}"

    def production_image_for_sha(self, sha: str) -> str:
        sha7 = sha[:7]
        tag_template = self.config.image.production_tag_template or self.config.image.tag_template
        tag = tag_template.format(sha=sha, sha7=sha7)
        return f"{self.config.image.registry}/{self.config.image.repository}:{tag}"

    def data_dir_for_pr(self, pr: int) -> str:
        preview = self._preview_config()
        return preview.data_dir_template.format(pr=pr)

    def sqlite_path_for_pr(self, pr: int) -> str:
        preview = self._preview_config()
        return preview.sqlite_path_template.format(pr=pr)

    def _preview_config(self) -> PreviewConfig:
        if self.config.preview is None:
            raise RuntimeError("preview configuration is required for review deployments")
        return self.config.preview

    def _production_config(self) -> ProductionConfig:
        if self.config.production is None:
            raise RuntimeError("production configuration is required for production deployments")
        return self.config.production

    def _run(self, argv: list[str], env: dict[str, str] | None = None) -> None:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        subprocess.run(
            argv,
            cwd=self.config.deployment.working_directory,
            env=merged_env,
            check=True,
        )

    def _ensure_dir(self, path: Path, purpose: str) -> None:
        try:
            ensure_dir(path)
        except PermissionError as exc:
            message = (
                f"Permission denied creating {purpose} at {path}. "
                "The mounted host directory must already exist and be writable by the "
                "unprivileged webhooker container user."
            )
            raise PermissionError(message) from exc

    def _compose_env(
        self,
        *,
        image: str,
        hostname: str,
        data_dir: str,
        sqlite_path: str,
        traefik_router: str,
        traefik_service: str,
    ) -> dict[str, str]:
        return {
            "APP_IMAGE": image,
            "APP_HOSTNAME": hostname,
            "APP_DATA_DIR": data_dir,
            "APP_SQLITE_PATH": sqlite_path,
            "TRAEFIK_ROUTER": traefik_router,
            "TRAEFIK_SERVICE": traefik_service,
            "TRAEFIK_CERTRESOLVER": self.config.traefik.certresolver,
        }

    def _compose_up(self, compose_project: str, extra_env: dict[str, str]) -> None:
        logger.info("Deploying compose project=%s", compose_project)
        self._run(
            [
                self.config.deployment.compose_bin,
                "compose",
                "-p",
                compose_project,
                "-f",
                self.config.deployment.compose_file,
                "up",
                "-d",
                "--remove-orphans",
            ],
            env=extra_env,
        )

    def _compose_down(
        self,
        compose_project: str,
        remove_volumes: bool,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        logger.info("Stopping compose project=%s", compose_project)
        argv = [
            self.config.deployment.compose_bin,
            "compose",
            "-p",
            compose_project,
            "-f",
            self.config.deployment.compose_file,
            "down",
        ]
        if remove_volumes:
            argv.append("-v")
        argv.append("--remove-orphans")
        self._run(argv, env=extra_env)

    def _seed(self, command_template: list[str], compose_project: str) -> None:
        if not command_template:
            return
        command = [
            part.format(
                compose_project=compose_project,
                compose_file=self.config.deployment.compose_file,
            )
            for part in command_template
        ]
        logger.info("Seeding compose project=%s", compose_project)
        self._run(command)

    def deploy_review(self, pr: PullRequestInfo) -> DeployedReview:
        preview = self._preview_config()
        compose_project = self.compose_project_name(pr.number)
        hostname = self.hostname_for_pr(pr.number)
        image = self.review_image_for_pr(pr.number, pr.head_sha)
        data_dir = Path(self.data_dir_for_pr(pr.number))
        sqlite_path = self.sqlite_path_for_pr(pr.number)
        is_first_creation = not data_dir.exists()

        self._ensure_dir(data_dir, "review data directory")
        extra_env = self._compose_env(
            image=image,
            hostname=hostname,
            data_dir=str(data_dir),
            sqlite_path=sqlite_path,
            traefik_router=compose_project,
            traefik_service=compose_project,
        )
        self._compose_up(compose_project, extra_env)
        if is_first_creation:
            self._seed(preview.seed_command, compose_project)

        return DeployedReview(
            pr=pr.number,
            sha=pr.head_sha,
            compose_project=compose_project,
            hostname=hostname,
            data_dir=str(data_dir),
            sqlite_path=sqlite_path,
            image=image,
        )

    def remove_review(self, deployed: DeployedReview) -> None:
        try:
            self._compose_down(
                deployed.compose_project,
                remove_volumes=True,
                extra_env=self._compose_env(
                    image=deployed.image,
                    hostname=deployed.hostname,
                    data_dir=deployed.data_dir,
                    sqlite_path=deployed.sqlite_path,
                    traefik_router=deployed.compose_project,
                    traefik_service=deployed.compose_project,
                ),
            )
        finally:
            shutil.rmtree(deployed.data_dir, ignore_errors=True)

    def deploy_production(
        self, sha: str, previous: DeployedProduction | None
    ) -> DeployedProduction:
        production = self._production_config()
        compose_project = self._production_project_name()
        hostname = self._production_hostname()
        image = self.production_image_for_sha(sha)
        data_dir = Path(production.data_dir)
        sqlite_path = Path(production.sqlite_path)
        sqlite_existed = sqlite_path.exists()

        self._ensure_dir(data_dir, "production data directory")
        if previous is not None:
            self._compose_down(
                compose_project,
                remove_volumes=False,
                extra_env=self._compose_env(
                    image=previous.image,
                    hostname=previous.hostname,
                    data_dir=previous.data_dir,
                    sqlite_path=previous.sqlite_path,
                    traefik_router=previous.compose_project,
                    traefik_service=previous.compose_project,
                ),
            )
            self._backup_sqlite(sqlite_path)

        extra_env = self._compose_env(
            image=image,
            hostname=hostname,
            data_dir=str(data_dir),
            sqlite_path=str(sqlite_path),
            traefik_router=compose_project,
            traefik_service=compose_project,
        )
        self._compose_up(compose_project, extra_env)
        if not sqlite_existed:
            self._seed(production.seed_command, compose_project)

        return DeployedProduction(
            sha=sha,
            compose_project=compose_project,
            hostname=hostname,
            data_dir=str(data_dir),
            sqlite_path=str(sqlite_path),
            image=image,
            branch=production.branch,
        )

    def _backup_sqlite(self, sqlite_path: Path) -> None:
        if not sqlite_path.exists():
            return
        production = self._production_config()
        backup_dir = Path(production.backup_dir)
        self._ensure_dir(backup_dir, "production backup directory")
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        backup_path = backup_dir / f"{sqlite_path.stem}-{timestamp}{sqlite_path.suffix}"
        shutil.copy2(sqlite_path, backup_path)
        backups = sorted(backup_dir.glob(f"{sqlite_path.stem}-*{sqlite_path.suffix}"), reverse=True)
        for stale_backup in backups[production.backup_keep :]:
            stale_backup.unlink()

    def _production_project_name(self) -> str:
        project_name = self.config.deployment.production_project_name
        if project_name is None:
            raise RuntimeError("production_project_name is required for production deployments")
        return project_name

    def _production_hostname(self) -> str:
        hostname = self.config.deployment.production_hostname
        if hostname is None:
            raise RuntimeError("production_hostname is required for production deployments")
        return hostname
