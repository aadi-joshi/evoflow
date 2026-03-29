"""
Checkpoint Manager — Step-level workflow persistence for crash recovery.

Provides:
  - save(): persist workflow state after each step completion
  - load(): resume from last checkpoint on crash/restart
  - cleanup(): remove checkpoint after successful completion
  - Idempotency keys per step ({run_id}:{step_name}:{attempt})
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class CheckpointManager:
    """Manages step-level checkpoints for workflow crash recovery."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._checkpoint_dir = data_dir / "checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        run_id: str,
        step_index: int,
        step_name: str,
        state_dict: Dict[str, Any],
        completed_steps: List[str],
    ) -> str:
        """
        Persist a checkpoint after a step completes.

        Returns the idempotency key.
        """
        idempotency_key = f"{run_id}:{step_name}:{step_index}"
        checkpoint = {
            "run_id":          run_id,
            "step_index":      step_index,
            "step_name":       step_name,
            "idempotency_key": idempotency_key,
            "completed_steps": completed_steps,
            "state":           state_dict,
            "saved_at":        datetime.now(timezone.utc).isoformat(),
        }
        path = self._checkpoint_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(checkpoint, fh, indent=2, default=str)
        return idempotency_key

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Load the latest checkpoint for a run, or None if not found."""
        path = self._checkpoint_path(run_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def cleanup(self, run_id: str) -> bool:
        """Remove checkpoint after successful completion."""
        path = self._checkpoint_path(run_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_active(self) -> List[Dict[str, Any]]:
        """List all active (incomplete) checkpoints."""
        active = []
        for cp_file in self._checkpoint_dir.glob("checkpoint_*.json"):
            try:
                with cp_file.open("r", encoding="utf-8") as fh:
                    active.append(json.load(fh))
            except Exception:
                continue
        return active

    def _checkpoint_path(self, run_id: str) -> Path:
        return self._checkpoint_dir / f"checkpoint_{run_id}.json"
