"""
Evolution Agent — Semantic, LLM-driven strategy evolution.

Replaces the threshold-based numeric retry-increment logic with an LLM that
analyses historical performance trends and generates a semantically reasoned
updated strategy.  Persists strategy history and per-run reasoning so the
Evolution tab can show the system "thinking" across runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from backend.services.llm_service import generate_response
from backend.utils.helpers import read_json, write_json

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "evolved_strategy": {
            "type": "object",
            "properties": {
                "jira": {
                    "type": "object",
                    "properties": {
                        "max_retries":             {"type": "integer"},
                        "precheck_enabled":        {"type": "boolean"},
                        "escalate_after_attempts": {"type": "integer"},
                        "backoff_multiplier":      {"type": "number"},
                    },
                }
            },
        },
        "reasoning":      {"type": "string"},
        "changes_made":   {"type": "array", "items": {"type": "string"}},
        "confidence":     {"type": "number"},
        "trend_analysis": {"type": "string"},
    },
    "required": [
        "evolved_strategy", "reasoning", "changes_made", "confidence", "trend_analysis",
    ],
}

_DEFAULT_MEMORY: Dict[str, Any] = {
    "total_runs": 0,
    "step_stats": {},
    "strategy": {
        "jira": {
            "max_retries": 2,
            "precheck_enabled": False,
            "escalate_after_attempts": 3,
            "backoff_multiplier": 1.0,
        }
    },
    "strategy_history": [],
    "reasoning_history": [],
}


class EvolutionAgent:
    name = "evolution_agent"

    def __init__(self, memory_path: Path) -> None:
        import copy
        self.memory_path = memory_path
        raw = read_json(memory_path, None)
        # Deep-copy the default so no two agent instances ever share the same dict
        self.memory: Dict[str, Any] = copy.deepcopy(raw) if raw else copy.deepcopy(_DEFAULT_MEMORY)
        # Ensure all required keys exist (handles old / partial memory files)
        self.memory.setdefault("total_runs", 0)
        self.memory.setdefault("step_stats", {})
        self.memory.setdefault("strategy_history", [])
        self.memory.setdefault("reasoning_history", [])
        strategy = self.memory.setdefault("strategy", {})
        jira = strategy.setdefault("jira", {})
        jira.setdefault("max_retries", 2)
        jira.setdefault("precheck_enabled", False)
        jira.setdefault("escalate_after_attempts", 3)
        jira.setdefault("backoff_multiplier", 1.0)

    def current_strategy(self) -> Dict[str, Any]:
        return self.memory.get("strategy", {})

    def evolve(self, run_summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse run outcomes and evolve the global strategy using the LLM.

        Parameters
        ----------
        run_summary:
            dict with keys:
              step_status   — {step_name: "success"|"failed"}
              run_status    — "completed" | "completed_with_escalation"
              (optional) failure_analyses — list of agent reasoning dicts

        Returns a rich summary dict included in the strategy_evolved SSE event.
        """
        # ── 1. Update stats ───────────────────────────────────────────────
        self.memory["total_runs"] += 1
        step_stats: Dict[str, Any] = self.memory.setdefault("step_stats", {})

        for step_name, status in run_summary.get("step_status", {}).items():
            stat = step_stats.setdefault(step_name, {"success": 0, "failed": 0})
            stat[status] = stat.get(status, 0) + 1

        # ── 2. Compute metrics ────────────────────────────────────────────
        jira_stat = step_stats.get("create_jira_access", {"success": 0, "failed": 0})
        total_jira = jira_stat["success"] + jira_stat["failed"]
        jira_failure_rate = jira_stat["failed"] / total_jira if total_jira else 0.0

        # ── 3. Call LLM to evolve strategy ────────────────────────────────
        prompt = self._build_prompt(jira_failure_rate, run_summary)
        llm_response, llm_audit = generate_response(prompt, _OUTPUT_SCHEMA, temperature=0.4)

        if llm_audit.get("ai_generated"):
            evolved = self._apply_llm_evolution(llm_response)
            ai_generated = True
        else:
            evolved = self._deterministic_fallback(jira_failure_rate)
            ai_generated = False
            llm_audit["fallback_used"] = True

        # ── 4. Persist ────────────────────────────────────────────────────
        self.memory.setdefault("strategy_history", []).append({
            "run_number":        self.memory["total_runs"],
            "strategy":          dict(self.memory["strategy"]),
            "reasoning":         evolved.get("reasoning", ""),
            "jira_failure_rate": round(jira_failure_rate, 2),
            "ai_generated":      ai_generated,
        })

        self.memory.setdefault("reasoning_history", []).append({
            "run":          self.memory["total_runs"],
            "reasoning":    evolved.get("reasoning", ""),
            "confidence":   evolved.get("confidence", 0.5),
            "changes":      evolved.get("changes_made", []),
            "ai_generated": ai_generated,
        })

        write_json(self.memory_path, self.memory)

        # ── 5. Return ─────────────────────────────────────────────────────
        # Compute per-step failure rates for all steps
        all_step_rates: Dict[str, float] = {}
        for sn, stat in step_stats.items():
            total = stat.get("success", 0) + stat.get("failed", 0)
            all_step_rates[sn] = round(stat.get("failed", 0) / total, 3) if total else 0.0

        # System reliability score: 1 - (weighted avg failure rate)
        if all_step_rates:
            system_reliability = round(
                1.0 - sum(all_step_rates.values()) / len(all_step_rates), 3
            )
        else:
            system_reliability = 1.0

        # Step reordering: recommend moving high-failure steps later
        step_order_rec = sorted(
            all_step_rates.items(), key=lambda x: x[1]
        )  # lowest failure rate first

        return {
            "jira_failure_rate":       round(jira_failure_rate, 2),
            "updated_strategy":        self.memory["strategy"].get("jira", {}),
            "total_runs":              self.memory["total_runs"],
            "reasoning":               evolved.get("reasoning", ""),
            "changes_made":            evolved.get("changes_made", []),
            "confidence":              evolved.get("confidence", 0.5),
            "trend_analysis":          evolved.get("trend_analysis", ""),
            "ai_generated":            ai_generated,
            "all_step_failure_rates":  all_step_rates,
            "system_reliability":      system_reliability,
            "recommended_step_order":  [s[0] for s in step_order_rec],
        }

    # ─── Private ─────────────────────────────────────────────────────────────

    def _build_prompt(self, jira_failure_rate: float, run_summary: Dict[str, Any]) -> str:
        history_tail: List[Dict[str, Any]] = self.memory.get("strategy_history", [])[-5:]
        current = self.memory.get("strategy", {})
        step_stats = self.memory.get("step_stats", {})

        return (
            "You are the Evolution Agent for EvoFlow AI. Analyse the system's "
            "performance history and update the recovery strategy.\n\n"
            f"Current strategy:\n{json.dumps(current, indent=2)}\n\n"
            f"Total runs: {self.memory['total_runs']}\n"
            f"Step statistics:\n{json.dumps(step_stats, indent=2)}\n"
            f"Jira failure rate (lifetime): {jira_failure_rate:.1%}\n"
            f"Latest run status: {run_summary.get('run_status', 'unknown')}\n\n"
            f"Strategy history (last {len(history_tail)} runs):\n"
            f"{json.dumps(history_tail, indent=2)}\n\n"
            "Based on these trends:\n"
            "1. Should max_retries increase, decrease, or stay the same? Why?\n"
            "2. Should precheck_enabled be toggled?\n"
            "3. Should the backoff_multiplier change?\n"
            "4. What overall trend do you observe across runs?\n"
            "5. List every concrete change you are making to the strategy.\n"
            "6. What is your confidence in these recommendations (0.0–1.0)?\n\n"
            "Return the COMPLETE evolved_strategy object even if no changes are made. "
            "Keep max_retries between 1 and 4."
        )

    def _apply_llm_evolution(self, llm: Dict[str, Any]) -> Dict[str, Any]:
        """Merge LLM-generated strategy into memory with safety bounds."""
        new_strat = llm.get("evolved_strategy", {})
        if new_jira := new_strat.get("jira"):
            current_jira = self.memory["strategy"].setdefault("jira", {})
            # Clamp max_retries
            mr = int(new_jira.get("max_retries", current_jira.get("max_retries", 2)))
            new_jira["max_retries"] = max(1, min(mr, 4))
            new_jira.setdefault(
                "escalate_after_attempts", new_jira["max_retries"] + 1
            )
            current_jira.update(new_jira)

        return llm

    def _deterministic_fallback(self, jira_failure_rate: float) -> Dict[str, Any]:
        """Classic threshold-based logic when LLM is unavailable."""
        jira = self.memory["strategy"].setdefault("jira", {})
        prev_retries = jira.get("max_retries", 2)
        changes: List[str] = []

        if jira_failure_rate >= 0.5:
            new_retries = min(prev_retries + 1, 4)
            jira["precheck_enabled"] = True
            jira["escalate_after_attempts"] = new_retries + 1
            if new_retries != prev_retries:
                changes.append(f"Increased max_retries {prev_retries} → {new_retries}")
            changes.append("Enabled precheck_enabled")
        elif jira_failure_rate < 0.2:
            new_retries = max(prev_retries - 1, 1)
            if new_retries != prev_retries:
                changes.append(f"Decreased max_retries {prev_retries} → {new_retries}")
        else:
            new_retries = prev_retries

        jira["max_retries"] = new_retries

        return {
            "evolved_strategy": {"jira": dict(jira)},
            "reasoning": (
                f"Deterministic evolution (LLM unavailable). "
                f"Jira failure rate is {jira_failure_rate:.1%}. "
                + (f"Changes: {', '.join(changes)}." if changes else "No changes made.")
            ),
            "changes_made": changes or ["No changes — rate within acceptable range"],
            "confidence": 0.60,
            "trend_analysis": (
                f"Jira failure rate of {jira_failure_rate:.1%} "
                + ("indicates persistent instability." if jira_failure_rate >= 0.5
                   else "is within acceptable bounds.")
            ),
        }
