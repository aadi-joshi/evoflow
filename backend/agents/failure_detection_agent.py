"""
Failure Detection Agent — GenAI-powered failure analysis.

Replaces the hardcoded recoverable/non-recoverable lookup with LLM reasoning
that infers root cause, business severity, and recommended action from the
full step context. Falls back to deterministic logic when LLM is unavailable.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from backend.services.llm_service import generate_response
from backend.utils.models import StepResult

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_failure":          {"type": "boolean"},
        "reason":              {"type": "string"},
        "severity":            {"type": "string", "enum": ["none", "low", "medium", "high", "critical"]},
        "recoverable":         {"type": "boolean"},
        "confidence":          {"type": "number"},
        "recommended_action":  {"type": "string", "enum": ["continue", "retry", "escalate", "skip", "modify"]},
        "reasoning":           {"type": "string"},
    },
    "required": [
        "is_failure", "reason", "severity", "recoverable",
        "confidence", "recommended_action", "reasoning",
    ],
}

# Known transient error codes that are always safe to retry
_TRANSIENT_CODES = {
    "JIRA_PROVISIONING_TIMEOUT",
    "NETWORK_TIMEOUT",
    "SERVICE_UNAVAILABLE",
    "RATE_LIMITED",
    "GATEWAY_TIMEOUT",
}


class FailureDetectionAgent:
    name = "failure_detection_agent"

    def analyze(
        self,
        step_result: StepResult,
        context: Dict[str, Any] | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Analyse a StepResult and produce a structured failure diagnosis.

        Returns
        -------
        (diagnosis, llm_audit)
            diagnosis  — structured dict with is_failure, severity, reasoning, etc.
            llm_audit  — audit record with prompt, raw_response, ai_generated flag.
        """
        if step_result.status == "success":
            diagnosis = {
                "is_failure": False,
                "reason": "Step completed successfully",
                "severity": "none",
                "recoverable": False,
                "confidence": 1.0,
                "recommended_action": "continue",
                "reasoning": (
                    f"{step_result.step_name} executed without errors on "
                    f"attempt {step_result.attempts}."
                ),
                "route": "continue",
            }
            return diagnosis, {"ai_generated": False, "prompt": None, "raw_response": None, "latency_ms": 0}

        prompt = self._build_prompt(step_result, context or {})
        llm_response, llm_audit = generate_response(prompt, _OUTPUT_SCHEMA, temperature=0.2)

        if llm_audit.get("ai_generated"):
            diagnosis = self._enrich(llm_response, step_result)
        else:
            # LLM unavailable — use deterministic fallback
            diagnosis = self._deterministic_fallback(step_result)
            llm_audit["fallback_used"] = True

        return diagnosis, llm_audit

    # ─── Private ─────────────────────────────────────────────────────────────

    def _build_prompt(self, sr: StepResult, context: Dict[str, Any]) -> str:
        return (
            "Analyse the following enterprise workflow step failure and produce a "
            "structured diagnosis.\n\n"
            f"Step name:  {sr.step_name}\n"
            f"System:     {sr.payload.get('system', 'unknown')}\n"
            f"Error code: {sr.error_code}\n"
            f"Message:    {sr.message}\n"
            f"Attempts so far: {sr.attempts}\n"
            f"Payload:    {json.dumps(sr.payload)}\n"
            f"Context:    {json.dumps(context)}\n\n"
            "Determine:\n"
            "1. The root cause of the failure based on the error code and system.\n"
            "2. Business severity (e.g., email account = critical; Jira = medium).\n"
            "3. Whether the failure is transient/recoverable (timeout, rate-limit) "
            "vs. permanent (permission denied, account already exists).\n"
            "4. The best recommended action for the autonomous agent.\n"
            "5. Your confidence in this analysis (0.0–1.0).\n"
            "6. A clear one-paragraph reasoning that a human reviewer can understand."
        )

    @staticmethod
    def _enrich(llm: Dict[str, Any], sr: StepResult) -> Dict[str, Any]:
        """Add backward-compatible 'route' field and fill in blanks."""
        action = llm.get("recommended_action", "escalate")
        if not llm.get("is_failure"):
            route = "continue"
        elif action in ("retry", "modify"):
            route = "recover"
        else:
            route = "escalate"

        return {**llm, "route": route, "error_code": sr.error_code}

    @staticmethod
    def _deterministic_fallback(sr: StepResult) -> Dict[str, Any]:
        recoverable = sr.error_code in _TRANSIENT_CODES
        return {
            "is_failure": True,
            "reason": f"Step failed with error code: {sr.error_code}",
            "severity": "high",
            "recoverable": recoverable,
            "confidence": 0.70,
            "recommended_action": "retry" if recoverable else "escalate",
            "reasoning": (
                f"Deterministic analysis: {sr.error_code} is "
                + ("a transient error — retrying is safe." if recoverable
                   else "not a known transient error — escalating.")
            ),
            "route": "recover" if recoverable else "escalate",
            "error_code": sr.error_code,
        }
