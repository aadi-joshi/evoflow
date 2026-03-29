from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "webhook",
    "authorization",
    "smtp_pass",
)


def mask_secret(value: str, keep_start: int = 4, keep_end: int = 4) -> str:
    if not value:
        return value
    if len(value) <= keep_start + keep_end:
        return "*" * len(value)
    return f"{value[:keep_start]}...{value[-keep_end:]}"


def mask_url(value: str) -> str:
    if not value:
        return value
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return mask_secret(value)

    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return f"{parsed.scheme}://{parsed.netloc}"
    masked_tail = "/".join(mask_secret(part, 2, 2) for part in parts[-2:])
    return f"{parsed.scheme}://{parsed.netloc}/.../{masked_tail}"


def sanitize_for_audit(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: sanitize_for_audit(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_audit(item, key) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return sanitize_for_audit(value.to_dict(), key)
    if isinstance(value, str):
        lower_key = (key or "").lower()
        if any(keyword in lower_key for keyword in SENSITIVE_KEYWORDS):
            return mask_url(value) if "://" in value else mask_secret(value)
        if "hooks.slack.com/services/" in value:
            return mask_url(value)
        if value.startswith(("xoxb-", "xoxp-", "xoxa-", "sk-")):
            return mask_secret(value)
        return value
    return value
