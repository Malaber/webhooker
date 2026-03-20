from __future__ import annotations

import hmac
from hashlib import sha256

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
