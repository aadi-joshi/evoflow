"""
Metrics Engine — Aggregates per-run and historical performance data.

Computes:
  - success_rate          % of runs with status "completed" (no escalations)
  - failure_rate          % of runs with escalations or errors
  - retry_count           total retries across all runs
  - escalation_rate       % of steps that ended in escalation
  - mttr_seconds          Mean Time To Recovery (avg time from first failure to recovery)
  - avg_completion_time   average total run duration in seconds
  - step_reliability      per-step success rates
  - trend                 success rate trend over last N runs
  - benchmark_comparison  static vs adaptive improvement metrics

All data is derived from audit files in data/audit_*.json — no extra DB needed.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _iso_to_ts(iso: str) -> Optional[float]:
    """Parse ISO-8601 string to Unix timestamp float."""
    try:
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return None


def _duration_seconds(start: str, end: str) -> Optional[float]:
    s, e = _iso_to_ts(start), _iso_to_ts(end)
    if s is None or e is None:
        return None
    diff = e - s
    return diff if diff >= 0 else None


class MetricsEngine:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    # ── Public API ────────────────────────────────────────────────────────────

    def aggregate(self, limit: int = 50) -> Dict[str, Any]:
        """Compute aggregate metrics across the last `limit` runs."""
        runs = self._load_runs(limit)
        if not runs:
            return self._empty_metrics()

        success_count     = 0
        escalation_count  = 0
        total_retries     = 0
        completion_times: List[float] = []
        mttr_samples:     List[float] = []
        step_stats:       Dict[str, Dict[str, int]] = {}
        per_run:          List[Dict[str, Any]] = []

        for run in runs:
            events = run["events"]
            run_id = run["run_id"]

            completed_event = next(
                (e for e in events if e.get("action") == "run_completed"), None
            )
            plan_event = next(
                (e for e in events if e.get("action") == "plan_created"), None
            )

            # Run duration
            if plan_event and completed_event:
                dur = _duration_seconds(
                    plan_event["timestamp"], completed_event["timestamp"]
                )
                if dur is not None:
                    completion_times.append(dur)

            # Success / escalation
            run_status = ""
            if completed_event:
                metrics = completed_event.get("payload", {}).get("metrics", {})
                run_status = completed_event.get("payload", {}).get("status", "")
                esc_count = metrics.get("escalation_count", 0)
                if esc_count == 0:
                    success_count += 1
                else:
                    escalation_count += 1

            # Retry events
            retry_events = [e for e in events if e.get("action") == "recovery_attempted"]
            for e in retry_events:
                total_retries += e.get("payload", {}).get("retry_count", 0)

            # MTTR: time from first step_failed to recovery_attempted where recovered=true
            mttr = self._compute_mttr(events)
            if mttr is not None:
                mttr_samples.append(mttr)

            # Per-step stats
            for e in events:
                action = e.get("action", "")
                step = e.get("payload", {}).get("step_name")
                if not step:
                    continue
                if step not in step_stats:
                    step_stats[step] = {"success": 0, "failed": 0, "retried": 0}
                if action == "step_success":
                    step_stats[step]["success"] += 1
                elif action == "step_failed":
                    step_stats[step]["failed"] += 1
                elif action == "step_retry":
                    step_stats[step]["retried"] += 1

            per_run.append({
                "run_id":       run_id,
                "status":       run_status,
                "duration_sec": completion_times[-1] if completion_times else None,
                "escalations":  escalation_count,
                "retries":      sum(
                    e.get("payload", {}).get("retry_count", 0)
                    for e in retry_events
                ),
                "mttr_sec":     mttr,
            })

        total_runs = len(runs)
        success_rate = round(success_count / total_runs * 100, 1) if total_runs else 0
        escalation_rate = round(escalation_count / total_runs * 100, 1) if total_runs else 0

        avg_completion = (
            round(statistics.mean(completion_times), 2)
            if completion_times else None
        )
        avg_mttr = (
            round(statistics.mean(mttr_samples), 2)
            if mttr_samples else None
        )

        step_reliability = {
            step: {
                "success_rate": round(
                    stats["success"] / max(stats["success"] + stats["failed"], 1) * 100, 1
                ),
                **stats,
            }
            for step, stats in step_stats.items()
        }

        return {
            "total_runs":           total_runs,
            "success_count":        success_count,
            "escalation_count":     escalation_count,
            "success_rate_pct":     success_rate,
            "failure_rate_pct":     100 - success_rate,
            "escalation_rate_pct":  escalation_rate,
            "total_retries":        total_retries,
            "avg_retries_per_run":  round(total_retries / total_runs, 2),
            "avg_completion_sec":   avg_completion,
            "mttr_seconds":         avg_mttr,
            "step_reliability":     step_reliability,
            "per_run_summary":      per_run[-10:],   # last 10 for trend
            "trend":                self._compute_trend(per_run),
        }

    # ── Chain verification endpoint helper ───────────────────────────────────

    def verify_audit(self, run_id: str) -> Dict[str, Any]:
        """Verify hash-chain integrity for a specific run's audit log."""
        from backend.agents.audit_agent import AuditAgent
        path = self.data_dir / f"audit_{run_id}.json"
        if not path.exists():
            return {"run_id": run_id, "valid": False, "reason": "audit file not found"}
        try:
            events = json.loads(path.read_text(encoding="utf-8"))
            valid, reason = AuditAgent.verify_chain(events)
            return {
                "run_id":       run_id,
                "valid":        valid,
                "reason":       reason,
                "event_count":  len(events),
                "verified_at":  datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            return {"run_id": run_id, "valid": False, "reason": str(exc)}

    # ── Private ───────────────────────────────────────────────────────────────

    def _load_runs(self, limit: int) -> List[Dict[str, Any]]:
        files = sorted(
            self.data_dir.glob("audit_*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        runs = []
        for f in files[:limit]:
            try:
                events = json.loads(f.read_text(encoding="utf-8"))
                run_id = f.stem.replace("audit_", "")
                if events:
                    run_id = events[0].get("run_id", run_id)
                runs.append({"run_id": run_id, "events": events})
            except Exception:
                continue
        return runs

    @staticmethod
    def _compute_mttr(events: List[Dict[str, Any]]) -> Optional[float]:
        """
        MTTR = time from first step_failed to first successful recovery_attempted.
        Returns None if no failure+recovery pair found.
        """
        first_failure_ts: Optional[float] = None
        for e in events:
            if e.get("action") == "step_failed" and first_failure_ts is None:
                first_failure_ts = _iso_to_ts(e.get("timestamp", ""))
            if (
                e.get("action") == "recovery_attempted"
                and e.get("payload", {}).get("recovered")
                and first_failure_ts is not None
            ):
                recovery_ts = _iso_to_ts(e.get("timestamp", ""))
                if recovery_ts and recovery_ts >= first_failure_ts:
                    return round(recovery_ts - first_failure_ts, 3)
        return None

    @staticmethod
    def _compute_trend(per_run: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return the last-10 run outcomes for sparkline rendering."""
        return [
            {
                "run_id":  r["run_id"][:8],
                "success": r["status"] in ("completed", "completed_with_escalation"),
                "dur":     r.get("duration_sec"),
                "retries": r.get("retries", 0),
            }
            for r in per_run[-10:]
        ]

    @staticmethod
    def _empty_metrics() -> Dict[str, Any]:
        return {
            "total_runs":           0,
            "success_count":        0,
            "escalation_count":     0,
            "success_rate_pct":     0,
            "failure_rate_pct":     0,
            "escalation_rate_pct":  0,
            "total_retries":        0,
            "avg_retries_per_run":  0,
            "avg_completion_sec":   None,
            "mttr_seconds":         None,
            "step_reliability":     {},
            "per_run_summary":      [],
            "trend":                [],
        }
