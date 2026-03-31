from __future__ import annotations

import hmac
from hashlib import sha256

import pytest

from webhooker.logging_utils import configure_logging
from webhooker.security import verify_github_signature


def test_valid_github_signature_returns_true() -> None:
    secret = "supersecret"
    body = b'{"hello":"world"}'
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()

    assert verify_github_signature(secret, body, signature) is True


def test_invalid_github_signature_returns_false() -> None:
    assert verify_github_signature("secret", b"body", "sha256=deadbeef") is False


def test_missing_github_signature_returns_false() -> None:
    assert verify_github_signature("secret", b"body", None) is False


def test_blank_github_secret_returns_false() -> None:
    assert verify_github_signature(" \n\t ", b"body", "sha256=deadbeef") is False


def test_signature_verification_strips_surrounding_secret_whitespace() -> None:
    body = b'{"hello":"world"}'
    signature = "sha256=" + hmac.new(b"supersecret", body, sha256).hexdigest()

    assert verify_github_signature("  supersecret\n", body, signature) is True


def test_signature_verification_strips_surrounding_header_whitespace() -> None:
    body = b'{"hello":"world"}'
    signature = "sha256=" + hmac.new(b"supersecret", body, sha256).hexdigest()

    assert verify_github_signature("supersecret", body, f"  {signature}\n") is True


def test_configure_logging_calls_basic_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("logging.basicConfig", fake_basic_config)

    configure_logging()

    assert captured["format"] == "%(asctime)s %(levelname)s %(name)s %(message)s"
