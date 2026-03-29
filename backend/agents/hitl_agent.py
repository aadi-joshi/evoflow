"""
Human-in-the-Loop (HITL) Agent — EvoFlow AI.

When the system encounters ambiguity (e.g. no clear owner for an action item,
a missing delegate for an SLA reroute), it pauses and asks a human.

Architecture:
- The workflow worker thread calls request_clarification() and then wait_for_answer().
- wait_for_answer() blocks on a threading.Event — the SSE stream stays open.
- The frontend detects the clarification_needed SSE event and shows a modal.
- The user submits an answer via POST /api/clarify/{run_id}.
- The API calls provide_answer() which sets the threading.Event.
- The worker thread unblocks and continues.

A per-run registry maps run_id → (event, answer).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional


# ── Global registry shared with api.py ──────────────────────────────────────
# { run_id: {"event": threading.Event, "answer": Optional[str], "question": str} }
_REGISTRY: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


class HITLAgent:
    name = "hitl_agent"

    def request_clarification(
        self,
        run_id: str,
        question: str,
        context: Dict[str, Any],
        options: Optional[List[str]] = None,
    ) -> str:
        """
        Register a pending clarification request.

        Returns the question text (for logging). The caller should then
        emit a clarification_needed SSE event and call wait_for_answer().
        """
        event = threading.Event()
        with _LOCK:
            _REGISTRY[run_id] = {
                "event":    event,
                "answer":   None,
                "question": question,
                "context":  context,
                "options":  options or [],
            }
        return question

    def wait_for_answer(self, run_id: str, timeout: float = 300.0) -> Optional[str]:
        """
        Block the calling thread until the human provides an answer.

        Returns the answer string, or None if timed out.
        """
        with _LOCK:
            entry = _REGISTRY.get(run_id)
        if not entry:
            return None

        fired = entry["event"].wait(timeout=timeout)
        if not fired:
            return None  # Timed out — caller should escalate

        with _LOCK:
            return _REGISTRY.get(run_id, {}).get("answer")

    def cleanup(self, run_id: str) -> None:
        with _LOCK:
            _REGISTRY.pop(run_id, None)


def provide_answer(run_id: str, answer: str) -> bool:
    """
    Called by the API endpoint when the user submits a clarification.
    Returns True if the run_id was found and unblocked, False otherwise.
    """
    with _LOCK:
        entry = _REGISTRY.get(run_id)
    if not entry:
        return False
    entry["answer"] = answer
    entry["event"].set()
    return True


def get_pending(run_id: str) -> Optional[Dict[str, Any]]:
    """Return the pending clarification request for a run, if any."""
    with _LOCK:
        entry = _REGISTRY.get(run_id)
    if not entry or entry["event"].is_set():
        return None
    return {
        "question": entry["question"],
        "context":  entry["context"],
        "options":  entry["options"],
    }
