"""
EvoFlow AI — Workflow definitions and configuration.

Three workflow tracks (all required by Track 2 hackathon scenario pack):
  1. employee_onboarding  — 6 system integration steps
  2. meeting_action       — meeting transcript → tasks → notifications
  3. sla_breach           — SLA monitoring → rerouting → recovery

Failures are probabilistic (configurable per step), not hardcoded.
"""
from __future__ import annotations

# ── Workflow step definitions ─────────────────────────────────────────────────

ONBOARDING_STEPS = [
    "create_email_account",
    "create_slack_account",
    "create_jira_access",
    "assign_buddy",
    "schedule_orientation_meetings",
    "send_welcome_email",
]

MEETING_ACTION_STEPS = [
    "parse_transcript",
    "extract_action_items",
    "assign_owners",
    "create_tasks",
    "send_summary",
]

SLA_BREACH_STEPS = [
    "detect_breach_risk",
    "identify_bottleneck",
    "find_delegate",
    "reroute_approval",
    "log_override",
    "notify_stakeholders",
]

# ── Per-step failure simulation config ────────────────────────────────────────
# Each step has:
#   failure_probability: 0.0 (never) to 1.0 (always) — adjustable in UI
#   failure_modes: list of possible error codes when step fails
#   recoverable: whether the failure is worth retrying

DEFAULT_SIMULATION_CONFIG = {
    # Onboarding steps
    "create_email_account": {
        "failure_probability": 0.05,
        "failure_modes": ["EMAIL_QUOTA_EXCEEDED", "DOMAIN_NOT_CONFIGURED"],
        "recoverable": True,
    },
    "create_slack_account": {
        "failure_probability": 0.05,
        "failure_modes": ["SLACK_INVITE_FAILED", "CHANNEL_LIMIT_REACHED"],
        "recoverable": True,
    },
    "create_jira_access": {
        "failure_probability": 0.85,  # High — demonstrates recovery & evolution
        "failure_modes": ["JIRA_PROVISIONING_TIMEOUT", "JIRA_LICENSE_LIMIT", "JIRA_SSO_ERROR"],
        "recoverable": True,
    },
    "assign_buddy": {
        "failure_probability": 0.05,
        "failure_modes": ["NO_BUDDY_AVAILABLE", "HR_PORTAL_DOWN"],
        "recoverable": False,
    },
    "schedule_orientation_meetings": {
        "failure_probability": 0.05,
        "failure_modes": ["CALENDAR_CONFLICT", "CALENDAR_API_ERROR"],
        "recoverable": True,
    },
    "send_welcome_email": {
        "failure_probability": 0.03,
        "failure_modes": ["EMAIL_DELIVERY_FAILED", "SMTP_TIMEOUT"],
        "recoverable": True,
    },
    # Meeting action steps
    "parse_transcript": {
        "failure_probability": 0.05,
        "failure_modes": ["TRANSCRIPT_TOO_SHORT", "ENCODING_ERROR"],
        "recoverable": True,
    },
    "extract_action_items": {
        "failure_probability": 0.10,
        "failure_modes": ["NO_ACTION_ITEMS_FOUND", "LLM_TIMEOUT"],
        "recoverable": True,
    },
    "assign_owners": {
        "failure_probability": 0.15,  # Higher — ambiguous ownership is common
        "failure_modes": ["AMBIGUOUS_OWNER", "OWNER_NOT_IN_SYSTEM"],
        "recoverable": False,  # Needs human clarification
    },
    "create_tasks": {
        "failure_probability": 0.08,
        "failure_modes": ["PROJECT_TRACKER_DOWN", "DUPLICATE_TASK"],
        "recoverable": True,
    },
    "send_summary": {
        "failure_probability": 0.04,
        "failure_modes": ["EMAIL_DELIVERY_FAILED", "INVALID_RECIPIENT"],
        "recoverable": True,
    },
    # SLA breach steps
    "detect_breach_risk": {
        "failure_probability": 0.05,
        "failure_modes": ["DATA_PIPELINE_STALE", "METRICS_UNAVAILABLE"],
        "recoverable": True,
    },
    "identify_bottleneck": {
        "failure_probability": 0.08,
        "failure_modes": ["INSUFFICIENT_AUDIT_DATA", "LLM_TIMEOUT"],
        "recoverable": True,
    },
    "find_delegate": {
        "failure_probability": 0.20,  # Delegate may not exist
        "failure_modes": ["NO_DELEGATE_CONFIGURED", "ALL_DELEGATES_ON_LEAVE"],
        "recoverable": False,
    },
    "reroute_approval": {
        "failure_probability": 0.10,
        "failure_modes": ["APPROVAL_SYSTEM_DOWN", "PERMISSION_DENIED"],
        "recoverable": True,
    },
    "log_override": {
        "failure_probability": 0.03,
        "failure_modes": ["AUDIT_WRITE_FAILED"],
        "recoverable": True,
    },
    "notify_stakeholders": {
        "failure_probability": 0.05,
        "failure_modes": ["EMAIL_DELIVERY_FAILED", "SLACK_WEBHOOK_ERROR"],
        "recoverable": True,
    },
}

# ── Recovery policies ─────────────────────────────────────────────────────────

DEFAULT_RECOVERY_POLICY = {
    "create_jira_access": {
        "max_retries": 2,
        "retry_backoff_seconds": [0.8, 1.0, 1.2, 1.5],
        "escalation_target": "it-ops@company.com",
    },
    "create_email_account": {
        "max_retries": 2,
        "retry_backoff_seconds": [0.5, 1.0],
        "escalation_target": "it-ops@company.com",
    },
    "create_slack_account": {
        "max_retries": 2,
        "retry_backoff_seconds": [0.5, 1.0],
        "escalation_target": "it-ops@company.com",
    },
    "create_tasks": {
        "max_retries": 2,
        "retry_backoff_seconds": [0.5, 1.0],
        "escalation_target": "project-ops@company.com",
    },
    "reroute_approval": {
        "max_retries": 2,
        "retry_backoff_seconds": [0.5, 1.0],
        "escalation_target": "workflow-ops@company.com",
    },
}

# ── Impact model assumptions (for ROI quantification) ────────────────────────

IMPACT_MODEL = {
    "employee_onboarding": {
        "manual_hours_per_run": 4.0,        # Hours an HR/IT person spends manually
        "agent_hours_per_run": 0.05,         # Agent execution time
        "hourly_cost_usd": 45.0,             # Fully-loaded HR/IT cost per hour
        "onboardings_per_month": 20,
        "error_rate_manual": 0.25,           # 25% of manual onboardings have errors
        "error_remediation_hours": 2.0,      # Hours to fix a manual error
        "time_to_productive_days_manual": 5,
        "time_to_productive_days_agent": 1,
    },
    "meeting_action": {
        "manual_hours_per_meeting": 1.5,     # Writing minutes, assigning tasks
        "agent_hours_per_meeting": 0.02,
        "hourly_cost_usd": 60.0,
        "meetings_per_month": 80,
        "follow_up_miss_rate_manual": 0.35,  # 35% of action items get dropped
        "revenue_per_deal_usd": 25000,
        "deals_affected_per_month": 3,
    },
    "sla_breach": {
        "avg_sla_penalty_usd": 15000,        # Per breach
        "breaches_prevented_per_month": 2,
        "manual_hours_per_breach": 6.0,      # Firefighting
        "agent_hours_per_breach": 0.1,
        "hourly_cost_usd": 70.0,
    },
}

# ── Workflow metadata ─────────────────────────────────────────────────────────

WORKFLOW_TYPES = {
    "employee_onboarding": {
        "label": "Employee Onboarding",
        "description": "Automates account creation, buddy assignment, and orientation across 3 systems",
        "steps": ONBOARDING_STEPS,
        "icon": "👤",
    },
    "meeting_action": {
        "label": "Meeting to Action",
        "description": "Extracts action items from meeting transcripts, assigns owners, creates tasks",
        "steps": MEETING_ACTION_STEPS,
        "icon": "📋",
    },
    "sla_breach": {
        "label": "SLA Breach Prevention",
        "description": "Detects SLA breach risk, identifies bottleneck, reroutes approvals",
        "steps": SLA_BREACH_STEPS,
        "icon": "⚡",
    },
}

# ── Deterministic demo scenarios ──────────────────────────────────────────────
# Each scenario defines a simulation_config with fixed seed + failure probs.
# Use by passing simulation_config=DEMO_SCENARIOS["scenario_name"] to the engine.

DEMO_SCENARIOS = {
    "happy_path": {
        "label": "Happy Path — All steps succeed",
        "seed": 42,
        "config": {step: {"failure_probability": 0.0} for step in ONBOARDING_STEPS},
    },
    "jira_failure": {
        "label": "Jira Failure — Recovery + Escalation demo",
        "seed": 42,
        "config": {
            **{step: {"failure_probability": 0.0} for step in ONBOARDING_STEPS},
            "create_jira_access": {
                "failure_probability": 1.0,
                "failure_modes": ["JIRA_PROVISIONING_TIMEOUT"],
            },
        },
    },
    "multi_failure": {
        "label": "Multi-System Failure — Shows breadth of recovery",
        "seed": 42,
        "config": {
            "create_email_account":          {"failure_probability": 0.0},
            "create_slack_account":          {"failure_probability": 0.8, "failure_modes": ["SLACK_INVITE_FAILED"]},
            "create_jira_access":            {"failure_probability": 1.0, "failure_modes": ["JIRA_PROVISIONING_TIMEOUT"]},
            "assign_buddy":                  {"failure_probability": 0.0},
            "schedule_orientation_meetings": {"failure_probability": 0.7, "failure_modes": ["CALENDAR_CONFLICT"]},
            "send_welcome_email":            {"failure_probability": 0.0},
        },
    },
    "full_demo": {
        "label": "Full Demo — Showcase all system capabilities",
        "seed": 123,
        "config": {
            **{step: {"failure_probability": 0.0} for step in ONBOARDING_STEPS},
            "create_jira_access": {
                "failure_probability": 1.0,
                "failure_modes": ["JIRA_PROVISIONING_TIMEOUT"],
            },
        },
    },
}
