"""
Tests for EvoFlow AI enhancements:
  1. Hash-chained tamper-proof audit
  2. Checkpoint save/load/cleanup
  3. Deterministic demo mode (seeded RNG)
  4. Benchmark baseline vs adaptive
  5. Enhanced metrics (MTTR, rates)
  6. Evolution all-step tracking
  7. Notification service
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "")

import pytest
from backend.utils.models import StepResult, utc_now


# ─── Audit Hash Chain ─────────────────────────────────────────────────────────

class TestAuditHashChain:
    def setup_method(self):
        from backend.agents.audit_agent import AuditAgent
        self.agent = AuditAgent()

    def test_hash_chain_integrity(self):
        self.agent.log("run-1", "test", "action_1", {"data": 1})
        self.agent.log("run-1", "test", "action_2", {"data": 2})
        self.agent.log("run-1", "test", "action_3", {"data": 3})
        assert self.agent.verify_chain() is True

    def test_each_record_has_hash_fields(self):
        self.agent.log("run-1", "test", "action_1", {"data": 1})
        event = self.agent.events[0]
        assert "prev_hash" in event
        assert "record_hash" in event
        assert event["prev_hash"] == "GENESIS"

    def test_hash_chain_links(self):
        self.agent.log("run-1", "test", "action_1", {"data": 1})
        self.agent.log("run-1", "test", "action_2", {"data": 2})
        assert self.agent.events[1]["prev_hash"] == self.agent.events[0]["record_hash"]

    def test_tamper_detection(self):
        self.agent.log("run-1", "test", "action_1", {"data": 1})
        self.agent.log("run-1", "test", "action_2", {"data": 2})
        # Tamper with the first record
        self.agent.events[0]["payload"]["data"] = 999
        assert self.agent.verify_chain() is False

    def test_export_includes_integrity_metadata(self):
        self.agent.log("run-1", "test", "action_1", {"data": 1})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            self.agent.export(path)
            export = json.loads(path.read_text())
            assert "events" in export
            assert "integrity" in export
            assert export["integrity"]["tamper_proof"] is True
            assert export["integrity"]["verified"] is True
            assert export["integrity"]["algorithm"] == "sha256"
        finally:
            path.unlink(missing_ok=True)

    def test_empty_chain_verifies(self):
        assert self.agent.verify_chain() is True


# ─── Checkpoint ───────────────────────────────────────────────────────────────

class TestCheckpoint:
    def setup_method(self):
        from backend.services.checkpoint import CheckpointManager
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = CheckpointManager(Path(self.tmp.name))

    def teardown_method(self):
        self.tmp.cleanup()

    def test_save_and_load(self):
        key = self.mgr.save("run-1", 0, "step_a", {"status": "running"}, ["step_a"])
        assert "run-1:step_a:0" == key
        loaded = self.mgr.load("run-1")
        assert loaded is not None
        assert loaded["step_name"] == "step_a"
        assert loaded["completed_steps"] == ["step_a"]

    def test_cleanup_removes_file(self):
        self.mgr.save("run-1", 0, "step_a", {}, [])
        assert self.mgr.cleanup("run-1") is True
        assert self.mgr.load("run-1") is None

    def test_list_active(self):
        self.mgr.save("run-1", 0, "step_a", {}, [])
        self.mgr.save("run-2", 0, "step_b", {}, [])
        active = self.mgr.list_active()
        assert len(active) == 2

    def test_load_nonexistent(self):
        assert self.mgr.load("nonexistent") is None


# ─── Enhanced Metrics ─────────────────────────────────────────────────────────

class TestEnhancedMetrics:
    def test_metrics_have_new_fields(self):
        from backend.services.workflow_engine import WorkflowEngine
        with tempfile.TemporaryDirectory() as tmp:
            sim_config = {
                "create_jira_access": {"failure_probability": 1.0, "failure_modes": ["JIRA_PROVISIONING_TIMEOUT"]},
                "create_email_account": {"failure_probability": 0.0},
                "create_slack_account": {"failure_probability": 0.0},
                "assign_buddy": {"failure_probability": 0.0},
                "schedule_orientation_meetings": {"failure_probability": 0.0},
                "send_welcome_email": {"failure_probability": 0.0},
            }
            engine = WorkflowEngine(data_dir=Path(tmp), simulation_config=sim_config)
            result = engine.run("employee_onboarding", {
                "employee_id": "E-T", "full_name": "T", "email": "t@c.com",
                "department": "Eng", "role": "SWE", "location": "R", "start_date": "2026-05-01",
            })
            metrics = result["run"]["metrics"]
            assert "success_rate" in metrics
            assert "failure_rate" in metrics
            assert "retry_rate" in metrics
            assert "mttr_seconds" in metrics
            assert "total_execution_time_secs" in metrics
            assert "step_execution_times" in metrics
            assert "checkpoint_count" in metrics
            assert metrics["checkpoint_count"] >= 1


# ─── Deterministic Demo ──────────────────────────────────────────────────────

class TestDeterministicDemo:
    def test_demo_scenarios_exist(self):
        from backend.utils.constants import DEMO_SCENARIOS
        assert "happy_path" in DEMO_SCENARIOS
        assert "jira_failure" in DEMO_SCENARIOS
        assert "multi_failure" in DEMO_SCENARIOS
        assert "full_demo" in DEMO_SCENARIOS

    def test_each_scenario_has_config(self):
        from backend.utils.constants import DEMO_SCENARIOS
        for name, scenario in DEMO_SCENARIOS.items():
            assert "config" in scenario, f"{name} missing config"
            assert "label" in scenario, f"{name} missing label"
            assert "seed" in scenario, f"{name} missing seed"


# ─── Evolution All-Step Tracking ──────────────────────────────────────────────

class TestEvolutionAllSteps:
    def test_evolution_returns_all_step_rates(self):
        from backend.agents.evolution_agent import EvolutionAgent
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            Path(f.name).write_text("{}")
            agent = EvolutionAgent(memory_path=Path(f.name))
        try:
            result = agent.evolve({
                "step_status": {
                    "create_jira_access": "failed",
                    "create_email_account": "success",
                    "create_slack_account": "success",
                },
                "run_status": "completed_with_escalation",
            })
            assert "all_step_failure_rates" in result
            assert "system_reliability" in result
            assert "recommended_step_order" in result
            assert len(result["all_step_failure_rates"]) >= 3
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_system_reliability_score(self):
        from backend.agents.evolution_agent import EvolutionAgent
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            Path(f.name).write_text("{}")
            agent = EvolutionAgent(memory_path=Path(f.name))
        try:
            result = agent.evolve({
                "step_status": {"create_email_account": "success"},
                "run_status": "completed",
            })
            assert 0.0 <= result["system_reliability"] <= 1.0
        finally:
            Path(f.name).unlink(missing_ok=True)


# ─── Notification Service ────────────────────────────────────────────────────

class TestNotificationService:
    def test_simulated_delivery(self):
        from backend.services.notification_service import NotificationService
        svc = NotificationService()
        receipt = svc.send_email("test@co.com", "Hello", "World")
        assert receipt["delivery"] == "simulated"
        assert "timestamp" in receipt

    def test_welcome_email(self):
        from backend.services.notification_service import NotificationService
        svc = NotificationService()
        receipt = svc.send_welcome_email("new@co.com", "New User", "Engineering")
        assert receipt["delivery"] == "simulated"
        assert "Welcome" in receipt["subject"]
        assert "<html" in receipt["html_preview"]

    def test_escalation_notice(self):
        from backend.services.notification_service import NotificationService
        svc = NotificationService()
        receipt = svc.send_escalation_notice(
            "ops@co.com", "create_jira_access", "Timeout", "run-123"
        )
        assert receipt["delivery"] == "simulated"
        assert "Escalation" in receipt["subject"]

    def test_delivery_log_accumulates(self):
        from backend.services.notification_service import NotificationService
        svc = NotificationService()
        svc.send_email("a@co.com", "S1", "B1")
        svc.send_email("b@co.com", "S2", "B2")
        assert len(svc.delivery_log) == 2

    def test_real_mode_without_smtp_falls_back(self):
        from backend.services.notification_service import NotificationService
        svc = NotificationService()
        receipt = svc.send_email("ops@co.com", "Alert", "Body", integration_mode="real")
        assert receipt["delivery"] == "fallback_simulated"


class TestSlackService:
    def test_simulation_mode_returns_receipt(self):
        from backend.services.slack_service import SlackService
        svc = SlackService()
        receipt = svc.send_message(
            channel=None,
            text="hello",
            metadata={"notification_type": "test", "run_id": "run-1"},
        )
        assert receipt["delivery"] == "simulated"
        assert receipt["provider"] == "slack"

    def test_real_mode_without_config_falls_back(self):
        from backend.services.slack_service import SlackService
        svc = SlackService()
        receipt = svc.send_message(
            channel=None,
            text="hello",
            metadata={"notification_type": "test", "run_id": "run-1"},
            integration_mode="real",
        )
        assert receipt["delivery"] == "fallback_simulated"


# ─── Integration: Audit Chain in Full Workflow ────────────────────────────────

class TestAuditChainIntegration:
    def test_full_workflow_produces_valid_chain(self):
        from backend.services.workflow_engine import WorkflowEngine
        with tempfile.TemporaryDirectory() as tmp:
            sim_config = {
                "create_jira_access": {"failure_probability": 1.0, "failure_modes": ["JIRA_PROVISIONING_TIMEOUT"]},
                "create_email_account": {"failure_probability": 0.0},
                "create_slack_account": {"failure_probability": 0.0},
                "assign_buddy": {"failure_probability": 0.0},
                "schedule_orientation_meetings": {"failure_probability": 0.0},
                "send_welcome_email": {"failure_probability": 0.0},
            }
            engine = WorkflowEngine(data_dir=Path(tmp), simulation_config=sim_config)
            result = engine.run("employee_onboarding", {
                "employee_id": "E-T", "full_name": "T", "email": "t@c.com",
                "department": "Eng", "role": "SWE", "location": "R", "start_date": "2026-05-01",
            })
            run_id = result["run"]["run_id"]
            audit_file = Path(tmp) / f"audit_{run_id}.json"
            assert audit_file.exists()
            export = json.loads(audit_file.read_text())
            assert "integrity" in export
            assert export["integrity"]["verified"] is True
            assert export["integrity"]["tamper_proof"] is True

    def test_checkpoint_cleaned_after_success(self):
        from backend.services.workflow_engine import WorkflowEngine
        with tempfile.TemporaryDirectory() as tmp:
            sim_config = {step: {"failure_probability": 0.0} for step in [
                "create_email_account", "create_slack_account", "create_jira_access",
                "assign_buddy", "schedule_orientation_meetings", "send_welcome_email",
            ]}
            engine = WorkflowEngine(data_dir=Path(tmp), simulation_config=sim_config)
            result = engine.run("employee_onboarding", {
                "employee_id": "E-T", "full_name": "T", "email": "t@c.com",
                "department": "Eng", "role": "SWE", "location": "R", "start_date": "2026-05-01",
            })
            # Checkpoint should be cleaned up after successful run
            cp_dir = Path(tmp) / "checkpoints"
            if cp_dir.exists():
                assert len(list(cp_dir.glob("checkpoint_*.json"))) == 0
