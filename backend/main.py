from __future__ import annotations

from pathlib import Path
import json

from backend.services.workflow_engine import WorkflowEngine
from backend.utils.env import load_env

load_env()


def demo_input() -> dict:
    return {
        "employee_id": "E-1042",
        "full_name": "Aarav Mehta",
        "email": "aarav.mehta@company.com",
        "department": "Data Platform",
        "role": "Senior Data Engineer",
        "location": "Bengaluru",
        "start_date": "2026-04-01",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "backend" / "data"
    engine = WorkflowEngine(data_dir=data_dir)

    output = engine.run_onboarding(demo_input())
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
