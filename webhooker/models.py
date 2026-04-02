from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DeploymentMode = Literal["review", "production"]


class GitHubConfig(BaseModel):
    owner: str
    repo: str
    token_env: str
    webhook_secret_env: str
    required_event_types: list[str] = Field(default_factory=lambda: ["pull_request", "ping"])


class DeploymentConfig(BaseModel):
    mode: DeploymentMode = "review"
    compose_file: str
    compose_bin: str = "docker"
    working_directory: str
    project_name_prefix: str
    preview_base_domain: str | None = None
    hostname_template: str | None = None
    production_project_name: str | None = None
    production_hostname: str | None = None


class ImageConfig(BaseModel):
    registry: str
    repository: str
    tag_template: str
    production_tag_template: str | None = None


class PreviewConfig(BaseModel):
    base_dir: str
    data_dir_template: str
    sqlite_path_template: str
    seed_command: list[str] = Field(default_factory=list)


class ProductionConfig(BaseModel):
    branch: str = "main"
    data_dir: str
    sqlite_path: str
    backup_dir: str
    backup_keep: int = 3
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
    preview: PreviewConfig | None = None
    production: ProductionConfig | None = None
    reconcile: ReconcileConfig
    traefik: TraefikConfig
    state: StateConfig
    wake: WakeConfig

    @model_validator(mode="after")
    def validate_mode_specific_sections(self) -> ProjectConfig:
        if self.deployment.mode == "review":
            if self.preview is None:
                raise ValueError("preview configuration is required when deployment.mode=review")
            if self.deployment.hostname_template is None:
                raise ValueError(
                    "deployment.hostname_template is required when deployment.mode=review"
                )
        if self.deployment.mode == "production":
            if self.production is None:
                raise ValueError(
                    "production configuration is required when deployment.mode=production"
                )
            if self.deployment.production_project_name is None:
                raise ValueError(
                    "deployment.production_project_name is required when deployment.mode=production"
                )
            if self.deployment.production_hostname is None:
                raise ValueError(
                    "deployment.production_hostname is required when deployment.mode=production"
                )
        return self


class PullRequestInfo(BaseModel):
    number: int
    head_sha: str
    state: Literal["open", "closed"]
    merged: bool = False


class DeployedReview(BaseModel):
    pr: int
    sha: str
    compose_project: str
    hostname: str
    data_dir: str
    sqlite_path: str
    image: str
    config_fingerprint: str | None = None


class DeployedProduction(BaseModel):
    sha: str
    compose_project: str
    hostname: str
    data_dir: str
    sqlite_path: str
    image: str
    branch: str
    config_fingerprint: str | None = None


class ProjectState(BaseModel):
    project_id: str
    reviews: dict[int, DeployedReview] = Field(default_factory=dict)
    production: DeployedProduction | None = None

    @field_validator("reviews", mode="before")
    @classmethod
    def normalize_review_keys(
        cls, value: dict[int, DeployedReview] | dict[str, DeployedReview]
    ) -> dict[int, DeployedReview] | dict[str, DeployedReview]:
        if not isinstance(value, dict):
            return value
        return {int(key): item for key, item in value.items()}
