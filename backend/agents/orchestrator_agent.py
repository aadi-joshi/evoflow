"""
Orchestrator Agent — LLM-enhanced plan creation for all workflow types.

Builds an ordered execution plan with AI-generated criticality assessments,
step rationale, and dynamic recovery policies.
Falls back to deterministic ordering if LLM is unavailable.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from backend.services.llm_service import generate_response
from backend.utils.constants import (
    MEETING_ACTION_STEPS,
    ONBOARDING_STEPS,
    SLA_BREACH_STEPS,
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_name":   {"type": "string"},
                    "criticality": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "rationale":   {"type": "string"},
                    "depends_on":  {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "plan_reasoning": {"type": "string"},
        "confidence":     {"type": "number"},
    },
    "required": ["plan", "plan_reasoning", "confidence"],
}

_STEP_CRITICALITY_DEFAULTS = {
    # Onboarding
    "create_email_account":          "critical",
    "create_slack_account":          "high",
    "create_jira_access":            "high",
    "assign_buddy":                  "medium",
    "schedule_orientation_meetings": "high",
    "send_welcome_email":            "critical",
    # Meeting action
    "parse_transcript":    "critical",
    "extract_action_items": "critical",
    "assign_owners":       "high",
    "create_tasks":        "high",
    "send_summary":        "medium",
    # SLA breach
    "detect_breach_risk":  "critical",
    "identify_bottleneck": "critical",
    "find_delegate":       "critical",
    "reroute_approval":    "critical",
    "log_override":        "high",
    "notify_stakeholders": "medium",
}


class OrchestratorAgent:
    name = "orchestrator_agent"

    def create_plan_with_audit(
        self,
        input_data: Dict[str, Any],
        strategy: Dict[str, Any],
        workflow_type: str = "employee_onboarding",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        steps = self._steps_for_workflow(workflow_type)
        llm_metadata, llm_audit = self._get_llm_metadata(input_data, strategy, steps, workflow_type)
        plan = self._build_plan(steps, llm_metadata, strategy, llm_audit)
        return plan, llm_audit

    # Keep backward compat for existing callers
    def create_plan(
        self,
        employee: Dict[str, Any],
        strategy: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        plan, _ = self.create_plan_with_audit(employee, strategy, "employee_onboarding")
        return plan

    # ─── Private ─────────────────────────────────────────────────────────────

    @staticmethod
    def _steps_for_workflow(workflow_type: str) -> List[str]:
        if workflow_type == "meeting_action":
            return MEETING_ACTION_STEPS
        if workflow_type == "sla_breach":
            return SLA_BREACH_STEPS
        return ONBOARDING_STEPS

    def _build_plan(
        self,
        steps: List[str],
        llm_metadata: List[Dict[str, Any]],
        strategy: Dict[str, Any],
        llm_audit: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        jira_max_retries = strategy.get("jira", {}).get("max_retries", 2)
        meta_by_step = {s["step_name"]: s for s in llm_metadata}
        plan = []
        for step in steps:
            meta = meta_by_step.get(step, {})
            criticality = meta.get("criticality") or _STEP_CRITICALITY_DEFAULTS.get(step, "medium")
            plan.append({
                "step_name":   step,
                "criticality": criticality,
                "rationale":   meta.get("rationale", f"Required workflow step: {step}"),
                "depends_on":  meta.get("depends_on", []),
                "recovery_policy": {
                    "max_retries": jira_max_retries if step == "create_jira_access" else 2,
                    "retry_backoff_seconds": [0.5, 1.0, 1.5, 2.0],
                    "escalation_target": "it-ops@company.com",
                },
                "ai_generated": llm_audit.get("ai_generated", False),
            })
        return plan

    def _get_llm_metadata(
        self,
        input_data: Dict[str, Any],
        strategy: Dict[str, Any],
        steps: List[str],
        workflow_type: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        prompt = (
            f"You are the Orchestrator Agent for EvoFlow AI.\n\n"
            f"Workflow type: {workflow_type}\n"
            f"Input: {json.dumps(input_data, default=str)}\n"
            f"Evolved strategy: {json.dumps(strategy)}\n\n"
            f"Steps to execute (in this order): {json.dumps(steps)}\n\n"
            "For each step provide:\n"
            "- criticality: how critical this step is (low/medium/high/critical)\n"
            "- rationale: one sentence explaining why this step matters for this specific case\n"
            "- depends_on: list of step names this step logically depends on\n\n"
            "Also provide plan_reasoning and confidence."
        )
        llm_response, llm_audit = generate_response(
            prompt, _OUTPUT_SCHEMA, temperature=0.3, complexity="low"
        )
        if llm_audit.get("ai_generated"):
            return llm_response.get("plan", []), llm_audit
        return [], llm_audit
