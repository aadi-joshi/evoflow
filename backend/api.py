from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agents.hitl_agent import provide_answer
from backend.services.workflow_engine import WorkflowEngine
from backend.utils.env import load_env

DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

load_env()

app = FastAPI(title="EvoFlow AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ────────────────────────────────────────────────────────────

class OnboardingPayload(BaseModel):
    workflow_type: str = "employee_onboarding"
    employee_id:   str
    full_name:     str
    email:         str
    department:    str
    role:          str
    location:      str
    start_date:    str
    simulation_config: Optional[Dict[str, Any]] = None
    integration_mode: str = "simulation"


class MeetingActionPayload(BaseModel):
    workflow_type: str = "meeting_action"
    transcript:    str
    participants:  list = []
    meeting_title: str = "Meeting"
    simulation_config: Optional[Dict[str, Any]] = None
    integration_mode: str = "simulation"


class SLABreachPayload(BaseModel):
    workflow_type: str = "sla_breach"
    approval:      Dict[str, Any]
    org_chart:     Dict[str, Any] = {}
    simulation_config: Optional[Dict[str, Any]] = None
    integration_mode: str = "simulation"


class GenericWorkflowPayload(BaseModel):
    workflow_type:     str
    input_data:        Dict[str, Any]
    simulation_config: Optional[Dict[str, Any]] = None
    integration_mode: str = "simulation"


class ClarifyPayload(BaseModel):
    answer: str


# ── SSE streaming helper ──────────────────────────────────────────────────────

def _run_engine_stream(
    workflow_type: str,
    input_data: Dict[str, Any],
    simulation_config: Optional[Dict[str, Any]],
    integration_mode: str = "simulation",
) -> StreamingResponse:
    loop = asyncio.get_running_loop()
    sync_queue: asyncio.Queue = asyncio.Queue(maxsize=1)

    def callback(event_type: str, data: Dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            sync_queue.put({"type": event_type, "data": data}),
            loop,
        )
        future.result(timeout=60)

    def worker() -> None:
        engine = WorkflowEngine(
            data_dir=DATA_DIR,
            simulation_config=simulation_config,
            integration_mode=integration_mode,
        )
        try:
            result = engine.run(workflow_type, input_data, event_callback=callback)
            asyncio.run_coroutine_threadsafe(
                sync_queue.put({"type": "done", "data": result}), loop
            ).result(timeout=60)
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(
                sync_queue.put({"type": "error", "data": {"message": str(exc)}}), loop
            ).result(timeout=60)

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                event = await asyncio.wait_for(sync_queue.get(), timeout=60.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                yield 'data: {"type": "heartbeat"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        },
    )


# ── Workflow endpoints ────────────────────────────────────────────────────────

@app.post("/api/run")
async def run_onboarding(payload: OnboardingPayload) -> StreamingResponse:
    """Run employee onboarding workflow (backward compatible)."""
    input_data = {
        "employee_id": payload.employee_id,
        "full_name":   payload.full_name,
        "email":       payload.email,
        "department":  payload.department,
        "role":        payload.role,
        "location":    payload.location,
        "start_date":  payload.start_date,
    }
    return _run_engine_stream(
        "employee_onboarding",
        input_data,
        payload.simulation_config,
        payload.integration_mode,
    )


@app.post("/api/run/meeting")
async def run_meeting(payload: MeetingActionPayload) -> StreamingResponse:
    """Run meeting-to-action workflow."""
    input_data = {
        "transcript":    payload.transcript,
        "participants":  payload.participants,
        "meeting_title": payload.meeting_title,
    }
    return _run_engine_stream(
        "meeting_action",
        input_data,
        payload.simulation_config,
        payload.integration_mode,
    )


@app.post("/api/run/sla")
async def run_sla(payload: SLABreachPayload) -> StreamingResponse:
    """Run SLA breach prevention workflow."""
    input_data = {
        "approval":  payload.approval,
        "org_chart": payload.org_chart,
    }
    return _run_engine_stream(
        "sla_breach",
        input_data,
        payload.simulation_config,
        payload.integration_mode,
    )


@app.post("/api/run/workflow")
async def run_workflow(payload: GenericWorkflowPayload) -> StreamingResponse:
    """Generic workflow runner — accepts any workflow_type."""
    return _run_engine_stream(
        payload.workflow_type,
        payload.input_data,
        payload.simulation_config,
        payload.integration_mode,
    )


# ── HITL endpoint ─────────────────────────────────────────────────────────────

@app.post("/api/clarify/{run_id}")
async def submit_clarification(run_id: str, payload: ClarifyPayload) -> Dict[str, Any]:
    """Submit a human clarification answer, unblocking the paused workflow."""
    success = provide_answer(run_id, payload.answer)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"No pending clarification for run_id={run_id}"
        )
    return {"ok": True, "run_id": run_id, "answer": payload.answer}


# ── Query endpoints ───────────────────────────────────────────────────────────

@app.get("/api/history")
def get_history() -> Dict[str, Any]:
    audit_files = sorted(
        DATA_DIR.glob("audit_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    runs = []
    for f in audit_files[:20]:
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            # Support both old (list) and new (dict with events key) format
            if isinstance(raw, dict):
                events = raw.get("events", [])
                integrity = raw.get("integrity", {})
            else:
                events = raw
                integrity = {}
            run_event     = next((e for e in events if e.get("action") == "run_completed"),    None)
            evolved_event = next((e for e in events if e.get("action") == "strategy_evolved"), None)
            plan_event    = next((e for e in events if e.get("action") == "plan_created"),     None)
            ai_events     = [e for e in events if e.get("llm_trace", {}).get("ai_generated")]
            run_payload   = run_event["payload"] if run_event else {}
            runs.append({
                "run_id":        events[0]["run_id"] if events else f.stem.replace("audit_", ""),
                "timestamp":     events[0]["timestamp"] if events else "",
                "workflow_type": plan_event["payload"].get("workflow_type", "employee_onboarding") if plan_event else "employee_onboarding",
                "metrics":       run_payload.get("metrics", run_payload),
                "impact":        run_payload.get("impact", {}),
                "evolution":     evolved_event["payload"] if evolved_event else {},
                "input_data":    plan_event["payload"].get("input_data", plan_event["payload"].get("employee", {})) if plan_event else {},
                "audit_file":    f.name,
                "ai_decisions":  len(ai_events),
                "integrity":     integrity,
            })
        except Exception:
            continue
    return {"runs": runs}


@app.get("/api/learning")
def get_learning() -> Dict[str, Any]:
    from backend.utils.helpers import read_json
    memory_path = DATA_DIR / "learning_state.json"
    return read_json(memory_path, {"total_runs": 0, "step_stats": {}, "strategy": {}})


@app.get("/api/audit/{run_id}")
def get_audit(run_id: str) -> Any:
    audit_file = DATA_DIR / f"audit_{run_id}.json"
    if not audit_file.exists():
        return {"error": "not found"}
    raw = json.loads(audit_file.read_text(encoding="utf-8"))
    # Support both old (list) and new (dict with events + integrity) format
    if isinstance(raw, list):
        return {"events": raw, "integrity": {}}
    return raw


@app.get("/api/strategy-history")
def get_strategy_history() -> Dict[str, Any]:
    from backend.utils.helpers import read_json
    memory_path = DATA_DIR / "learning_state.json"
    memory = read_json(memory_path, {})
    return {
        "strategy_history":  memory.get("strategy_history", []),
        "reasoning_history": memory.get("reasoning_history", []),
        "total_runs":        memory.get("total_runs", 0),
    }


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    from backend.services.llm_service import is_ai_available
    from backend.services.notification_service import NotificationService
    from backend.services.slack_service import SlackService
    from backend.utils.constants import DEMO_SCENARIOS
    slack = SlackService()
    email = NotificationService()
    return {
        "status":       "ok",
        "ai_available": is_ai_available(),
        "workflows":    ["employee_onboarding", "meeting_action", "sla_breach"],
        "demo_scenarios": {k: v["label"] for k, v in DEMO_SCENARIOS.items()},
        "integrations": {
            "slack_configured": slack.is_configured(),
            "email_configured": email.is_configured(),
            "default_mode": "simulation",
        },
    }


@app.post("/api/reset")
def reset_state() -> Dict[str, Any]:
    learning_path = DATA_DIR / "learning_state.json"
    deleted = []
    if learning_path.exists():
        learning_path.unlink()
        deleted.append("learning_state.json")
    for audit_file in DATA_DIR.glob("audit_*.json"):
        audit_file.unlink()
        deleted.append(audit_file.name)
    # Also clean up checkpoints
    cp_dir = DATA_DIR / "checkpoints"
    if cp_dir.exists():
        for cp_file in cp_dir.glob("checkpoint_*.json"):
            cp_file.unlink()
            deleted.append(cp_file.name)
    return {"reset": True, "deleted": deleted}


# ── Benchmark endpoint ────────────────────────────────────────────────────────

class BenchmarkPayload(BaseModel):
    num_runs: int = 5


@app.post("/api/benchmark")
def run_benchmark_endpoint(payload: BenchmarkPayload) -> Dict[str, Any]:
    """Run baseline vs adaptive benchmark comparison."""
    from backend.services.benchmark import run_benchmark
    return run_benchmark(num_runs=min(payload.num_runs, 20))


# ── Demo scenarios ────────────────────────────────────────────────────────────

@app.get("/api/scenarios")
def list_scenarios() -> Dict[str, Any]:
    from backend.utils.constants import DEMO_SCENARIOS
    return {
        "scenarios": {
            k: {"label": v["label"], "seed": v.get("seed")}
            for k, v in DEMO_SCENARIOS.items()
        }
    }


@app.post("/api/run/scenario/{scenario_name}")
async def run_scenario(
    scenario_name: str,
    integration_mode: str = Query(default="simulation"),
) -> StreamingResponse:
    """Run a preset demo scenario with deterministic failures."""
    from backend.utils.constants import DEMO_SCENARIOS
    scenario = DEMO_SCENARIOS.get(scenario_name)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_name}")

    sim_config = dict(scenario["config"])
    if scenario.get("seed"):
        sim_config["seed"] = scenario["seed"]

    input_data = {
        "employee_id": "E-DEMO",
        "full_name":   "Demo Employee",
        "email":       "demo@company.com",
        "department":  "Engineering",
        "role":        "Senior Engineer",
        "location":    "Bengaluru",
        "start_date":  "2026-04-01",
    }
    return _run_engine_stream("employee_onboarding", input_data, sim_config, integration_mode)


# ── Checkpoint status ─────────────────────────────────────────────────────────

@app.get("/api/checkpoints")
def list_checkpoints() -> Dict[str, Any]:
    from backend.services.checkpoint import CheckpointManager
    mgr = CheckpointManager(DATA_DIR)
    return {"active_checkpoints": mgr.list_active()}


# Serve frontend — mount last so API routes take priority
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
