from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StepResult:
    step_id: str
    step_name: str
    status: str
    message: str
    attempts: int = 1
    error_code: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    start_ts: str = field(default_factory=utc_now)
    end_ts: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionItem:
    """A task extracted from a meeting transcript."""
    id: str
    description: str
    owner: Optional[str] = None
    owner_email: Optional[str] = None
    due_date: Optional[str] = None
    priority: str = "medium"
    ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    task_ref: Optional[str] = None  # Created task ID in project tracker

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalRecord:
    """An approval that needs to be rerouted due to SLA risk."""
    approval_id: str
    description: str
    original_approver: str
    original_approver_email: str
    stuck_since: str
    sla_deadline: str
    hours_remaining: float
    delegate: Optional[str] = None
    delegate_email: Optional[str] = None
    rerouted: bool = False
    override_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowState:
    workflow_type: str
    input_data: Dict[str, Any]
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = field(default_factory=utc_now)
    finished_at: Optional[str] = None
    status: str = "running"
    context: Dict[str, Any] = field(default_factory=dict)
    plan: List[Dict[str, Any]] = field(default_factory=list)
    results: List[StepResult] = field(default_factory=list)
    escalations: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    impact: Dict[str, Any] = field(default_factory=dict)
    clarifications: List[Dict[str, Any]] = field(default_factory=list)

    # Keep backward compat — onboarding callers use state.employee
    @property
    def employee(self) -> Dict[str, Any]:
        return self.input_data

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["results"] = [result.to_dict() for result in self.results]
        return data
