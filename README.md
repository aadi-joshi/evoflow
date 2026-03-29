# EvoFlow AI

EvoFlow AI is a multi-agent workflow runtime for enterprise operations. It executes structured workflows end to end, detects failures in real time, applies adaptive recovery strategies, escalates when needed, records a tamper-evident audit trail, and improves reliability over repeated runs.

The project includes a FastAPI backend, a real-time frontend, deterministic demo scenarios, benchmark tooling, and optional real Slack and SMTP integrations.

## Highlights

- Multi-agent orchestration across planning, execution, failure detection, recovery, audit, evolution, and human-in-the-loop handling
- Real-time run visibility over Server-Sent Events
- Deterministic demo scenarios for repeatable failure and recovery walkthroughs
- Tamper-evident audit export with SHA-256 hash chaining
- Step-level checkpointing for resumability and crash tolerance
- Adaptive strategy evolution based on historical outcomes
- Optional real Slack notifications and SMTP email delivery with simulation fallback

## Supported Workflows

### Employee Onboarding
Provisions access, coordinates onboarding tasks, sends welcome communications, and demonstrates recovery and escalation clearly.

### Meeting to Action
Processes a meeting transcript into action items, assignments, tasks, and follow-up communication.

### SLA Breach Prevention
Detects approval risk, reroutes decisions, and preserves a complete record of intervention steps.

## Architecture

EvoFlow is organized into four layers:

1. API layer: FastAPI endpoints and SSE streaming in `backend/api.py`
2. Orchestration layer: workflow execution control loop in `backend/services/workflow_engine.py`
3. Agent layer: specialized agents in `backend/agents/`
4. Utilities and state: models, constants, persistence, notification, benchmark, and environment loading in `backend/utils/` and `backend/services/`

Core agents:

- `OrchestratorAgent`
- `ExecutionAgents`
- `FailureDetectionAgent`
- `StrategyAgent`
- `RecoveryAgent`
- `HITLAgent`
- `EvolutionAgent`
- `AuditAgent`

## Integrations

### Slack
Real Slack delivery is supported through either:

- `SLACK_WEBHOOK_URL`
- or `SLACK_BOT_TOKEN` with `SLACK_DEFAULT_CHANNEL`

Used for:

- critical failure notifications
- escalations
- workflow completion updates

### Email
Real SMTP delivery is supported through:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_FROM`

If SMTP is not configured, EvoFlow records simulated delivery receipts instead of failing the workflow.

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill the values you want to enable.

```bash
cp .env.example .env
```

Optional configuration:

- `OPENAI_API_KEY` for LLM-powered reasoning
- Slack webhook or bot token for real Slack delivery
- SMTP settings for real email delivery

### 3. Run the API

```bash
python3 -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 --reload
```

### 4. Open the app

Visit:

```text
http://127.0.0.1:8000
```

## Deterministic Demo Scenarios

The fastest demo path is:

- workflow: `employee_onboarding`
- scenario: `jira_failure`
- simulation: `ON`
- real integrations: `ON` if Slack is configured

Available scenarios:

- `happy_path`
- `jira_failure`
- `multi_failure`
- `full_demo`

## API Overview

Run endpoints:

- `POST /api/run`
- `POST /api/run/meeting`
- `POST /api/run/sla`
- `POST /api/run/workflow`
- `POST /api/run/scenario/{scenario_name}`

Query endpoints:

- `GET /api/status`
- `GET /api/history`
- `GET /api/learning`
- `GET /api/audit/{run_id}`
- `GET /api/strategy-history`
- `GET /api/scenarios`
- `GET /api/checkpoints`

Utility endpoints:

- `POST /api/clarify/{run_id}`
- `POST /api/reset`
- `POST /api/benchmark`

## Testing

Run the test suite with:

```bash
python3 -m pytest -q
```

## Deployment

The repository includes:

- `Dockerfile` for containerized deployment
- `render.yaml` for Render deployment

## Repository Structure

```text
backend/
  agents/
  services/
  utils/
  data/
frontend/
tests/
README.md
DEMO_RUNBOOK.md
DEMO_SCRIPT.md
Dockerfile
render.yaml
requirements.txt
```

## Notes

- `.env`, runtime audit files, learning state, checkpoints, caches, and local virtual environments should not be committed
- when Slack or SMTP is not configured, EvoFlow preserves behavior through simulation fallback instead of crashing
- if `OPENAI_API_KEY` is not set, the system runs with deterministic fallback logic
