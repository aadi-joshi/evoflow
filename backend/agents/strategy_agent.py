"""
Strategy Agent — GenAI-powered adaptive recovery strategy generator.

Given a failing step, its historical failure pattern, the current recovery
policy, and the failure analysis, this agent generates a tailored strategy
that includes retry policy, prechecks, fallbacks, and a human-readable
justification.  Replaces the static retry-count-only logic.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from backend.services.llm_service import generate_response

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy_name": {"type": "string"},
        "actions":        {"type": "array", "items": {"type": "string"}},
        "retry_policy": {
            "type": "object",
            "properties": {
                "max_retries":       {"type": "integer"},
                "backoff":           {"type": "array", "items": {"type": "number"}},
                "backoff_strategy":  {"type": "string"},
            },
        },
        "prechecks":          {"type": "array", "items": {"type": "string"}},
        "fallbacks":          {"type": "array", "items": {"type": "string"}},
        "escalation_target":  {"type": "string"},
        "justification":      {"type": "string"},
        "confidence":         {"type": "number"},
    },
    "required": [
        "strategy_name", "actions", "retry_policy",
        "prechecks", "fallbacks", "justification", "confidence",
    ],
}


class StrategyAgent:
    name = "strategy_agent"

    def generate_strategy(
        self,
        step_name: str,
        failure_history: Dict[str, Any],
        current_policy: Dict[str, Any],
        failure_analysis: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Generate an adaptive recovery strategy for the given failing step.

        Returns
        -------
        (strategy, llm_audit)
        """
        prompt = self._build_prompt(
            step_name, failure_history, current_policy, failure_analysis
        )
        llm_response, llm_audit = generate_response(prompt, _OUTPUT_SCHEMA, temperature=0.4)

        if llm_audit.get("ai_generated"):
            strategy = self._validate_and_fix(llm_response, current_policy)
        else:
            strategy = self._default_strategy(step_name, current_policy, failure_analysis)
            llm_audit["fallback_used"] = True

        return strategy, llm_audit

    # ─── Private ─────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        step_name: str,
        history: Dict[str, Any],
        policy: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> str:
        total = history.get("success", 0) + history.get("failed", 0)
        fail_rate = (history.get("failed", 0) / total * 100) if total else 0

        return (
            "Design an adaptive recovery strategy for a failing enterprise workflow step.\n\n"
            f"Step:              {step_name}\n"
            f"Failure analysis:  {json.dumps(analysis)}\n"
            f"Current policy:    {json.dumps(policy)}\n"
            f"Historical stats:  success={history.get('success', 0)}, "
            f"failed={history.get('failed', 0)}, "
            f"failure_rate={fail_rate:.1f}%\n\n"
            "Design a strategy that:\n"
            "1. Directly addresses the root cause in the failure analysis.\n"
            "2. Sets max_retries appropriate to the failure rate "
            "(higher rate → more retries, up to 4).\n"
            "3. Uses exponential backoff (provide the exact wait times in seconds).\n"
            "4. Lists 2–3 concrete prechecks to validate system state before retrying.\n"
            "5. Lists 2–3 specific fallback actions if all retries are exhausted.\n"
            "6. Gives a clear justification paragraph explaining every decision.\n"
            "7. States your confidence (0.0–1.0) in this strategy.\n\n"
            "Give the strategy a short, descriptive name like "
            "'adaptive_jira_backoff_v2'."
        )

    @staticmethod
    def _validate_and_fix(
        strategy: Dict[str, Any], policy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ensure retry count is within safe bounds and backoff list matches."""
        rp = strategy.setdefault("retry_policy", {})
        max_r = max(1, min(int(rp.get("max_retries", 2)), 4))
        rp["max_retries"] = max_r

        backoff: List[float] = rp.get("backoff", [])
        # Pad or trim backoff list to match max_retries
        while len(backoff) < max_r:
            backoff.append(round(0.5 * (2 ** len(backoff)), 1))
        rp["backoff"] = [min(b, 5.0) for b in backoff[:max_r]]

        if not strategy.get("escalation_target"):
            strategy["escalation_target"] = policy.get(
                "escalation_target", "it-ops@company.com"
            )
        return strategy

    @staticmethod
    def _default_strategy(
        step_name: str,
        policy: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        max_r = min(policy.get("max_retries", 2), 4)
        backoff = [round(0.5 * (2 ** i), 1) for i in range(max_r)]
        return {
            "strategy_name": f"default_retry_{step_name}",
            "actions": [
                "verify_system_health",
                "retry_with_exponential_backoff",
                "escalate_if_exhausted",
            ],
            "retry_policy": {
                "max_retries": max_r,
                "backoff": backoff,
                "backoff_strategy": "exponential",
            },
            "prechecks": [
                "check_network_connectivity",
                "verify_downstream_service_availability",
            ],
            "fallbacks": [
                "create_manual_intervention_ticket",
                "notify_it_ops_team",
            ],
            "escalation_target": policy.get("escalation_target", "it-ops@company.com"),
            "justification": (
                f"Default strategy applied (LLM unavailable). Using {max_r} retries "
                f"with exponential backoff based on current policy. Failure analysis: "
                f"{analysis.get('reason', 'unknown error')}."
            ),
            "confidence": 0.55,
        }
