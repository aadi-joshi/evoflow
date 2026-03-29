"""
Audit Agent — Append-only immutable event log with hash-chained integrity.

Every audit record captures:
  - SHA-256 hash chain (each record hashes itself + previous record's hash)
  - LLM prompt, raw response, ai_generated flag, confidence, reasoning
  - Latency of the LLM call
  - Tamper-proof verification via verify_chain()

This makes the audit trail fully explainable AND cryptographically verifiable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.security import sanitize_for_audit


class AuditAgent:
    name = "audit_agent"

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self._prev_hash: str = "GENESIS"  # seed for the hash chain

    def log(
        self,
        run_id: str,
        actor: str,
        action: str,
        payload: Dict[str, Any],
        llm_audit: Dict[str, Any] | None = None,
    ) -> None:
        """
        Append one event to the in-memory log with hash chaining.

        Parameters
        ----------
        run_id:    Workflow run UUID.
        actor:     Name of the agent that produced this event.
        action:    Event type string (e.g., "failure_analysis").
        payload:   Event-specific data dict.
        llm_audit: Optional LLM audit record (prompt, raw_response, latency_ms, …).
        """
        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id":    run_id,
            "actor":     actor,
            "action":    action,
            "payload":   self._normalize(payload),
            "sequence":  len(self.events),
        }

        if llm_audit:
            record["llm_trace"] = {
                "ai_generated": llm_audit.get("ai_generated", False),
                "model":        llm_audit.get("model"),
                "latency_ms":   llm_audit.get("latency_ms", 0),
                "prompt":       llm_audit.get("prompt"),
                "raw_response": llm_audit.get("raw_response"),
                "error":        llm_audit.get("error"),
                "fallback_used": llm_audit.get("fallback_used", False),
            }

        # ── Hash chaining ─────────────────────────────────────────────────
        record["prev_hash"] = self._prev_hash
        record_hash = self._compute_hash(record)
        record["record_hash"] = record_hash
        self._prev_hash = record_hash

        self.events.append(record)

    def export(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        export_data = {
            "events": self.events,
            "integrity": {
                "chain_length":  len(self.events),
                "genesis_hash":  "GENESIS",
                "final_hash":    self._prev_hash,
                "algorithm":     "sha256",
                "tamper_proof":  True,
                "verified":      self.verify_chain(),
            },
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(export_data, fh, indent=2)

    def verify_chain(self) -> bool:
        """Verify the integrity of the entire hash chain."""
        if not self.events:
            return True

        expected_prev = "GENESIS"
        for event in self.events:
            if event.get("prev_hash") != expected_prev:
                return False
            # Recompute hash without the record_hash field
            stored_hash = event.get("record_hash")
            recomputed = self._compute_hash(event)
            if recomputed != stored_hash:
                return False
            expected_prev = stored_hash
        return True

    # ─── Private ─────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_hash(record: Dict[str, Any]) -> str:
        """Compute SHA-256 hash of a record (excluding the record_hash field)."""
        hashable = {k: v for k, v in record.items() if k != "record_hash"}
        canonical = json.dumps(hashable, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _normalize(self, value: Any) -> Any:
        return sanitize_for_audit(value)
