from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GitHubConfig(BaseModel):
    owner: str
    repo: str
    token_env: str
    webhook_secret_env: str
    required_event_types: list[str] = Field(
        default_factory=lambda: ["pull_request", "ping"]
    )


class DeploymentConfig(BaseModel):
    compose_file: str
    compose_bin: str = "docker"
    working_directory: str
    project_name_prefix: str
    preview_base_domain: str
    hostname_template: str


class ImageConfig(BaseModel):
    registry: str
    repository: str
    tag_template: str


class PreviewConfig(BaseModel):
    base_dir: str
    reset_data_on_redeploy: bool = True
    data_dir_template: str
    sqlite_path_template: str
    seed_command: list[str] = Field(default_factory=list)


class ReconcileConfig(BaseModel):
    poll_interval_seconds: int = 600
    cleanup_closed_prs: bool = True
    redeploy_on_sha_change: bool = True


class TraefikConfig(BaseModel):
    enable_labels: bool = True
    certresolver: str = "letsencrypt"


class StateConfig(BaseModel):
    state_file: str


class WakeConfig(BaseModel):
    wake_file: str


class ProjectConfig(BaseModel):
    project_id: str
    github: GitHubConfig
    deployment: DeploymentConfig
    image: ImageConfig
    preview: PreviewConfig
    reconcile: ReconcileConfig
    traefik: TraefikConfig
    state: StateConfig
    wake: WakeConfig


class PullRequestInfo(BaseModel):
    number: int
    head_sha: str
    state: Literal["open", "closed"]
    merged: bool = False


class DeployedPreview(BaseModel):
    pr: int
    sha: str
    compose_project: str
    hostname: str
    data_dir: str
    image: str


class ProjectState(BaseModel):
    project_id: str
    deployed: dict[int, DeployedPreview] = Field(default_factory=dict)

    @field_validator("deployed", mode="before")
    @classmethod
    def normalize_deployed_keys(
        cls, value: dict[int, DeployedPreview] | dict[str, DeployedPreview]
    ) -> dict[int, DeployedPreview] | dict[str, DeployedPreview]:
        if not isinstance(value, dict):
            return value
        return {int(key): item for key, item in value.items()}
