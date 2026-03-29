"""
Unit tests for all EvoFlow AI agents.

These tests run without an OpenAI API key — they validate that:
  1. All agents produce valid output schemas
  2. Deterministic fallback paths are correct
  3. The LLM audit records have the expected structure
"""
from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path

# Allow running from repo root: python -m pytest tests/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Ensure no LLM calls are made in tests (simulate missing key)
os.environ.setdefault("OPENAI_API_KEY", "")

import pytest
from backend.utils.models import StepResult, utc_now


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def jira_failure() -> StepResult:
    return StepResult(
        step_id="create_jira_access:1",
        step_name="create_jira_access",
        status="failed",
        message="Jira provisioning failed for test@company.com",
        attempts=1,
        error_code="JIRA_PROVISIONING_TIMEOUT",
        payload={"system": "jira", "failure_type": "transient_or_external", "attempt": 1},
        start_ts=utc_now(),
        end_ts=utc_now(),
    )


@pytest.fixture()
def success_result() -> StepResult:
    return StepResult(
        step_id="create_email_account:1",
        step_name="create_email_account",
        status="success",
        message="Email account created for Test User",
        attempts=1,
        payload={"system": "google-workspace"},
        start_ts=utc_now(),
        end_ts=utc_now(),
    )


@pytest.fixture()
def employee() -> dict:
    return {
        "employee_id": "E-TEST",
        "full_name": "Test User",
        "email": "test@company.com",
        "department": "Engineering",
        "role": "Software Engineer",
        "location": "Remote",
        "start_date": "2026-04-01",
    }


# ─── FailureDetectionAgent ────────────────────────────────────────────────────

class TestFailureDetectionAgent:
    def setup_method(self):
        from backend.agents.failure_detection_agent import FailureDetectionAgent
        self.agent = FailureDetectionAgent()

    def test_success_returns_no_failure(self, success_result):
        diagnosis, audit = self.agent.analyze(success_result)
        assert diagnosis["is_failure"] is False
        assert diagnosis["route"] == "continue"
        assert diagnosis["severity"] == "none"

    def test_jira_timeout_is_recoverable(self, jira_failure):
        diagnosis, audit = self.agent.analyze(jira_failure)
        assert diagnosis["is_failure"] is True
        assert diagnosis["recoverable"] is True
        assert diagnosis["route"] == "recover"
        assert "confidence" in diagnosis
        assert 0.0 <= diagnosis["confidence"] <= 1.0

    def test_unknown_error_escalates(self):
        from backend.agents.failure_detection_agent import FailureDetectionAgent
        sr = StepResult(
            step_id="x:1", step_name="create_email_account",
            status="failed", message="Permission denied", attempts=1,
            error_code="PERMISSION_DENIED",
            payload={}, start_ts=utc_now(), end_ts=utc_now(),
        )
        diagnosis, audit = FailureDetectionAgent().analyze(sr)
        assert diagnosis["is_failure"] is True
        assert diagnosis["recoverable"] is False
        assert diagnosis["route"] == "escalate"

    def test_audit_record_has_required_keys(self, jira_failure):
        _, audit = self.agent.analyze(jira_failure)
        for key in ("ai_generated", "prompt", "raw_response", "latency_ms"):
            assert key in audit, f"Missing audit key: {key}"

    def test_diagnosis_has_reasoning(self, jira_failure):
        diagnosis, _ = self.agent.analyze(jira_failure)
        assert "reasoning" in diagnosis
        assert len(diagnosis["reasoning"]) > 10


# ─── StrategyAgent ────────────────────────────────────────────────────────────

class TestStrategyAgent:
    def setup_method(self):
        from backend.agents.strategy_agent import StrategyAgent
        self.agent = StrategyAgent()

    def test_returns_valid_strategy_schema(self):
        strategy, audit = self.agent.generate_strategy(
            step_name="create_jira_access",
            failure_history={"success": 0, "failed": 5},
            current_policy={"max_retries": 2, "escalation_target": "ops@co.com"},
            failure_analysis={
                "is_failure": True,
                "recoverable": True,
                "reason": "timeout",
                "severity": "high",
                "confidence": 0.8,
                "recommended_action": "retry",
                "reasoning": "Transient timeout error",
            },
        )
        for key in ("strategy_name", "actions", "retry_policy", "prechecks", "fallbacks", "justification", "confidence"):
            assert key in strategy, f"Missing strategy key: {key}"

    def test_max_retries_clamped(self):
        strategy, _ = self.agent.generate_strategy(
            "create_jira_access",
            {"success": 0, "failed": 100},
            {"max_retries": 10},  # too high — should be clamped
            {"recoverable": True, "reason": "timeout"},
        )
        assert strategy["retry_policy"]["max_retries"] <= 4

    def test_backoff_matches_retries(self):
        strategy, _ = self.agent.generate_strategy(
            "create_jira_access",
            {"success": 0, "failed": 3},
            {"max_retries": 3},
            {"recoverable": True},
        )
        rp = strategy["retry_policy"]
        assert len(rp["backoff"]) == rp["max_retries"]


# ─── EvolutionAgent ────────────────────────────────────────────────────────────

class TestEvolutionAgent:
    def setup_method(self):
        from backend.agents.evolution_agent import EvolutionAgent
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        # Start with empty file (agent uses default)
        Path(self.tmp.name).write_text("{}")
        self.agent = EvolutionAgent(memory_path=Path(self.tmp.name))

    def teardown_method(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_evolve_increments_runs(self):
        self.agent.evolve({
            "step_status": {"create_jira_access": "failed"},
            "run_status": "completed_with_escalation",
        })
        assert self.agent.memory["total_runs"] == 1

    def test_high_failure_rate_increases_retries(self):
        for _ in range(3):
            self.agent.evolve({
                "step_status": {"create_jira_access": "failed"},
                "run_status": "completed_with_escalation",
            })
        jira = self.agent.memory["strategy"]["jira"]
        # With 100% failure rate, retries should have increased
        assert jira["max_retries"] >= 2

    def test_evolution_result_has_reasoning(self):
        result = self.agent.evolve({
            "step_status": {"create_jira_access": "failed"},
            "run_status": "completed_with_escalation",
        })
        assert "reasoning" in result
        assert len(result["reasoning"]) > 5

    def test_strategy_history_persisted(self):
        self.agent.evolve({
            "step_status": {"create_jira_access": "failed"},
            "run_status": "completed_with_escalation",
        })
        assert len(self.agent.memory["strategy_history"]) == 1


# ─── RecoveryAgent ────────────────────────────────────────────────────────────

class TestRecoveryAgent:
    def setup_method(self):
        from backend.agents.recovery_agent import RecoveryAgent
        self.agent = RecoveryAgent()

    def _always_fail_fn(self, step_name, employee, attempt):
        return StepResult(
            step_id=f"{step_name}:{attempt}",
            step_name=step_name,
            status="failed",
            message="still failing",
            attempts=attempt,
            error_code="JIRA_PROVISIONING_TIMEOUT",
            payload={},
            start_ts=utc_now(),
            end_ts=utc_now(),
        )

    def _always_succeed_fn(self, step_name, employee, attempt):
        return StepResult(
            step_id=f"{step_name}:{attempt}",
            step_name=step_name,
            status="success",
            message="success",
            attempts=attempt,
            payload={},
            start_ts=utc_now(),
            end_ts=utc_now(),
        )

    def test_escalation_when_all_retries_fail(self, employee):
        policy = {"max_retries": 2, "retry_backoff_seconds": [0, 0], "escalation_target": "ops@co.com"}
        result = self.agent.recover(
            "create_jira_access", employee, policy, self._always_fail_fn
        )
        assert result["recovered"] is False
        assert result["recovery_mode"] == "escalation"
        assert result["escalation"] is not None
        assert len(result["retry_results"]) == 2

    def test_recovery_when_retry_succeeds(self, employee):
        calls = {"count": 0}
        def succeed_on_second(step, emp, attempt):
            calls["count"] += 1
            if calls["count"] >= 2:
                return self._always_succeed_fn(step, emp, attempt)
            return self._always_fail_fn(step, emp, attempt)

        policy = {"max_retries": 3, "retry_backoff_seconds": [0, 0, 0]}
        result = self.agent.recover(
            "create_jira_access", employee, policy, succeed_on_second
        )
        assert result["recovered"] is True
        assert result["recovery_mode"] == "retry"

    def test_strategy_name_included_in_result(self, employee):
        from backend.agents.strategy_agent import StrategyAgent
        strategy = StrategyAgent()._default_strategy(
            "create_jira_access", {"max_retries": 1}, {}
        )
        policy = {"max_retries": 1, "retry_backoff_seconds": [0]}
        result = self.agent.recover(
            "create_jira_access", employee, policy,
            self._always_fail_fn, strategy=strategy
        )
        assert result["strategy_name"] == strategy["strategy_name"]

    def test_escalation_includes_fallbacks(self, employee):
        strategy = {
            "strategy_name": "test",
            "retry_policy": {"max_retries": 1, "backoff": [0]},
            "fallbacks": ["create_ticket", "notify_team"],
            "escalation_target": "ops@co.com",
            "justification": "test",
            "confidence": 0.8,
        }
        policy = {"max_retries": 1, "retry_backoff_seconds": [0]}
        result = self.agent.recover(
            "create_jira_access", employee, policy,
            self._always_fail_fn, strategy=strategy
        )
        assert result["escalation"]["fallback_options"] == ["create_ticket", "notify_team"]


# ─── LLM Service ─────────────────────────────────────────────────────────────

class TestLlmService:
    def _reset_svc(self, svc):
        svc._client = None
        svc._model_fast = None
        svc._model_smart = None

    def test_returns_fallback_when_no_key(self):
        import backend.services.llm_service as svc
        self._reset_svc(svc)
        original = os.environ.get("OPENAI_API_KEY", "")
        os.environ["OPENAI_API_KEY"] = ""

        try:
            schema = {
                "properties": {
                    "result": {"type": "string"},
                    "score":  {"type": "number"},
                }
            }
            response, audit = svc.generate_response("test prompt", schema)
            assert audit["ai_generated"] is False
            assert "result" in response
            assert "score" in response
        finally:
            os.environ["OPENAI_API_KEY"] = original
            self._reset_svc(svc)

    def test_is_ai_available_false_when_no_key(self):
        import backend.services.llm_service as svc
        self._reset_svc(svc)
        original = os.environ.get("OPENAI_API_KEY", "")
        os.environ["OPENAI_API_KEY"] = ""
        try:
            assert svc.is_ai_available() is False
        finally:
            os.environ["OPENAI_API_KEY"] = original
            self._reset_svc(svc)
