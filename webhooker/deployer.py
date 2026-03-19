from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from webhooker.models import DeployedPreview, ProjectConfig, PullRequestInfo
from webhooker.paths import ensure_dir

logger = logging.getLogger(__name__)


class Deployer:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    def compose_project_name(self, pr: int) -> str:
        return f"{self.config.deployment.project_name_prefix}{pr}"

    def hostname_for_pr(self, pr: int) -> str:
        return self.config.deployment.hostname_template.format(pr=pr)

    def image_for_pr(self, pr: int, sha: str) -> str:
        sha7 = sha[:7]
        tag = self.config.image.tag_template.format(pr=pr, sha=sha, sha7=sha7)
        return f"{self.config.image.registry}/{self.config.image.repository}:{tag}"

    def data_dir_for_pr(self, pr: int) -> str:
        return self.config.preview.data_dir_template.format(pr=pr)

    def sqlite_path_for_pr(self, pr: int) -> str:
        return self.config.preview.sqlite_path_template.format(pr=pr)

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

    def _compose_up(self, compose_project: str, extra_env: dict[str, str]) -> None:
        logger.info("Deploying preview project=%s", compose_project)
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

    def _compose_down(self, compose_project: str) -> None:
        logger.info("Removing preview project=%s", compose_project)
        self._run(
            [
                self.config.deployment.compose_bin,
                "compose",
                "-p",
                compose_project,
                "-f",
                self.config.deployment.compose_file,
                "down",
                "-v",
                "--remove-orphans",
            ]
        )

    def _seed(self, compose_project: str) -> None:
        if not self.config.preview.seed_command:
            return

        command = [
            part.format(
                compose_project=compose_project,
                compose_file=self.config.deployment.compose_file,
            )
            for part in self.config.preview.seed_command
        ]
        logger.info("Seeding preview project=%s", compose_project)
        self._run(command)

    def deploy_preview(self, pr: PullRequestInfo) -> DeployedPreview:
        compose_project = self.compose_project_name(pr.number)
        hostname = self.hostname_for_pr(pr.number)
        image = self.image_for_pr(pr.number, pr.head_sha)
        data_dir = self.data_dir_for_pr(pr.number)

        if self.config.preview.reset_data_on_redeploy and Path(data_dir).exists():
            shutil.rmtree(data_dir)

        ensure_dir(data_dir)

        extra_env = {
            "APP_IMAGE": image,
            "APP_HOSTNAME": hostname,
            "APP_DATA_DIR": data_dir,
            "APP_SQLITE_PATH": self.sqlite_path_for_pr(pr.number),
            "TRAEFIK_ROUTER": compose_project,
            "TRAEFIK_SERVICE": compose_project,
            "TRAEFIK_CERTRESOLVER": self.config.traefik.certresolver,
        }

        self._compose_up(compose_project, extra_env)
        self._seed(compose_project)

        return DeployedPreview(
            pr=pr.number,
            sha=pr.head_sha,
            compose_project=compose_project,
            hostname=hostname,
            data_dir=data_dir,
            image=image,
        )

    def remove_preview(self, deployed: DeployedPreview) -> None:
        try:
            self._compose_down(deployed.compose_project)
        finally:
            shutil.rmtree(deployed.data_dir, ignore_errors=True)
