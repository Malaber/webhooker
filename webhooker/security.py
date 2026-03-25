from __future__ import annotations

import hmac
from hashlib import sha256


def verify_github_signature(
    secret: str,
    raw_body: bytes,
    signature_header: str | None,
) -> bool:
    """Validate GitHub's X-Hub-Signature-256 header."""
    normalized_secret = secret.strip()
    normalized_signature = signature_header.strip() if signature_header is not None else None

    if not normalized_secret:
        return False
    if not normalized_signature or not normalized_signature.startswith("sha256="):
        return False

    expected = (
        "sha256="
        + hmac.new(
            normalized_secret.encode("utf-8"),
            raw_body,
            sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, normalized_signature)
