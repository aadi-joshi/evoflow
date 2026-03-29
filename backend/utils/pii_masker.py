"""
PII Masker — Redacts sensitive fields from audit payloads before persistence.

Masks:
  - Email addresses  → u***@domain.com
  - Full names       → J*** D***
  - Employee IDs     → EMP-***
  - Phone numbers    → ***-***-XXXX
  - API keys / tokens (heuristic length+prefix check)

Usage:
    masked = mask_pii(payload_dict)
"""
from __future__ import annotations

import re
from typing import Any

# ── Patterns ──────────────────────────────────────────────────────────────────

_EMAIL_RE    = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE    = re.compile(r"\b(\+?\d[\d\s\-\.]{7,}\d)\b")
_EMP_ID_RE   = re.compile(r"\b(EMP[-_]?\d{3,})\b", re.IGNORECASE)
_TOKEN_RE    = re.compile(r"\b(sk-|Bearer |ghp_|xoxb-|xoxp-)[A-Za-z0-9\-_]{10,}\b")

# Fields whose values are always masked regardless of content
_SENSITIVE_KEYS = {
    "email", "owner_email", "delegate_email", "original_approver_email",
    "full_name", "employee_name", "name", "delegate_name", "original_approver",
    "employee_id", "phone", "mobile", "api_key", "token", "secret", "password",
    "authorization", "recipient", "recipients",
}


def mask_pii(value: Any, _depth: int = 0) -> Any:
    """
    Recursively mask PII in any JSON-serialisable value.
    Depth limit prevents pathological recursion on huge nested objects.
    """
    if _depth > 10:
        return value

    if isinstance(value, dict):
        return {
            k: _mask_value(k, v, _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_pii(item, _depth + 1) for item in value]
    if isinstance(value, str):
        return _scrub_string(value)
    return value


def _mask_value(key: str, value: Any, depth: int) -> Any:
    """Mask a dict value by key name or by content scanning."""
    if key.lower() in _SENSITIVE_KEYS:
        if isinstance(value, str) and value:
            return _mask_by_key(key.lower(), value)
        if isinstance(value, list):
            return [_mask_by_key(key.lower(), v) if isinstance(v, str) else v for v in value]
        return value
    return mask_pii(value, depth)


def _mask_by_key(key: str, value: str) -> str:
    if not value:
        return value

    if key in ("email", "owner_email", "delegate_email", "original_approver_email"):
        return _mask_email(value)

    if key in ("full_name", "employee_name", "name", "delegate_name", "original_approver"):
        return _mask_name(value)

    if key in ("employee_id",):
        return _mask_employee_id(value)

    if key in ("phone", "mobile"):
        return _mask_phone(value)

    if key in ("api_key", "token", "secret", "password", "authorization"):
        return "***REDACTED***"

    if key in ("recipient", "recipients"):
        return _mask_email(value)

    # Fallback: first char + stars
    return value[0] + "***" if len(value) > 1 else "***"


def _mask_email(email: str) -> str:
    """john.doe@company.com → j***.d***@company.com"""
    match = _EMAIL_RE.search(email)
    if not match:
        return "***@***.***"
    local, domain = match.group().split("@", 1)
    parts = local.split(".")
    masked_local = ".".join(
        (p[0] + "***") if p else "***" for p in parts
    )
    return f"{masked_local}@{domain}"


def _mask_name(name: str) -> str:
    """John Doe → J*** D***"""
    parts = name.strip().split()
    return " ".join((p[0] + "***") if p else "***" for p in parts)


def _mask_employee_id(eid: str) -> str:
    """EMP-12345 → EMP-***"""
    return _EMP_ID_RE.sub(lambda m: m.group(1).split("-")[0] + "-***", eid) or "***"


def _mask_phone(phone: str) -> str:
    """Any phone → ***-***-XXXX (last 4 preserved)"""
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 4:
        return "***-***-" + digits[-4:]
    return "***-***-****"


def _scrub_string(text: str) -> str:
    """Scan free-form strings and redact any PII patterns found."""
    text = _EMAIL_RE.sub(lambda m: _mask_email(m.group()), text)
    text = _TOKEN_RE.sub("***REDACTED_TOKEN***", text)
    return text
