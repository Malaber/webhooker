from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Literal, Optional, Union, get_args, get_origin, get_type_hints


class ValidationError(ValueError):
    """Lightweight validation error used in tests and config loading."""


class _DefaultFactory:
    def __init__(self, factory):
        self.factory = factory


def Field(*, default_factory):
    return _DefaultFactory(default_factory)


class BaseModel:
    def __init__(self, **kwargs: Any) -> None:
        hints = get_type_hints(self.__class__)
        for name, annotation in hints.items():
            if name in kwargs:
                value = kwargs[name]
            elif hasattr(self.__class__, name):
                default = getattr(self.__class__, name)
                if isinstance(default, _DefaultFactory):
                    value = default.factory()
                else:
                    value = default
            else:
                raise ValidationError(f"Missing required field: {name}")
            setattr(self, name, self._convert(annotation, value, name))

    @classmethod
    def model_validate(cls, raw: Any):
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, dict):
            raise ValidationError(f"Expected object for {cls.__name__}")
        return cls(**raw)

    def model_dump(self) -> dict[str, Any]:
        hints = get_type_hints(self.__class__)
        return {name: _dump_value(getattr(self, name)) for name in hints}

    def model_dump_json(self, indent: int | None = None) -> str:
        import json

        return json.dumps(self.model_dump(), indent=indent)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and self.model_dump() == other.model_dump()

    def __repr__(self) -> str:
        hints = get_type_hints(self.__class__)
        args = ", ".join(f"{k}={getattr(self, k)!r}" for k in hints)
        return f"{self.__class__.__name__}({args})"

    @classmethod
    def _convert(cls, annotation: Any, value: Any, name: str) -> Any:
        origin = get_origin(annotation)
        if annotation is Any:
            return value
        if origin is Literal:
            allowed = get_args(annotation)
            if value not in allowed:
                raise ValidationError(f"Invalid value for {name}: {value!r}")
            return value
        if origin in (list, list[str].__origin__ if hasattr(list[str], '__origin__') else list):
            if not isinstance(value, list):
                raise ValidationError(f"Expected list for {name}")
            inner = get_args(annotation)[0] if get_args(annotation) else Any
            return [cls._convert(inner, item, name) for item in value]
        if origin is dict:
            if not isinstance(value, dict):
                raise ValidationError(f"Expected object for {name}")
            key_type, value_type = get_args(annotation)
            return {
                cls._convert(key_type, key, name): cls._convert(value_type, item, name)
                for key, item in value.items()
            }
        if origin in (Union, getattr(__import__('types'), 'UnionType', Union)):
            options = [arg for arg in get_args(annotation) if arg is not type(None)]
            if value is None:
                return None
            for option in options:
                try:
                    return cls._convert(option, value, name)
                except ValidationError:
                    continue
            raise ValidationError(f"Invalid value for {name}: {value!r}")
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation.model_validate(value)
        if annotation is bool:
            if not isinstance(value, bool):
                raise ValidationError(f"Expected bool for {name}")
            return value
        if annotation is int:
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
            raise ValidationError(f"Expected int for {name}")
        if annotation is str:
            if not isinstance(value, str):
                raise ValidationError(f"Expected str for {name}")
            return value
        return value



def _dump_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {str(key): _dump_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dump_value(item) for item in value]
    return value


class GitHubConfig(BaseModel):
    owner: str
    repo: str
    token_env: str
    webhook_secret_env: str
    required_event_types: list[str] = Field(default_factory=lambda: ["pull_request", "ping"])


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
