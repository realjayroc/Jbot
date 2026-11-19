"""Environment-backed secret access; credentials are never written to shared state."""
from __future__ import annotations

import os
import re
from typing import Iterable


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SecurityVault:
    """Read provider credentials from process environment without persisting them."""

    def get_secret(self, name: str) -> str | None:
        if not _ENV_NAME.fullmatch(name):
            raise ValueError("secret name must be an uppercase environment-variable name")
        value = os.getenv(name, "").strip()
        return value or None

    def get_key_ring(self, name: str) -> list[str]:
        value = self.get_secret(name)
        keys = [item.strip() for item in (value or "").split(",") if item.strip()]
        if not keys and name.endswith("_API_KEYS"):
            singular = name[:-1].replace("_API_KEYS", "_API_KEY")
            value = self.get_secret(singular)
            keys = [item.strip() for item in (value or "").split(",") if item.strip()]
        return keys

    def redact(self, text: str, extra_secrets: Iterable[str] = ()) -> str:
        secrets = set(extra_secrets)
        for name, value in os.environ.items():
            if name.endswith(("_API_KEY", "_API_KEYS", "_TOKEN", "_SECRET")) and value.strip():
                secrets.add(value.strip())
                secrets.update(item.strip() for item in value.split(",") if item.strip())
        redacted = text
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
