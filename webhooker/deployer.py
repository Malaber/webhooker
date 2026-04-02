from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import yaml

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

PLACEHOLDER_IMAGE = "python:3.14-alpine"
PLACEHOLDER_POLL_SECONDS = 5


class Deployer:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    def deployment_fingerprint(self) -> str:
        digest = hashlib.sha256()
        payload = {
            "deployment": self.config.deployment.model_dump(mode="json"),
            "image": self.config.image.model_dump(mode="json"),
            "preview": self.config.preview.model_dump(mode="json") if self.config.preview else None,
            "production": (
                self.config.production.model_dump(mode="json") if self.config.production else None
            ),
            "traefik": self.config.traefik.model_dump(mode="json"),
        }
        digest.update(json.dumps(payload, sort_keys=True).encode("utf-8"))

        for path in self._deployment_input_paths():
            digest.update(str(path).encode("utf-8"))
            if path.exists():
                digest.update(b"present\0")
                digest.update(path.read_bytes())
            else:
                digest.update(b"missing\0")

        return digest.hexdigest()

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

    def _compose_file_path(self) -> Path:
        compose_path = Path(self.config.deployment.compose_file)
        if compose_path.is_absolute():
            return compose_path
        return Path(self.config.deployment.working_directory) / compose_path

    def _deployment_input_paths(self) -> list[Path]:
        compose_path = self._compose_file_path()
        input_paths: dict[str, Path] = {str(compose_path): compose_path}
        if compose_path.exists():
            for path in self._compose_env_file_paths(compose_path):
                input_paths[str(path)] = path
        return [input_paths[key] for key in sorted(input_paths)]

    def _compose_env_file_paths(self, compose_path: Path) -> list[Path]:
        loaded = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            return []
        services = loaded.get("services")
        if not isinstance(services, dict):
            return []

        env_paths: dict[str, Path] = {}
        for service in services.values():
            if not isinstance(service, dict):
                continue
            for entry in self._normalize_env_file_entries(service.get("env_file")):
                path = Path(entry)
                if not path.is_absolute():
                    path = compose_path.parent / path
                env_paths[str(path)] = path
        return [env_paths[key] for key in sorted(env_paths)]

    def _normalize_env_file_entries(self, value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            entries: list[str] = []
            for item in value:
                if isinstance(item, str):
                    entries.append(item)
                elif isinstance(item, dict) and isinstance(item.get("path"), str):
                    entries.append(item["path"])
            return entries
        return []

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

    def _compose_up(
        self,
        compose_project: str,
        extra_env: dict[str, str],
        *,
        compose_file: str | None = None,
    ) -> None:
        compose_file_path = compose_file or self.config.deployment.compose_file
        logger.info(
            "Deploying compose project=%s compose_file=%s", compose_project, compose_file_path
        )
        self._run(
            [
                self.config.deployment.compose_bin,
                "compose",
                "-p",
                compose_project,
                "-f",
                compose_file_path,
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
        *,
        compose_file: str | None = None,
    ) -> None:
        compose_file_path = compose_file or self.config.deployment.compose_file
        logger.info(
            "Stopping compose project=%s compose_file=%s", compose_project, compose_file_path
        )
        argv = [
            self.config.deployment.compose_bin,
            "compose",
            "-p",
            compose_project,
            "-f",
            compose_file_path,
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

    def _pull_image(self, image: str) -> None:
        logger.info("Pulling review image=%s", image)
        self._run([self.config.deployment.compose_bin, "pull", image])

    def _is_missing_review_image(self, exc: subprocess.CalledProcessError) -> bool:
        output = "\n".join(
            part for part in (exc.stdout, exc.stderr) if isinstance(part, str) and part.strip()
        ).lower()
        return any(
            marker in output
            for marker in (
                "manifest unknown",
                "not found",
                "repository does not exist",
                "pull access denied",
                "no such image",
            )
        )

    def _app_display_name(self) -> str:
        parts = [part for part in self.config.image.repository.split("/") if part]
        if parts:
            return parts[-1]
        return self.config.project_id

    def _placeholder_root(self) -> Path:
        preview = self._preview_config()
        return Path(preview.base_dir) / ".webhooker-placeholder"

    def _placeholder_compose_path(self, pr: int) -> Path:
        return self._placeholder_root() / f"pr-{pr}" / "compose.yml"

    def _placeholder_html_path(self, pr: int) -> Path:
        return self._placeholder_root() / f"pr-{pr}" / "index.html"

    def _placeholder_service_template(self) -> tuple[dict[str, object], dict[str, object]]:
        compose_path = self._compose_file_path()
        loaded = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise RuntimeError("review compose template must be a YAML mapping")
        services = loaded.get("services")
        if not isinstance(services, dict) or not services:
            raise RuntimeError("review compose template must define at least one service")

        selected_service: dict[str, object] | None = None
        for service in services.values():
            if not isinstance(service, dict):
                continue
            labels = service.get("labels")
            if self._service_uses_traefik(labels):
                selected_service = service
                break
        if selected_service is None:
            first_service = next(iter(services.values()))
            if not isinstance(first_service, dict):
                raise RuntimeError("review compose template service entries must be YAML mappings")
            selected_service = first_service

        top_level_networks = loaded.get("networks")
        if not isinstance(top_level_networks, dict):
            top_level_networks = {}

        return selected_service, top_level_networks

    def _service_uses_traefik(self, labels: object) -> bool:
        label_values: list[str] = []
        if isinstance(labels, dict):
            label_values.extend(
                str(key) if value is None else f"{key}={value}" for key, value in labels.items()
            )
        elif isinstance(labels, list):
            label_values.extend(str(item) for item in labels)
        return any("traefik." in value.lower() for value in label_values)

    def _write_review_placeholder_files(self, pr: PullRequestInfo, hostname: str) -> Path:
        placeholder_dir = self._placeholder_compose_path(pr.number).parent
        self._ensure_dir(self._placeholder_root(), "review placeholder directory")
        self._ensure_dir(placeholder_dir, "review placeholder directory")

        service_template, top_level_networks = self._placeholder_service_template()
        html_path = self._placeholder_html_path(pr.number)
        compose_path = self._placeholder_compose_path(pr.number)
        html_path.write_text(self._placeholder_html(pr, hostname), encoding="utf-8")
        compose_path.write_text(
            self._placeholder_compose_yaml(service_template, top_level_networks, html_path),
            encoding="utf-8",
        )
        return compose_path

    def _placeholder_html(self, pr: PullRequestInfo, hostname: str) -> str:
        app_name = self._app_display_name()
        return textwrap.dedent(f"""\
            <!doctype html>
            <html lang="en">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <title>{app_name} deployment is loading</title>
              <style>
                :root {{
                  color-scheme: light;
                  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
                  background:
                    radial-gradient(circle at top, #eef6ff 0%, #f8fafc 45%, #e2e8f0 100%);
                  color: #0f172a;
                }}
                * {{ box-sizing: border-box; }}
                body {{
                  margin: 0;
                  min-height: 100vh;
                  display: grid;
                  place-items: center;
                  padding: 24px;
                }}
                main {{
                  width: min(100%, 680px);
                  background: rgba(255, 255, 255, 0.92);
                  border: 1px solid rgba(148, 163, 184, 0.32);
                  border-radius: 24px;
                  padding: 32px;
                  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.12);
                }}
                h1 {{
                  margin: 0 0 12px;
                  font-size: clamp(2rem, 6vw, 3.5rem);
                  line-height: 1.05;
                }}
                p {{
                  margin: 0 0 16px;
                  font-size: 1.05rem;
                  line-height: 1.6;
                  color: #334155;
                }}
                .meta {{
                  display: inline-flex;
                  gap: 12px;
                  flex-wrap: wrap;
                  margin-top: 12px;
                  color: #475569;
                  font-size: 0.95rem;
                }}
                .pill {{
                  background: #e0f2fe;
                  border-radius: 999px;
                  padding: 8px 12px;
                }}
                .pulse {{
                  width: 14px;
                  height: 14px;
                  border-radius: 999px;
                  background: #0284c7;
                  display: inline-block;
                  margin-right: 10px;
                  animation: pulse 1.6s ease-in-out infinite;
                  vertical-align: middle;
                }}
                @keyframes pulse {{
                  0%, 100% {{ transform: scale(1); opacity: 0.55; }}
                  50% {{ transform: scale(1.45); opacity: 1; }}
                }}
              </style>
            </head>
            <body>
              <main>
                <p><span class="pulse"></span>Webhooker is preparing your review app.</p>
                <h1>webhooker is still loading your deployment for {app_name}</h1>
                <p>The preview image for pull request #{pr.number} is not available yet, so this temporary page is keeping the hostname live while webhooker keeps retrying the deploy in the background.</p>
                <p>This page refreshes automatically every {PLACEHOLDER_POLL_SECONDS} seconds and will switch to the real app as soon as the image is ready.</p>
                <div class="meta">
                  <span class="pill">PR #{pr.number}</span>
                  <span class="pill">{hostname}</span>
                  <span class="pill">Commit {pr.head_sha[:7]}</span>
                </div>
              </main>
              <script>
                window.setTimeout(function () {{
                  window.location.reload();
                }}, {PLACEHOLDER_POLL_SECONDS * 1000});
              </script>
            </body>
            </html>
            """)

    def _placeholder_compose_yaml(
        self,
        service_template: dict[str, object],
        top_level_networks: dict[str, object],
        html_path: Path,
    ) -> str:
        placeholder_service: dict[str, object] = {
            "image": PLACEHOLDER_IMAGE,
            "command": [
                "python",
                "-m",
                "http.server",
                "8000",
                "--directory",
                "/placeholder",
            ],
            "restart": "unless-stopped",
            "volumes": [f"{html_path}:/placeholder/index.html:ro"],
        }
        for key in ("labels", "networks"):
            value = service_template.get(key)
            if value is not None:
                placeholder_service[key] = value

        compose_doc: dict[str, object] = {
            "services": {
                "placeholder": placeholder_service,
            }
        }
        if top_level_networks:
            compose_doc["networks"] = top_level_networks

        return yaml.safe_dump(compose_doc, sort_keys=False)

    def _review_compose_file_for_state(self, deployed: DeployedReview) -> str:
        if deployed.placeholder_active:
            return str(self._placeholder_compose_path(deployed.pr))
        return self.config.deployment.compose_file

    def deploy_review(
        self,
        pr: PullRequestInfo,
        previous: DeployedReview | None = None,
    ) -> DeployedReview:
        preview = self._preview_config()
        compose_project = self.compose_project_name(pr.number)
        hostname = self.hostname_for_pr(pr.number)
        image = self.review_image_for_pr(pr.number, pr.head_sha)
        data_dir = Path(self.data_dir_for_pr(pr.number))
        sqlite_path = self.sqlite_path_for_pr(pr.number)
        sqlite_exists = Path(sqlite_path).exists()

        self._ensure_dir(data_dir, "review data directory")
        extra_env = self._compose_env(
            image=image,
            hostname=hostname,
            data_dir=str(data_dir),
            sqlite_path=sqlite_path,
            traefik_router=compose_project,
            traefik_service=compose_project,
        )
        placeholder_active = False
        compose_file = self.config.deployment.compose_file
        try:
            self._pull_image(image)
        except subprocess.CalledProcessError as exc:
            if not self._is_missing_review_image(exc):
                raise
            logger.warning(
                "Review image is not available yet; deploying placeholder page project_id=%s pr=%s image=%s",
                self.config.project_id,
                pr.number,
                image,
            )
            compose_file = str(self._write_review_placeholder_files(pr, hostname))
            placeholder_active = True

        self._compose_up(compose_project, extra_env, compose_file=compose_file)
        if not placeholder_active and (
            not sqlite_exists or (previous and previous.placeholder_active)
        ):
            self._seed(preview.seed_command, compose_project)

        return DeployedReview(
            pr=pr.number,
            sha=pr.head_sha,
            compose_project=compose_project,
            hostname=hostname,
            data_dir=str(data_dir),
            sqlite_path=sqlite_path,
            image=image,
            placeholder_active=placeholder_active,
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
                compose_file=self._review_compose_file_for_state(deployed),
            )
        finally:
            shutil.rmtree(deployed.data_dir, ignore_errors=True)
            shutil.rmtree(self._placeholder_compose_path(deployed.pr).parent, ignore_errors=True)

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
