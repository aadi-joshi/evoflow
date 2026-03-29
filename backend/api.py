from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.agents.hitl_agent import provide_answer
from backend.services.metrics_engine import MetricsEngine
from backend.services.workflow_engine import WorkflowEngine
from backend.utils.rbac import Role, require_role

DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

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


class MeetingActionPayload(BaseModel):
    workflow_type: str = "meeting_action"
    transcript:    str
    participants:  list = []
    meeting_title: str = "Meeting"
    simulation_config: Optional[Dict[str, Any]] = None


class SLABreachPayload(BaseModel):
    workflow_type: str = "sla_breach"
    approval:      Dict[str, Any]
    org_chart:     Dict[str, Any] = {}
    simulation_config: Optional[Dict[str, Any]] = None


class GenericWorkflowPayload(BaseModel):
    workflow_type:     str
    input_data:        Dict[str, Any]
    simulation_config: Optional[Dict[str, Any]] = None


class ClarifyPayload(BaseModel):
    answer: str


# ── SSE streaming helper ──────────────────────────────────────────────────────

def _run_engine_stream(
    workflow_type: str,
    input_data: Dict[str, Any],
    simulation_config: Optional[Dict[str, Any]],
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
        engine = WorkflowEngine(data_dir=DATA_DIR, simulation_config=simulation_config)
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
    return _run_engine_stream("employee_onboarding", input_data, payload.simulation_config)


@app.post("/api/run/meeting")
async def run_meeting(payload: MeetingActionPayload) -> StreamingResponse:
    """Run meeting-to-action workflow."""
    input_data = {
        "transcript":    payload.transcript,
        "participants":  payload.participants,
        "meeting_title": payload.meeting_title,
    }
    return _run_engine_stream("meeting_action", input_data, payload.simulation_config)


@app.post("/api/run/sla")
async def run_sla(payload: SLABreachPayload) -> StreamingResponse:
    """Run SLA breach prevention workflow."""
    input_data = {
        "approval":  payload.approval,
        "org_chart": payload.org_chart,
    }
    return _run_engine_stream("sla_breach", input_data, payload.simulation_config)


@app.post("/api/run/workflow")
async def run_workflow(payload: GenericWorkflowPayload) -> StreamingResponse:
    """Generic workflow runner — accepts any workflow_type."""
    return _run_engine_stream(
        payload.workflow_type, payload.input_data, payload.simulation_config
    )


# ── Resume endpoint ───────────────────────────────────────────────────────────

@app.post("/api/resume/{run_id}")
async def resume_workflow(run_id: str) -> StreamingResponse:
    """
    Resume a previously interrupted workflow from its last checkpoint.
    Only works if a checkpoint file exists for run_id.
    """
    from backend.services.checkpoint_store import CheckpointStore
    store = CheckpointStore(DATA_DIR)
    checkpoint = store.load(run_id)
    if not checkpoint:
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found for run_id={run_id}. Cannot resume.",
        )
    workflow_type = checkpoint.get("workflow_type", "employee_onboarding")
    input_data    = checkpoint.get("input_data", {})
    return _run_engine_stream(workflow_type, input_data, simulation_config=None)


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
            events = json.loads(f.read_text(encoding="utf-8"))
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
    return json.loads(audit_file.read_text(encoding="utf-8"))


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
    return {
        "status":       "ok",
        "ai_available": is_ai_available(),
        "workflows":    ["employee_onboarding", "meeting_action", "sla_breach"],
    }


@app.get("/api/metrics")
def get_metrics(limit: int = 50) -> Dict[str, Any]:
    """Aggregate performance metrics: success rate, MTTR, retry counts, step reliability."""
    engine = MetricsEngine(DATA_DIR)
    return engine.aggregate(limit=min(limit, 200))


@app.get("/api/audit/{run_id}/verify")
def verify_audit_chain(run_id: str) -> Dict[str, Any]:
    """Verify hash-chain integrity of an audit log — tamper detection."""
    engine = MetricsEngine(DATA_DIR)
    return engine.verify_audit(run_id)


@app.get("/api/benchmark")
def get_benchmark() -> Dict[str, Any]:
    """Return pre-computed benchmark: static vs adaptive comparison."""
    from backend.services.benchmark_engine import BenchmarkEngine
    engine = BenchmarkEngine(DATA_DIR)
    return engine.get_or_compute()


@app.post("/api/benchmark/run")
def run_benchmark(
    n: int = 30,
    _role=Depends(require_role(Role.operator)),
) -> Dict[str, Any]:
    """Trigger a fresh benchmark simulation (n runs each for static and adaptive). Requires operator role."""
    from backend.services.benchmark_engine import BenchmarkEngine
    engine = BenchmarkEngine(DATA_DIR)
    return engine.run(n_runs=min(n, 50))


@app.post("/api/reset")
def reset_state(_role=Depends(require_role(Role.admin))) -> Dict[str, Any]:
    learning_path = DATA_DIR / "learning_state.json"
    deleted = []
    if learning_path.exists():
        learning_path.unlink()
        deleted.append("learning_state.json")
    for audit_file in DATA_DIR.glob("audit_*.json"):
        audit_file.unlink()
        deleted.append(audit_file.name)
    return {"reset": True, "deleted": deleted}


# Serve frontend — mount last so API routes take priority
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
