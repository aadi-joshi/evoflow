"""
Integration test — full workflow run without OpenAI API key.

Validates that:
  - The workflow executes all 6 steps end-to-end
  - Jira failure is detected and recovery is attempted
  - Escalation is created and persisted
  - Evolution runs and produces a reasoning string
  - Audit file is written with llm_trace fields
  - All required SSE event types are emitted

Uses simulation_config to force Jira failures deterministically.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "")  # no LLM calls in integration tests

import pytest
from backend.services.workflow_engine import WorkflowEngine


EMPLOYEE = {
    "employee_id": "E-INT-001",
    "full_name": "Integration Tester",
    "email": "integration@company.com",
    "department": "QA",
    "role": "QA Engineer",
    "location": "Remote",
    "start_date": "2026-05-01",
}

# Force Jira to always fail with a transient (recoverable) error in tests
FORCED_SIM_CONFIG = {
    "create_jira_access": {
        "failure_probability": 1.0,
        "failure_modes": ["JIRA_PROVISIONING_TIMEOUT"],  # always transient → recoverable
    },
    "create_email_account":          {"failure_probability": 0.0},
    "create_slack_account":          {"failure_probability": 0.0},
    "assign_buddy":                  {"failure_probability": 0.0},
    "schedule_orientation_meetings": {"failure_probability": 0.0},
    "send_welcome_email":            {"failure_probability": 0.0},
}


@pytest.fixture()
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def run_workflow(data_dir: Path):
    """Run the full workflow, collect all emitted events."""
    events = []
    engine = WorkflowEngine(data_dir=data_dir, simulation_config=FORCED_SIM_CONFIG)
    result = engine.run_onboarding(
        EMPLOYEE,
        event_callback=lambda t, d: events.append({"type": t, "data": d}),
    )
    return result, events


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestFullWorkflow:
    def test_workflow_completes(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        assert result is not None
        run = result["run"]
        assert run["status"] in ("completed", "completed_with_escalation")

    def test_all_steps_present_in_results(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        step_names = {r["step_name"] for r in result["run"]["results"]}
        expected = {
            "create_email_account", "create_slack_account", "create_jira_access",
            "assign_buddy", "schedule_orientation_meetings", "send_welcome_email",
        }
        assert expected == step_names

    def test_jira_failure_detected(self, tmp_data_dir):
        result, events = run_workflow(tmp_data_dir)
        failed_events = [e for e in events if e["type"] == "step_failed"]
        assert any("jira" in e["data"]["step_name"] for e in failed_events)

    def test_escalation_created(self, tmp_data_dir):
        result, events = run_workflow(tmp_data_dir)
        esc_events = [e for e in events if e["type"] == "escalation_created"]
        assert len(esc_events) >= 1

    def test_strategy_generated_event_emitted(self, tmp_data_dir):
        result, events = run_workflow(tmp_data_dir)
        strat_events = [e for e in events if e["type"] == "strategy_generated"]
        assert len(strat_events) >= 1

    def test_strategy_has_retry_policy(self, tmp_data_dir):
        result, events = run_workflow(tmp_data_dir)
        strat = next(e["data"] for e in events if e["type"] == "strategy_generated")
        assert "retry_policy" in strat
        assert strat["retry_policy"]["max_retries"] >= 1

    def test_ai_reasoning_events_emitted(self, tmp_data_dir):
        result, events = run_workflow(tmp_data_dir)
        reasoning_events = [e for e in events if e["type"] == "ai_reasoning"]
        assert len(reasoning_events) >= 1

    def test_evolution_has_reasoning(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        evo = result["evolution"]
        assert "reasoning" in evo
        assert len(evo["reasoning"]) > 5

    def test_evolution_has_changes_made(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        assert "changes_made" in result["evolution"]

    def test_audit_file_written(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        run_id = result["run"]["run_id"]
        audit_file = tmp_data_dir / f"audit_{run_id}.json"
        assert audit_file.exists()

    def test_audit_file_has_llm_trace(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        run_id = result["run"]["run_id"]
        raw = json.loads((tmp_data_dir / f"audit_{run_id}.json").read_text())
        # Support new hash-chained format (events under "events" key)
        events = raw.get("events", raw) if isinstance(raw, dict) else raw
        traces = [e for e in events if "llm_trace" in e]
        assert len(traces) >= 1
        for t in traces:
            assert "ai_generated" in t["llm_trace"]

    def test_learning_state_persisted(self, tmp_data_dir):
        run_workflow(tmp_data_dir)
        state_file = tmp_data_dir / "learning_state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["total_runs"] >= 1
        assert "strategy_history" in state
        assert "reasoning_history" in state

    def test_second_run_updates_strategy(self, tmp_data_dir):
        before_state_file = tmp_data_dir / "learning_state.json"
        before_runs = 0
        if before_state_file.exists():
            before_runs = json.loads(before_state_file.read_text()).get("total_runs", 0)

        run_workflow(tmp_data_dir)
        run_workflow(tmp_data_dir)
        state = json.loads((tmp_data_dir / "learning_state.json").read_text())
        assert state["total_runs"] == before_runs + 2
        # After persistent Jira failures, max_retries should have increased or stayed >= 2
        assert state["strategy"]["jira"]["max_retries"] >= 2

    def test_non_jira_steps_succeed(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        step_status = result["run"]["metrics"]["latest_step_status"]
        for step in ["create_email_account", "create_slack_account",
                     "assign_buddy", "schedule_orientation_meetings", "send_welcome_email"]:
            assert step_status.get(step) == "success", f"{step} should succeed"

    def test_metrics_present(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        metrics = result["run"]["metrics"]
        for key in ("total_step_events", "distinct_steps", "failed_events",
                    "escalation_count", "latest_step_status"):
            assert key in metrics

    def test_required_sse_events_emitted(self, tmp_data_dir):
        _, events = run_workflow(tmp_data_dir)
        emitted = {e["type"] for e in events}
        required = {
            "plan_created", "step_started", "step_executed",
            "step_success", "step_failed", "step_retry",
            "recovery_attempted", "escalation_created",
            "strategy_generated", "run_completed", "integration_delivery",
            "strategy_evolved", "audit_exported",
        }
        missing = required - emitted
        assert not missing, f"Missing SSE events: {missing}"

    def test_integration_receipts_in_run_payload(self, tmp_data_dir):
        result, events = run_workflow(tmp_data_dir)
        receipts = result["run"].get("integration_receipts", [])
        assert receipts, "Expected integration receipts in run payload"
        assert any(receipt.get("provider") == "slack" for receipt in receipts)

    def test_impact_computed(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        impact = result["run"].get("impact", {})
        assert "time_saved_hours_per_run" in impact
        assert "monthly_cost_savings_usd" in impact
        assert impact["monthly_cost_savings_usd"] > 0

    def test_workflow_type_in_state(self, tmp_data_dir):
        result, _ = run_workflow(tmp_data_dir)
        assert result["run"]["workflow_type"] == "employee_onboarding"
