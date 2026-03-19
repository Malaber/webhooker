from __future__ import annotations

import hmac
from hashlib import sha256


def verify_github_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """Validate GitHub's X-Hub-Signature-256 header."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
