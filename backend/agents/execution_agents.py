"""
Execution Agents — EvoFlow AI.

Handles step execution for all three workflow types:
  1. employee_onboarding  — system integration steps (Email, Slack, Jira, etc.)
  2. meeting_action       — LLM-native steps (parse transcript, extract, assign)
  3. sla_breach           — LLM-native steps (detect risk, find delegate, reroute)

Failures are probabilistic — each step has a configurable failure_probability.
No step always fails; probabilities are seeded from simulation_config.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.integrations import (
    notify_slack_onboarding,
    send_welcome_email_real,
)
from backend.services.llm_service import generate_response
from backend.utils.constants import DEFAULT_SIMULATION_CONFIG
from backend.utils.models import StepResult


class ExecutionAgents:
    name = "execution_agents"

    def execute_step(
        self,
        step_name: str,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        simulation_config: Optional[Dict[str, Any]] = None,
        attempt: int = 1,
    ) -> StepResult:
        """
        Execute a single workflow step.

        simulation_config overrides DEFAULT_SIMULATION_CONFIG per step.
        """
        cfg = dict(DEFAULT_SIMULATION_CONFIG.get(step_name, {}))
        if simulation_config and step_name in simulation_config:
            cfg.update(simulation_config[step_name])

        start_ts = datetime.now(timezone.utc).isoformat()

        # ── Probabilistic failure simulation ──────────────────────────────────
        failure_prob = cfg.get("failure_probability", 0.05)
        # Use seed from simulation_config for deterministic/reproducible runs
        seed = cfg.get("seed", None)
        rng = random.Random(seed)
        if rng.random() < failure_prob:
            modes = cfg.get("failure_modes", ["UNKNOWN_ERROR"])
            error_code = rng.choice(modes)
            end_ts = datetime.now(timezone.utc).isoformat()
            return StepResult(
                step_id=f"{step_name}:{attempt}",
                step_name=step_name,
                status="failed",
                message=self._failure_message(step_name, error_code, input_data),
                attempts=attempt,
                error_code=error_code,
                payload={
                    "system":       self._map_system(step_name),
                    "failure_type": "simulated_probabilistic",
                    "attempt":      attempt,
                },
                start_ts=start_ts,
                end_ts=end_ts,
            )

        # ── LLM-native steps for meeting_action & sla_breach ──────────────────
        llm_steps = {
            "parse_transcript", "extract_action_items", "assign_owners",
            "create_tasks", "send_summary",
            "detect_breach_risk", "identify_bottleneck", "find_delegate",
            "reroute_approval", "log_override", "notify_stakeholders",
        }
        if step_name in llm_steps:
            return self._execute_llm_step(step_name, input_data, context, attempt, start_ts)

        # ── System integration steps (onboarding) ─────────────────────────────
        return self._execute_integration_step(step_name, input_data, attempt, start_ts)

    # ─── LLM-native execution ─────────────────────────────────────────────────

    def _execute_llm_step(
        self,
        step_name: str,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        attempt: int,
        start_ts: str,
    ) -> StepResult:
        prompt, schema = self._build_llm_prompt(step_name, input_data, context)
        result, audit = generate_response(prompt, schema, temperature=0.2, complexity="high")
        end_ts = datetime.now(timezone.utc).isoformat()

        # Check if LLM flagged an error condition
        error_code = result.get("error_code") or (None if audit.get("ai_generated") else "LLM_UNAVAILABLE")
        status = "failed" if error_code else "success"

        return StepResult(
            step_id=f"{step_name}:{attempt}",
            step_name=step_name,
            status=status,
            message=result.get("message", f"{step_name} completed"),
            attempts=attempt,
            error_code=error_code,
            payload={
                **result,
                "system":       self._map_system(step_name),
                "attempt":      attempt,
                "ai_generated": audit.get("ai_generated", False),
                "model":        audit.get("model"),
            },
            start_ts=start_ts,
            end_ts=end_ts,
        )

    def _build_llm_prompt(
        self,
        step_name: str,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ):
        """Return (prompt_str, json_schema) for each LLM-native step."""
        transcript = input_data.get("transcript", "")
        participants = input_data.get("participants", [])
        action_items = context.get("action_items", [])

        if step_name == "parse_transcript":
            prompt = (
                f"You are processing a meeting transcript for EvoFlow AI.\n\n"
                f"TRANSCRIPT:\n{transcript}\n\n"
                f"Extract all participants mentioned and the meeting topic. "
                f"Identify if this transcript has enough content to extract action items."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":         {"type": "string"},
                    "participants_found": {"type": "array", "items": {"type": "string"}},
                    "meeting_topic":   {"type": "string"},
                    "word_count":      {"type": "integer"},
                    "parseable":       {"type": "boolean"},
                    "error_code":      {"type": "string"},
                },
                "required": ["message", "participants_found", "meeting_topic", "parseable"],
            }

        elif step_name == "extract_action_items":
            prompt = (
                f"Extract all action items from this meeting transcript.\n\n"
                f"TRANSCRIPT:\n{transcript}\n\n"
                f"PARTICIPANTS: {json.dumps(participants)}\n\n"
                f"For each action item identify: what needs to be done, who is responsible, "
                f"and when it is due. If ownership is unclear, mark ambiguous=true and explain why."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "action_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":               {"type": "string"},
                                "description":      {"type": "string"},
                                "owner":            {"type": "string"},
                                "owner_email":      {"type": "string"},
                                "due_date":         {"type": "string"},
                                "priority":         {"type": "string"},
                                "ambiguous":        {"type": "boolean"},
                                "ambiguity_reason": {"type": "string"},
                            },
                        },
                    },
                    "total_count":     {"type": "integer"},
                    "ambiguous_count": {"type": "integer"},
                    "error_code":      {"type": "string"},
                },
                "required": ["message", "action_items", "total_count"],
            }

        elif step_name == "assign_owners":
            items_json = json.dumps(action_items, indent=2)
            prompt = (
                f"Review these action items extracted from a meeting and confirm ownership.\n\n"
                f"ACTION ITEMS:\n{items_json}\n\n"
                f"PARTICIPANTS IN MEETING: {json.dumps(participants)}\n\n"
                f"For items marked ambiguous=true, determine if you can resolve ownership "
                f"from context. If you cannot resolve an owner, set error_code=AMBIGUOUS_OWNER "
                f"on that item and explain the ambiguity_reason clearly."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "resolved_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":               {"type": "string"},
                                "description":      {"type": "string"},
                                "owner":            {"type": "string"},
                                "owner_email":      {"type": "string"},
                                "due_date":         {"type": "string"},
                                "priority":         {"type": "string"},
                                "ambiguous":        {"type": "boolean"},
                                "ambiguity_reason": {"type": "string"},
                                "error_code":       {"type": "string"},
                            },
                        },
                    },
                    "unresolved_count": {"type": "integer"},
                    "error_code": {"type": "string"},
                },
                "required": ["message", "resolved_items", "unresolved_count"],
            }

        elif step_name == "create_tasks":
            items_json = json.dumps(action_items, indent=2)
            prompt = (
                f"Create tasks in the project tracker for these action items.\n\n"
                f"ACTION ITEMS TO CREATE:\n{items_json}\n\n"
                f"Generate realistic task references (e.g. TASK-1234) and confirm creation."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "tasks_created": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action_item_id": {"type": "string"},
                                "task_ref":       {"type": "string"},
                                "url":            {"type": "string"},
                                "assigned_to":    {"type": "string"},
                            },
                        },
                    },
                    "count": {"type": "integer"},
                    "error_code": {"type": "string"},
                },
                "required": ["message", "tasks_created", "count"],
            }

        elif step_name == "send_summary":
            items_json = json.dumps(action_items, indent=2)
            prompt = (
                f"Compose a meeting summary email for these participants.\n\n"
                f"PARTICIPANTS: {json.dumps(participants)}\n"
                f"ACTION ITEMS ASSIGNED:\n{items_json}\n\n"
                f"Write a professional, concise summary (3-5 sentences) and confirm delivery."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":     {"type": "string"},
                    "email_body":  {"type": "string"},
                    "recipients":  {"type": "array", "items": {"type": "string"}},
                    "error_code":  {"type": "string"},
                },
                "required": ["message", "email_body", "recipients"],
            }

        # ── SLA breach steps ───────────────────────────────────────────────────

        elif step_name == "detect_breach_risk":
            approval = input_data.get("approval", {})
            prompt = (
                f"Analyze this SLA breach risk scenario.\n\n"
                f"APPROVAL DETAILS:\n{json.dumps(approval, indent=2)}\n\n"
                f"Calculate: time remaining, breach probability (0-1), urgency level. "
                f"Consider that an approval stuck for >48h with <72h remaining is critical."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":             {"type": "string"},
                    "hours_remaining":     {"type": "number"},
                    "breach_probability":  {"type": "number"},
                    "urgency":             {"type": "string"},
                    "risk_factors":        {"type": "array", "items": {"type": "string"}},
                    "error_code":          {"type": "string"},
                },
                "required": ["message", "hours_remaining", "breach_probability", "urgency"],
            }

        elif step_name == "identify_bottleneck":
            approval = input_data.get("approval", {})
            prompt = (
                f"Identify why this approval is stuck.\n\n"
                f"APPROVAL:\n{json.dumps(approval, indent=2)}\n\n"
                f"Based on the approver name and stuck duration, determine the most likely "
                f"reason (on leave, overloaded, needs clarification, system issue). "
                f"Be specific about who is the bottleneck and why."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":         {"type": "string"},
                    "bottleneck_type": {"type": "string"},
                    "bottleneck_owner": {"type": "string"},
                    "reason":          {"type": "string"},
                    "confidence":      {"type": "number"},
                    "error_code":      {"type": "string"},
                },
                "required": ["message", "bottleneck_type", "bottleneck_owner", "reason"],
            }

        elif step_name == "find_delegate":
            approval = input_data.get("approval", {})
            org_chart = input_data.get("org_chart", {})
            prompt = (
                f"Find an appropriate delegate for this stuck approval.\n\n"
                f"ORIGINAL APPROVER: {approval.get('approver_name')} ({approval.get('approver_role')})\n"
                f"ORG CHART:\n{json.dumps(org_chart, indent=2)}\n\n"
                f"Identify the best delegate: their manager or a peer with equivalent authority. "
                f"If no suitable delegate exists, set error_code=NO_DELEGATE_CONFIGURED."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":         {"type": "string"},
                    "delegate_name":   {"type": "string"},
                    "delegate_email":  {"type": "string"},
                    "delegate_role":   {"type": "string"},
                    "delegation_basis": {"type": "string"},
                    "error_code":      {"type": "string"},
                },
                "required": ["message", "delegate_name", "delegate_email"],
            }

        elif step_name == "reroute_approval":
            approval = input_data.get("approval", {})
            delegate = context.get("delegate", {})
            prompt = (
                f"Reroute this approval to the identified delegate.\n\n"
                f"APPROVAL: {json.dumps(approval, indent=2)}\n"
                f"DELEGATE: {json.dumps(delegate, indent=2)}\n\n"
                f"Generate the rerouting confirmation with a unique override ID and timestamp."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":     {"type": "string"},
                    "override_id": {"type": "string"},
                    "rerouted_to": {"type": "string"},
                    "rerouted_at": {"type": "string"},
                    "sla_impact":  {"type": "string"},
                    "error_code":  {"type": "string"},
                },
                "required": ["message", "override_id", "rerouted_to"],
            }

        elif step_name == "log_override":
            override = context.get("override", {})
            approval = input_data.get("approval", {})
            prompt = (
                f"Create an immutable audit log entry for this approval override.\n\n"
                f"ORIGINAL APPROVAL: {json.dumps(approval, indent=2)}\n"
                f"OVERRIDE DETAILS: {json.dumps(override, indent=2)}\n\n"
                f"Generate a compliance-ready audit record with full justification chain."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":      {"type": "string"},
                    "audit_ref":    {"type": "string"},
                    "justification": {"type": "string"},
                    "compliance_flags": {"type": "array", "items": {"type": "string"}},
                    "error_code":   {"type": "string"},
                },
                "required": ["message", "audit_ref", "justification"],
            }

        elif step_name == "notify_stakeholders":
            approval = input_data.get("approval", {})
            override = context.get("override", {})
            prompt = (
                f"Notify all stakeholders about this SLA override.\n\n"
                f"APPROVAL: {json.dumps(approval, indent=2)}\n"
                f"OVERRIDE: {json.dumps(override, indent=2)}\n\n"
                f"Draft notifications for: original approver, delegate, requester, and manager. "
                f"Keep each message under 3 sentences."
            )
            schema = {
                "type": "object",
                "properties": {
                    "message":      {"type": "string"},
                    "notifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "recipient": {"type": "string"},
                                "channel":   {"type": "string"},
                                "body":      {"type": "string"},
                            },
                        },
                    },
                    "count":      {"type": "integer"},
                    "error_code": {"type": "string"},
                },
                "required": ["message", "notifications", "count"],
            }

        else:
            # Generic fallback for unknown LLM steps
            prompt = f"Execute step '{step_name}' for: {json.dumps(input_data, indent=2)}"
            schema = {
                "type": "object",
                "properties": {
                    "message":    {"type": "string"},
                    "error_code": {"type": "string"},
                },
                "required": ["message"],
            }

        return prompt, schema

    # ─── Integration step execution (onboarding) ──────────────────────────────

    def _execute_integration_step(
        self,
        step_name: str,
        employee: Dict[str, Any],
        attempt: int,
        start_ts: str,
    ) -> StepResult:
        name  = employee.get("full_name", "Unknown")
        eid   = employee.get("employee_id", "?")
        email = employee.get("email", "")
        dept  = employee.get("department", "")
        start = employee.get("start_date", "")

        integration_meta: Dict[str, Any] = {}

        # Real API calls for applicable steps
        if step_name == "send_welcome_email":
            result = send_welcome_email_real(email, name, dept, start)
            integration_meta = {
                "integration":       "smtp",
                "real_call":         True,
                "provider_success":  result.success,
                "latency_ms":        result.latency_ms,
                "response_metadata": result.response_metadata,
            }
            if not result.success:
                end_ts = datetime.now(timezone.utc).isoformat()
                return StepResult(
                    step_id=f"{step_name}:{attempt}",
                    step_name=step_name,
                    status="failed",
                    message=f"Email delivery failed: {result.error_detail}",
                    attempts=attempt,
                    error_code=result.error_code or "EMAIL_DELIVERY_FAILED",
                    payload={"system": "notification", **integration_meta},
                    start_ts=start_ts,
                    end_ts=end_ts,
                )

        elif step_name == "create_slack_account":
            result = notify_slack_onboarding(name, dept)
            integration_meta = {
                "integration":       "slack",
                "real_call":         True,
                "provider_success":  result.success,
                "latency_ms":        result.latency_ms,
                "response_metadata": result.response_metadata,
            }
            if not result.success:
                end_ts = datetime.now(timezone.utc).isoformat()
                return StepResult(
                    step_id=f"{step_name}:{attempt}",
                    step_name=step_name,
                    status="failed",
                    message=f"Slack notification failed: {result.error_detail}",
                    attempts=attempt,
                    error_code=result.error_code or "SLACK_INVITE_FAILED",
                    payload={"system": "slack", **integration_meta},
                    start_ts=start_ts,
                    end_ts=end_ts,
                )

        end_ts = datetime.now(timezone.utc).isoformat()
        return StepResult(
            step_id=f"{step_name}:{attempt}",
            step_name=step_name,
            status="success",
            message=f"{step_name} completed for {name}",
            attempts=attempt,
            error_code=None,
            payload={
                "system":       self._map_system(step_name),
                "resource_ref": f"{step_name}:{eid}",
                "attempt":      attempt,
                **integration_meta,
            },
            start_ts=start_ts,
            end_ts=end_ts,
        )

    def _failure_message(
        self, step_name: str, error_code: str, input_data: Dict[str, Any]
    ) -> str:
        target = (
            input_data.get("email")
            or input_data.get("approval", {}).get("approval_id")
            or input_data.get("approval_id")
            or "target"
        )
        return f"{step_name} failed for {target}: {error_code}"

    @staticmethod
    def _map_system(step_name: str) -> str:
        mapping = {
            "email":         "google-workspace",
            "slack":         "slack",
            "jira":          "jira",
            "buddy":         "hr-portal",
            "orientation":   "calendar",
            "welcome":       "notification",
            "transcript":    "meeting-intelligence",
            "action":        "meeting-intelligence",
            "owners":        "hr-portal",
            "tasks":         "project-tracker",
            "summary":       "email",
            "breach":        "sla-monitor",
            "bottleneck":    "workflow-analytics",
            "delegate":      "org-chart",
            "reroute":       "approval-system",
            "override":      "audit-log",
            "stakeholders":  "notification",
        }
        for keyword, system in mapping.items():
            if keyword in step_name:
                return system
        return "internal"
