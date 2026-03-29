"""
Recovery Agent — Executes LLM-generated strategies.

Rather than using a fixed retry loop the agent now follows the strategy
produced by StrategyAgent: it respects the generated backoff list, runs
declared prechecks (logged but not blocking in simulation), and attaches
fallback options and root-cause reasoning to any escalation it creates.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from backend.utils.models import StepResult


class RecoveryAgent:
    name = "recovery_agent"

    def recover(
        self,
        step_name: str,
        employee: Dict[str, Any],
        policy: Dict[str, Any],
        execute_fn: Callable[[str, Dict[str, Any], int], StepResult],
        strategy: Optional[Dict[str, Any]] = None,
        failure_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the recovery strategy for a failed step.

        Parameters
        ----------
        step_name:        Name of the step to retry.
        employee:         Employee context dict.
        policy:           Base recovery policy from DEFAULT_RECOVERY_POLICY.
        execute_fn:       Callback that re-executes the step (injected by engine).
        strategy:         Optional dict from StrategyAgent (if LLM is available).
        failure_analysis: Optional dict from FailureDetectionAgent.

        Returns a recovery result dict with retry outcomes and/or escalation.
        """
        # ── Resolve effective parameters ────────────────────────────────────
        if strategy:
            rp = strategy.get("retry_policy", {})
            max_retries:        int         = min(int(rp.get("max_retries", policy.get("max_retries", 2))), 4)
            backoff:            List[float] = rp.get("backoff", policy.get("retry_backoff_seconds", []))
            prechecks:          List[str]   = strategy.get("prechecks", [])
            fallbacks:          List[str]   = strategy.get("fallbacks", [])
            escalation_target:  str         = strategy.get("escalation_target", policy.get("escalation_target", "it-ops@company.com"))
            strategy_name:      str         = strategy.get("strategy_name", "generated")
            strategy_justification: str     = strategy.get("justification", "")
        else:
            max_retries        = policy.get("max_retries", 0)
            backoff            = policy.get("retry_backoff_seconds", [])
            prechecks          = []
            fallbacks          = []
            escalation_target  = policy.get("escalation_target", "it-ops@company.com")
            strategy_name      = "default"
            strategy_justification = ""

        # ── Execute prechecks (logged; non-blocking in simulation) ──────────
        precheck_log: List[str] = []
        for check in prechecks:
            precheck_log.append(f"PRECHECK [{check}]: passed (simulated)")

        # ── Retry loop ───────────────────────────────────────────────────────
        retries: List[StepResult] = []
        attempt_log: List[str] = []

        for idx in range(max_retries):
            wait = backoff[idx] if idx < len(backoff) else 1.0
            # Cap sleep to 1.5 s in simulation so the demo stays snappy
            time.sleep(min(wait, 1.5))

            attempt_number = idx + 2  # attempt 1 already happened
            retry_result: StepResult = execute_fn(step_name, employee, attempt_number)
            retries.append(retry_result)

            outcome = "SUCCEEDED" if retry_result.status == "success" else "FAILED"
            attempt_log.append(
                f"Attempt {attempt_number} (wait={wait}s): {outcome}"
                + (f" — {retry_result.error_code}" if retry_result.error_code else "")
            )

            if retry_result.status == "success":
                return {
                    "recovered": True,
                    "recovery_mode": "retry",
                    "retry_results": retries,
                    "escalation": None,
                    "strategy_name": strategy_name,
                    "strategy_justification": strategy_justification,
                    "prechecks_run": precheck_log,
                    "reasoning": (
                        f"Strategy '{strategy_name}' recovered {step_name} on "
                        f"attempt {attempt_number}.\n"
                        + "\n".join(attempt_log)
                    ),
                }

        # ── All retries exhausted — escalate ────────────────────────────────
        root_cause = ""
        if failure_analysis:
            root_cause = failure_analysis.get("reasoning", failure_analysis.get("reason", ""))

        escalation_reason = (
            f"{step_name} failed after {max_retries + 1} total attempts "
            f"(strategy: {strategy_name})."
        )
        if root_cause:
            escalation_reason += f" Root cause: {root_cause}"

        escalation = {
            "type": "manual_intervention",
            "target": escalation_target,
            "reason": escalation_reason,
            "severity": failure_analysis.get("severity", "high") if failure_analysis else "high",
            "status": "open",
            "recommended_action": (
                failure_analysis.get("recommended_action", "escalate")
                if failure_analysis else "escalate"
            ),
            "fallback_options": fallbacks,
            "strategy_name": strategy_name,
            "ai_reasoning": root_cause,
        }

        return {
            "recovered": False,
            "recovery_mode": "escalation",
            "retry_results": retries,
            "escalation": escalation,
            "strategy_name": strategy_name,
            "strategy_justification": strategy_justification,
            "prechecks_run": precheck_log,
            "reasoning": (
                f"Strategy '{strategy_name}' exhausted all {max_retries} retries "
                f"for {step_name}. Escalating to {escalation_target}.\n"
                + "\n".join(attempt_log)
            ),
        }
