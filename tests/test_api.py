from __future__ import annotations

import hmac
import json
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webhooker.api import create_app


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


def test_healthz(config_dir: Path) -> None:
    client = TestClient(create_app(str(config_dir)))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_wake_endpoint_accepts_valid_review_request(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake_file = Path("/tmp/review-wake")
    if wake_file.exists():
        wake_file.unlink()

    client = TestClient(create_app(str(config_dir)))
    body = json.dumps({"repository": {"full_name": "example/repo"}}).encode("utf-8")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")

    response = client.post(
        "/github/review-demo/wake",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signature("supersecret", body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert wake_file.exists()

    wake_file.unlink()


def test_wake_endpoint_rejects_bad_signature(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(str(config_dir)))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")

    response = client.post(
        "/github/review-demo/wake",
        content=b"{}",
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=bad",
        },
    )

    assert response.status_code == 401


def test_wake_endpoint_rejects_repository_mismatch(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(str(config_dir)))
    body = json.dumps({"repository": {"full_name": "other/repo"}}).encode("utf-8")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")

    response = client.post(
        "/github/review-demo/wake",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signature("supersecret", body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 403


def test_wake_endpoint_ignores_unexpected_event(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(str(config_dir)))
    body = json.dumps({"repository": {"full_name": "example/repo"}}).encode("utf-8")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")

    response = client.post(
        "/github/review-demo/wake",
        content=body,
        headers={
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": _signature("supersecret", body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "reason": "event type"}


def test_wake_endpoint_rejects_invalid_json(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(str(config_dir)))
    body = b"{"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")

    response = client.post(
        "/github/review-demo/wake",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signature("supersecret", body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400


def test_wake_endpoint_rejects_unknown_project(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(str(config_dir)))
    body = b"{}"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "supersecret")

    response = client.post(
        "/github/missing/wake",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signature("supersecret", body),
        },
    )

    assert response.status_code == 404
