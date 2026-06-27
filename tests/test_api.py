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


def test_wake_endpoint_rejects_missing_webhook_secret(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(str(config_dir)))
    body = b"{}"
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    response = client.post(
        "/github/review-demo/wake",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=anything",
        },
    )

    assert response.status_code == 500


def test_wake_endpoint_accepts_secret_with_surrounding_whitespace(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(str(config_dir)))
    body = json.dumps({"repository": {"full_name": "example/repo"}}).encode("utf-8")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", " supersecret\n")

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


def test_ui_deployment_config_round_trips_to_desired_file(config_dir: Path) -> None:
    client = TestClient(create_app(str(config_dir)))

    response = client.post(
        "/ui/deployments",
        json={"projects": {"review-demo": {"enabled": True, "review_prs": [5, 8]}}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    saved = json.loads((config_dir / "desired-deployments.json").read_text(encoding="utf-8"))
    assert saved == {"projects": {"review-demo": {"enabled": True, "review_prs": [5, 8]}}}

    get_response = client.get("/ui/deployments")

    assert get_response.status_code == 200
    assert get_response.json()["desired"] == saved


def test_ui_page_lists_resource_constraints(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEBHOOKER_RAM_BUDGET", "2048")
    monkeypatch.setenv("WEBHOOKER_RAM_PER_APPLICATION", "512")
    client = TestClient(create_app(str(config_dir)))

    response = client.get("/ui")

    assert response.status_code == 200
    assert "RAM budget: 2048 / per app: 512" in response.text
    assert "review-demo" in response.text
