"""
Checkpoint Store — Step-level persistence for resume-from-failure.

Design:
  - Each workflow run has a checkpoint file: data/checkpoint_<run_id>.json
  - Before executing a step, the engine checks if a successful checkpoint exists.
  - On success, the result is checkpointed immediately.
  - On resume, completed steps are skipped; the engine picks up from the first
    non-completed step.
  - Idempotency key = run_id + step_name → prevents duplicate execution on retry.
  - Checkpoints are cleaned up after a successful run (configurable).

File format:
  {
    "run_id": "...",
    "workflow_type": "...",
    "input_data": {...},
    "created_at": "ISO-8601",
    "updated_at": "ISO-8601",
    "steps": {
      "create_email_account": {
        "idempotency_key": "sha256(run_id:step_name:input_hash)",
        "status": "success" | "failed" | "skipped",
        "result": {StepResult.to_dict()},
        "completed_at": "ISO-8601",
        "attempt": 1
      },
      ...
    }
  }
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.utils.models import StepResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckpointStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def init(
        self,
        run_id: str,
        workflow_type: str,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Initialise a new checkpoint for this run.
        If a checkpoint already exists (resume scenario), load and return it.
        """
        path = self._path(run_id)
        if path.exists():
            return self._load(path)

        checkpoint = {
            "run_id":        run_id,
            "workflow_type": workflow_type,
            "input_data":    input_data,
            "created_at":    _utc_now(),
            "updated_at":    _utc_now(),
            "steps":         {},
        }
        self._save(path, checkpoint)
        return checkpoint

    def is_done(self, run_id: str, step_name: str) -> bool:
        """Return True if step already completed successfully (idempotency guard)."""
        cp = self._load_or_none(run_id)
        if cp is None:
            return False
        step = cp.get("steps", {}).get(step_name, {})
        return step.get("status") == "success"

    def get_result(self, run_id: str, step_name: str) -> Optional[StepResult]:
        """Return the cached StepResult if step was already completed."""
        cp = self._load_or_none(run_id)
        if cp is None:
            return None
        step = cp.get("steps", {}).get(step_name)
        if step and step.get("status") == "success":
            d = step["result"]
            return StepResult(
                step_id=d["step_id"],
                step_name=d["step_name"],
                status=d["status"],
                message=d["message"],
                attempts=d.get("attempts", 1),
                error_code=d.get("error_code"),
                payload=d.get("payload", {}),
                start_ts=d.get("start_ts", ""),
                end_ts=d.get("end_ts", ""),
            )
        return None

    def save_step(
        self,
        run_id: str,
        step_name: str,
        result: StepResult,
        attempt: int = 1,
    ) -> None:
        """Persist a completed step result."""
        path = self._path(run_id)
        cp = self._load_or_none(run_id) or {}
        steps = cp.setdefault("steps", {})

        idempotency_key = self._idempotency_key(run_id, step_name)
        steps[step_name] = {
            "idempotency_key": idempotency_key,
            "status":          result.status,
            "result":          result.to_dict(),
            "completed_at":    _utc_now(),
            "attempt":         attempt,
        }
        cp["updated_at"] = _utc_now()
        self._save(path, cp)

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return the full checkpoint dict for run_id, or None if not found."""
        return self._load_or_none(run_id)

    def completed_steps(self, run_id: str) -> list[str]:
        """Return list of step names that completed successfully."""
        cp = self._load_or_none(run_id)
        if cp is None:
            return []
        return [
            name
            for name, data in cp.get("steps", {}).items()
            if data.get("status") == "success"
        ]

    def cleanup(self, run_id: str) -> None:
        """Remove checkpoint file after successful run (optional)."""
        path = self._path(run_id)
        if path.exists():
            path.unlink()

    # ── Private ───────────────────────────────────────────────────────────────

    def _path(self, run_id: str) -> Path:
        return self.data_dir / f"checkpoint_{run_id}.json"

    def _load_or_none(self, run_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(run_id)
        if not path.exists():
            return None
        return self._load(path)

    @staticmethod
    def _load(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _save(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _idempotency_key(run_id: str, step_name: str) -> str:
        raw = f"{run_id}:{step_name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
