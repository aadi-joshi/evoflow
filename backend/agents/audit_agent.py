"""
Audit Agent — Tamper-evident, append-only event log with hash chain.

Every record contains:
  - SHA-256 hash of its own content  (current_hash)
  - SHA-256 hash of the previous record (prev_hash)
  → Forms an immutable hash chain: any tampering breaks the chain.

PII masking is applied before persisting log entries so sensitive data
(emails, names, employee IDs) never lands in the audit file in plaintext.

Verification:
  AuditAgent.verify_chain(events) → True if chain is intact, False otherwise.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.utils.pii_masker import mask_pii


class AuditAgent:
    name = "audit_agent"

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self._prev_hash: str = "0" * 64  # genesis hash

    # ── Public API ────────────────────────────────────────────────────────────

    def log(
        self,
        run_id: str,
        actor: str,
        action: str,
        payload: Dict[str, Any],
        llm_audit: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Append one tamper-evident event to the in-memory log.

        The record is:
          1. Normalised (objects → dicts)
          2. PII-masked
          3. Hashed (SHA-256 over canonical JSON)
          4. Chained to the previous record's hash
        """
        normalised_payload = mask_pii(self._normalize(payload))

        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id":    run_id,
            "actor":     actor,
            "action":    action,
            "payload":   normalised_payload,
            "prev_hash": self._prev_hash,
        }

        if llm_audit:
            record["llm_trace"] = {
                "ai_generated":  llm_audit.get("ai_generated", False),
                "model":         llm_audit.get("model"),
                "latency_ms":    llm_audit.get("latency_ms", 0),
                "prompt":        llm_audit.get("prompt"),
                "raw_response":  llm_audit.get("raw_response"),
                "error":         llm_audit.get("error"),
                "fallback_used": llm_audit.get("fallback_used", False),
            }

        # Compute hash over stable canonical JSON (sorted keys, no indent)
        current_hash = self._hash_record(record)
        record["current_hash"] = current_hash

        self._prev_hash = current_hash
        self.events.append(record)

    def export(self, path: Path) -> None:
        """Write all events to disk as formatted JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self.events, fh, indent=2)

    # ── Chain verification ────────────────────────────────────────────────────

    @staticmethod
    def verify_chain(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Verify the integrity of a persisted audit log.

        Returns (True, "ok") if the chain is intact.
        Returns (False, reason) if tampering is detected.
        """
        if not events:
            return True, "ok"

        prev_hash = "0" * 64
        for i, record in enumerate(events):
            if record.get("prev_hash") != prev_hash:
                return False, (
                    f"Chain broken at record {i}: "
                    f"expected prev_hash={prev_hash!r}, "
                    f"got {record.get('prev_hash')!r}"
                )

            # Recompute hash from record excluding current_hash field
            stored_hash = record.get("current_hash", "")
            probe = {k: v for k, v in record.items() if k != "current_hash"}
            recomputed = AuditAgent._hash_record(probe)
            if recomputed != stored_hash:
                return False, (
                    f"Hash mismatch at record {i} (action={record.get('action')!r}): "
                    f"stored={stored_hash!r}, recomputed={recomputed!r}"
                )

            prev_hash = stored_hash

        return True, "ok"

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _hash_record(record: Dict[str, Any]) -> str:
        """SHA-256 over stable canonical JSON serialisation."""
        canonical = json.dumps(record, sort_keys=True, ensure_ascii=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _normalize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self._normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalize(i) for i in value]
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return self._normalize(value.to_dict())
        return value
