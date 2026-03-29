"""
Workflow Engine — Central orchestrator for EvoFlow AI.

Routes to three workflow types:
  1. employee_onboarding  — System integration steps + recovery + evolution
  2. meeting_action       — LLM-native meeting transcript processing with HITL
  3. sla_breach           — SLA breach detection, bottleneck resolution, rerouting

All workflows share:
  - Common step execution loop with failure detection + recovery
  - Human-in-the-loop (HITL) pause for ambiguous situations
  - Audit logging with full LLM traces
  - SSE event streaming
  - Impact quantification
  - Strategy evolution
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.agents.audit_agent import AuditAgent
from backend.agents.evolution_agent import EvolutionAgent
from backend.agents.execution_agents import ExecutionAgents
from backend.agents.failure_detection_agent import FailureDetectionAgent
from backend.agents.hitl_agent import HITLAgent
from backend.agents.orchestrator_agent import OrchestratorAgent
from backend.agents.recovery_agent import RecoveryAgent
from backend.agents.strategy_agent import StrategyAgent
from backend.services.checkpoint_store import CheckpointStore
from backend.utils.constants import (
    DEFAULT_RECOVERY_POLICY,
    IMPACT_MODEL,
    WORKFLOW_TYPES,
)
from backend.utils.models import StepResult, WorkflowState


class WorkflowEngine:
    def __init__(
        self,
        data_dir: Path,
        simulation_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.data_dir = data_dir
        self.simulation_config = simulation_config  # per-step overrides from UI
        self.orchestrator     = OrchestratorAgent()
        self.executor         = ExecutionAgents()
        self.failure_detector = FailureDetectionAgent()
        self.strategy_agent   = StrategyAgent()
        self.recovery_agent   = RecoveryAgent()
        self.hitl_agent       = HITLAgent()
        self.audit_agent      = AuditAgent()
        self.evolution_agent  = EvolutionAgent(
            memory_path=data_dir / "learning_state.json"
        )
        self.checkpoint_store = CheckpointStore(data_dir)

    # ── Public entry point ───────────────────────────────────────────────────

    def run(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Run any supported workflow type.

        workflow_type: "employee_onboarding" | "meeting_action" | "sla_breach"
        input_data:   workflow-specific payload (employee dict, transcript, approval)
        """
        if workflow_type not in WORKFLOW_TYPES:
            raise ValueError(f"Unknown workflow type: {workflow_type}")

        return self._run_workflow(workflow_type, input_data, event_callback)

    def run_onboarding(
        self,
        employee: Dict[str, Any],
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible wrapper for onboarding."""
        return self.run("employee_onboarding", employee, event_callback)

    # ── Core workflow runner ──────────────────────────────────────────────────

    def _run_workflow(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        event_callback: Optional[Callable],
    ) -> Dict[str, Any]:
        def emit(event_type: str, data: Dict[str, Any]) -> None:
            if event_callback:
                event_callback(event_type, data)

        state = WorkflowState(workflow_type=workflow_type, input_data=input_data)
        evolved_strategy = self.evolution_agent.current_strategy()

        # Initialise (or reload) checkpoint for this run
        self.checkpoint_store.init(state.run_id, workflow_type, input_data)

        # ── Plan creation ─────────────────────────────────────────────────────
        plan, plan_audit = self.orchestrator.create_plan_with_audit(
            input_data, evolved_strategy, workflow_type
        )
        state.plan = plan

        self.audit_agent.log(
            state.run_id, self.orchestrator.name, "plan_created",
            {"plan": state.plan, "input_data": input_data, "workflow_type": workflow_type},
            llm_audit=plan_audit,
        )
        emit("plan_created", {
            "run_id":         state.run_id,
            "workflow_type":  workflow_type,
            "plan":           state.plan,
            "input_data":     input_data,
            "ai_generated":   plan_audit.get("ai_generated", False),
        })

        if plan_audit.get("ai_generated"):
            emit("ai_reasoning", {
                "agent":        "orchestrator_agent",
                "step_name":    None,
                "reasoning":    f"Orchestrator built AI-enriched plan for {workflow_type} with criticality assessments per step.",
                "confidence":   0.85,
                "decision":     "plan_created",
                "ai_generated": True,
            })

        # ── Step execution loop ───────────────────────────────────────────────
        failure_analyses: Dict[str, Any] = {}

        for step in state.plan:
            step_name = step["step_name"]

            # ── Checkpoint resume: skip already-completed steps ───────────────
            if self.checkpoint_store.is_done(state.run_id, step_name):
                cached = self.checkpoint_store.get_result(state.run_id, step_name)
                if cached:
                    state.results.append(cached)
                    self._accumulate_context(workflow_type, step_name, cached, state)
                emit("step_started",  {"step_name": step_name, "attempt": 1, "resumed": True})
                emit("step_success",  {"step_name": step_name, "status": "success", "resumed": True})
                continue

            emit("step_started", {"step_name": step_name, "attempt": 1})

            # Build step-specific context from accumulated state
            step_context = self._build_step_context(workflow_type, step_name, state)

            # Execute
            step_result = self._execute_step(step_name, input_data, step_context, attempt=1)
            state.results.append(step_result)
            self.audit_agent.log(
                state.run_id, self.executor.name, "step_executed", step_result.to_dict()
            )
            emit("step_executed", step_result.to_dict())

            # Checkpoint successful steps immediately
            if step_result.status == "success":
                self.checkpoint_store.save_step(state.run_id, step_name, step_result, attempt=1)
                self._accumulate_context(workflow_type, step_name, step_result, state)

            # Failure detection
            context = {
                "workflow_type": workflow_type,
                "department":    input_data.get("department"),
                "role":          input_data.get("role"),
                "step_plan":     step,
                "prior_results": [r.to_dict() for r in state.results[:-1]],
            }
            diagnosis, failure_audit = self.failure_detector.analyze(step_result, context)
            self.audit_agent.log(
                state.run_id, self.failure_detector.name, "failure_analysis",
                diagnosis, llm_audit=failure_audit,
            )

            if diagnosis.get("is_failure") and diagnosis.get("reasoning"):
                emit("ai_reasoning", {
                    "agent":        "failure_detection_agent",
                    "step_name":    step_name,
                    "reasoning":    diagnosis["reasoning"],
                    "confidence":   diagnosis.get("confidence", 0.7),
                    "decision":     diagnosis.get("recommended_action", "escalate"),
                    "severity":     diagnosis.get("severity", "high"),
                    "ai_generated": failure_audit.get("ai_generated", False),
                })
                failure_analyses[step_name] = diagnosis

            # Happy path
            if not diagnosis["is_failure"]:
                emit("step_success", {"step_name": step_name, "status": "success"})
                continue

            emit("step_failed", {
                "step_name":  step_name,
                "error_code": step_result.error_code,
                "diagnosis":  diagnosis,
            })

            # ── HITL: clarification needed ────────────────────────────────────
            if diagnosis.get("recommended_action") == "clarify":
                clarification = self._handle_hitl(
                    state, step_name, step_result, diagnosis, emit
                )
                if clarification:
                    state.clarifications.append(clarification)
                    # Re-execute the step with the clarification answer
                    step_context["clarification_answer"] = clarification.get("answer")
                    retry_result = self._execute_step(
                        step_name, input_data, step_context, attempt=2
                    )
                    state.results.append(retry_result)
                    emit("step_executed", retry_result.to_dict())
                    if retry_result.status == "success":
                        self._accumulate_context(workflow_type, step_name, retry_result, state)
                        emit("step_success", {"step_name": step_name, "status": "success"})
                        continue
                    # If still failed after clarification, fall through to escalation
                    step_result = retry_result

            # ── Non-recoverable — escalate directly ───────────────────────────
            if not diagnosis.get("recoverable", False):
                escalation = self._create_escalation(
                    step_name, step_result, diagnosis, failure_audit
                )
                state.escalations.append(escalation)
                self.audit_agent.log(
                    state.run_id, self.recovery_agent.name, "escalation_created", escalation
                )
                emit("escalation_created", escalation)
                continue

            # ── Generate adaptive strategy ────────────────────────────────────
            step_history = (
                self.evolution_agent.memory
                .get("step_stats", {})
                .get(step_name, {"success": 0, "failed": 0})
            )
            base_policy = dict(DEFAULT_RECOVERY_POLICY.get(step_name, {"max_retries": 2}))
            if step_name == "create_jira_access":
                base_policy["max_retries"] = evolved_strategy.get("jira", {}).get(
                    "max_retries", base_policy.get("max_retries", 2)
                )

            generated_strategy, strategy_audit = self.strategy_agent.generate_strategy(
                step_name, step_history, base_policy, diagnosis
            )
            self.audit_agent.log(
                state.run_id, self.strategy_agent.name, "strategy_generated",
                generated_strategy, llm_audit=strategy_audit,
            )
            emit("strategy_generated", {
                "step_name":     step_name,
                "strategy_name": generated_strategy.get("strategy_name"),
                "justification": generated_strategy.get("justification"),
                "retry_policy":  generated_strategy.get("retry_policy"),
                "prechecks":     generated_strategy.get("prechecks", []),
                "fallbacks":     generated_strategy.get("fallbacks", []),
                "confidence":    generated_strategy.get("confidence"),
                "ai_generated":  strategy_audit.get("ai_generated", False),
            })

            # ── Recovery loop ─────────────────────────────────────────────────
            def _execute_with_event(
                name: str, emp: Dict[str, Any], attempt: int
            ) -> StepResult:
                emit("step_retry", {"step_name": name, "attempt": attempt})
                result = self._execute_step(name, emp, step_context, attempt)
                emit("step_executed", result.to_dict())
                return result

            # Inject run_id so recovery agent can reference it in escalation alerts
            input_data_with_run_id = {**input_data, "_run_id": state.run_id}
            recovery = self.recovery_agent.recover(
                step_name,
                input_data_with_run_id,
                base_policy,
                execute_fn=_execute_with_event,
                strategy=generated_strategy,
                failure_analysis=diagnosis,
            )

            self.audit_agent.log(
                state.run_id, self.recovery_agent.name, "recovery_attempted", recovery
            )
            emit("recovery_attempted", {
                "step_name":     step_name,
                "recovered":     recovery["recovered"],
                "recovery_mode": recovery["recovery_mode"],
                "retry_count":   len(recovery.get("retry_results", [])),
                "strategy_name": recovery.get("strategy_name"),
                "reasoning":     recovery.get("reasoning", ""),
            })

            if recovery.get("reasoning"):
                emit("ai_reasoning", {
                    "agent":        "recovery_agent",
                    "step_name":    step_name,
                    "reasoning":    recovery["reasoning"],
                    "confidence":   generated_strategy.get("confidence", 0.7),
                    "decision":     "recovered" if recovery["recovered"] else "escalated",
                    "ai_generated": strategy_audit.get("ai_generated", False),
                })

            state.results.extend(recovery.get("retry_results", []))

            if recovery.get("escalation"):
                esc = recovery["escalation"]
                state.escalations.append(esc)
                self.audit_agent.log(
                    state.run_id, self.recovery_agent.name, "escalation_created", esc
                )
                emit("escalation_created", esc)

            # Checkpoint if recovery succeeded
            if recovery.get("recovered"):
                successful_retries = [
                    r for r in recovery.get("retry_results", [])
                    if r.status == "success"
                ]
                if successful_retries:
                    self.checkpoint_store.save_step(
                        state.run_id, step_name, successful_retries[-1],
                        attempt=successful_retries[-1].attempts,
                    )

        # ── Finalise ──────────────────────────────────────────────────────────
        state.finished_at = datetime.now(timezone.utc).isoformat()
        state.status = (
            "completed_with_escalation" if state.escalations else "completed"
        )
        state.metrics = self._compute_metrics(state)
        state.impact   = self._compute_impact(workflow_type, state)

        self.audit_agent.log(
            state.run_id, "workflow_engine", "run_completed",
            {"metrics": state.metrics, "impact": state.impact},
        )
        emit("run_completed", {
            "status":  state.status,
            "metrics": state.metrics,
            "impact":  state.impact,
        })

        # ── Evolution ─────────────────────────────────────────────────────────
        evolution_summary = self.evolution_agent.evolve({
            "step_status":      state.metrics["latest_step_status"],
            "run_status":       state.status,
            "failure_analyses": failure_analyses,
        })
        self.audit_agent.log(
            state.run_id, self.evolution_agent.name, "strategy_evolved", evolution_summary
        )
        emit("strategy_evolved", evolution_summary)

        if evolution_summary.get("reasoning"):
            emit("ai_reasoning", {
                "agent":        "evolution_agent",
                "step_name":    None,
                "reasoning":    evolution_summary["reasoning"],
                "confidence":   evolution_summary.get("confidence", 0.6),
                "decision":     "strategy_evolved",
                "ai_generated": evolution_summary.get("ai_generated", False),
            })

        # ── Audit export ──────────────────────────────────────────────────────
        self.audit_agent.export(self.data_dir / f"audit_{state.run_id}.json")
        emit("audit_exported", {"audit_file": f"audit_{state.run_id}.json"})

        # Clean up checkpoint on successful completion
        if state.status in ("completed", "completed_with_escalation"):
            self.checkpoint_store.cleanup(state.run_id)

        return {
            "run":       state.to_dict(),
            "evolution": evolution_summary,
        }

    # ── HITL ─────────────────────────────────────────────────────────────────

    def _handle_hitl(
        self,
        state: WorkflowState,
        step_name: str,
        step_result: StepResult,
        diagnosis: Dict[str, Any],
        emit: Callable,
    ) -> Optional[Dict[str, Any]]:
        """Pause workflow, ask human for clarification, return their answer."""
        question = diagnosis.get("clarification_question") or (
            f"Action item owner is ambiguous for step '{step_name}'. "
            f"Error: {step_result.error_code}. Who should own this task?"
        )
        options = diagnosis.get("clarification_options", [])

        self.hitl_agent.request_clarification(
            state.run_id, question, {"step_name": step_name, "error": step_result.error_code},
            options
        )
        emit("clarification_needed", {
            "run_id":   state.run_id,
            "step_name": step_name,
            "question": question,
            "options":  options,
            "timeout_seconds": 300,
        })

        answer = self.hitl_agent.wait_for_answer(state.run_id, timeout=300.0)
        self.hitl_agent.cleanup(state.run_id)

        if answer is None:
            # Timed out — escalate
            emit("clarification_timeout", {
                "run_id":    state.run_id,
                "step_name": step_name,
                "message":   "No response within 5 minutes — escalating.",
            })
            return None

        emit("clarification_received", {
            "run_id":    state.run_id,
            "step_name": step_name,
            "answer":    answer,
        })
        return {"step_name": step_name, "question": question, "answer": answer}

    # ── Context accumulation ──────────────────────────────────────────────────

    def _build_step_context(
        self, workflow_type: str, step_name: str, state: WorkflowState
    ) -> Dict[str, Any]:
        """Build context dict for a step from accumulated prior results."""
        ctx: Dict[str, Any] = {}
        for result in state.results:
            if result.status == "success" and result.payload:
                # Pull relevant outputs forward into context
                if result.step_name == "extract_action_items":
                    ctx["action_items"] = result.payload.get("action_items", [])
                elif result.step_name == "assign_owners":
                    ctx["action_items"] = result.payload.get("resolved_items", [])
                elif result.step_name == "find_delegate":
                    ctx["delegate"] = {
                        "delegate_name":  result.payload.get("delegate_name"),
                        "delegate_email": result.payload.get("delegate_email"),
                        "delegate_role":  result.payload.get("delegate_role"),
                    }
                elif result.step_name == "reroute_approval":
                    ctx["override"] = {
                        "override_id": result.payload.get("override_id"),
                        "rerouted_to": result.payload.get("rerouted_to"),
                        "rerouted_at": result.payload.get("rerouted_at"),
                    }
        return ctx

    def _accumulate_context(
        self, workflow_type: str, step_name: str, result: StepResult, state: WorkflowState
    ) -> None:
        """Store step outputs in state.context for downstream steps."""
        if result.payload:
            state.context[step_name] = result.payload

    # ── Step execution ────────────────────────────────────────────────────────

    def _execute_step(
        self,
        step_name: str,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        attempt: int,
    ) -> StepResult:
        return self.executor.execute_step(
            step_name=step_name,
            input_data=input_data,
            context=context,
            simulation_config=self.simulation_config,
            attempt=attempt,
        )

    # ── Impact quantification ─────────────────────────────────────────────────

    @staticmethod
    def _compute_impact(workflow_type: str, state: WorkflowState) -> Dict[str, Any]:
        model = IMPACT_MODEL.get(workflow_type, {})
        if not model:
            return {}

        if workflow_type == "employee_onboarding":
            manual_h = model["manual_hours_per_run"]
            agent_h  = model["agent_hours_per_run"]
            rate     = model["hourly_cost_usd"]
            per_month = model["onboardings_per_month"]
            error_saves = (
                model["error_rate_manual"]
                * model["error_remediation_hours"]
                * rate
            )
            time_saved_h = manual_h - agent_h
            cost_saved_per_run = time_saved_h * rate + error_saves
            return {
                "time_saved_hours_per_run":   round(time_saved_h, 2),
                "cost_saved_per_run_usd":     round(cost_saved_per_run, 2),
                "monthly_cost_savings_usd":   round(cost_saved_per_run * per_month, 0),
                "steps_automated":            len(state.plan),
                "human_interventions":        len(state.escalations),
                "time_to_productive_improvement_days": (
                    model["time_to_productive_days_manual"]
                    - model["time_to_productive_days_agent"]
                ),
                "automation_rate_pct": round(
                    (1 - len(state.escalations) / max(len(state.plan), 1)) * 100, 1
                ),
            }

        elif workflow_type == "meeting_action":
            manual_h = model["manual_hours_per_meeting"]
            agent_h  = model["agent_hours_per_meeting"]
            rate     = model["hourly_cost_usd"]
            meetings = model["meetings_per_month"]
            missed_rate = model["follow_up_miss_rate_manual"]
            revenue = model["revenue_per_deal_usd"]
            deals   = model["deals_affected_per_month"]
            action_items = 0
            for r in state.results:
                if r.step_name == "extract_action_items" and r.status == "success":
                    action_items = r.payload.get("total_count", 0)
            return {
                "time_saved_hours_per_meeting": round(manual_h - agent_h, 2),
                "monthly_time_savings_hours":   round((manual_h - agent_h) * meetings, 1),
                "monthly_cost_savings_usd":     round((manual_h - agent_h) * rate * meetings, 0),
                "action_items_captured":        action_items,
                "follow_up_miss_prevention_pct": round(missed_rate * 100, 0),
                "monthly_revenue_at_risk_protected_usd": round(missed_rate * revenue * deals, 0),
                "steps_automated": len(state.plan),
            }

        elif workflow_type == "sla_breach":
            penalty = model["avg_sla_penalty_usd"]
            prevented = model["breaches_prevented_per_month"]
            manual_h = model["manual_hours_per_breach"]
            agent_h  = model["agent_hours_per_breach"]
            rate     = model["hourly_cost_usd"]
            return {
                "penalties_avoided_per_month_usd": round(penalty * prevented, 0),
                "time_saved_per_breach_hours":     round(manual_h - agent_h, 2),
                "monthly_firefighting_hours_saved": round((manual_h - agent_h) * prevented, 1),
                "monthly_labor_savings_usd":       round((manual_h - agent_h) * rate * prevented, 0),
                "total_monthly_value_usd":         round(
                    penalty * prevented + (manual_h - agent_h) * rate * prevented, 0
                ),
                "steps_automated": len(state.plan),
                "escalations":     len(state.escalations),
            }
        return {}

    # ── Metrics ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_metrics(state: WorkflowState) -> Dict[str, Any]:
        latest_status: Dict[str, str] = {}
        for result in state.results:
            latest_status[result.step_name] = result.status
        return {
            "total_step_events":  len(state.results),
            "distinct_steps":     len(state.plan),
            "failed_events":      sum(1 for r in state.results if r.status == "failed"),
            "escalation_count":   len(state.escalations),
            "latest_step_status": latest_status,
        }

    # ── Escalation helper ─────────────────────────────────────────────────────

    @staticmethod
    def _create_escalation(
        step_name: str,
        step_result: StepResult,
        diagnosis: Dict[str, Any],
        failure_audit: Dict[str, Any],
    ) -> Dict[str, Any]:
        policy = DEFAULT_RECOVERY_POLICY.get(step_name, {})
        return {
            "type":               "manual_intervention",
            "target":             policy.get("escalation_target", "ops@company.com"),
            "reason":             (
                f"{step_name} failed with non-recoverable error: "
                f"{step_result.error_code}. {diagnosis.get('reasoning', '')}"
            ),
            "severity":           diagnosis.get("severity", "high"),
            "status":             "open",
            "recommended_action": diagnosis.get("recommended_action", "escalate"),
            "ai_reasoning":       diagnosis.get("reasoning", ""),
            "ai_generated":       failure_audit.get("ai_generated", False),
        }
