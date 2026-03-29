# EvoFlow AI — A Self-Healing, Self-Improving Autonomous Enterprise Workflow System

## 1. Project Overview

### Problem Statement
Enterprise onboarding workflows are fragmented across SaaS tools (email, chat, ticketing, calendars). Failures in one system often block the whole process, create silent delays, and require manual coordination with poor traceability.

### Motivation
Most workflow automations are static and brittle. They do not:
- detect failures deeply,
- recover autonomously,
- continue safely with partial completion,
- learn from previous failures.

### Solution Overview
EvoFlow AI is a multi-agent autonomous workflow system that executes onboarding end-to-end, handles Jira failures using retries + escalation, logs every decision for audit, and updates strategy after each run using observed reliability metrics.

### System Architecture Explanation
The architecture uses six specialized agents with a shared workflow state. The Orchestrator plans steps, Execution Agents perform each action, Failure Detection Agent classifies issues, Recovery Agent retries/escalates, Audit Agent writes immutable run events, and Evolution Agent updates strategy for future runs.

### Workflow Execution Logic
Mandatory flow implemented:
1. Create Email Account
2. Create Slack Account
3. Create Jira Access (forced failure simulation)
4. Assign Buddy
5. Schedule Orientation Meetings
6. Send Welcome Email

Execution policy:
- Failures trigger immediate detection and diagnostic labeling.
- Recoverable failures trigger retry loop with backoff.
- Persisting Jira failure triggers escalation ticket.
- Workflow continues with downstream steps.

### Failure Handling Strategy
- Forced Jira failure (`JIRA_PROVISIONING_TIMEOUT`) on each attempt.
- Retry attempts controlled by policy (`max_retries`, backoff).
- Final escalation to `it-ops@company.com` after retries.
- Completion status can be `completed_with_escalation`.

### Evolution Mechanism
After each run, the Evolution Agent:
- updates historical per-step success/failure counters,
- computes Jira failure rate,
- adjusts strategy (e.g., increase retries, enable precheck) when failures are persistent,
- persists strategy to `backend/data/learning_state.json`.

### Impact (Quantified Assumptions)
Assuming 1,000 new hires/year:
- Manual coordination reduced from 30 min to 8 min per hire (73% reduction).
- Mean failure recovery time from 4 hours to 20 minutes for recoverable SaaS provisioning issues.
- Audit preparation effort for IT/HR compliance reduced by ~60% due to structured run logs.
- Onboarding SLA adherence improved from 82% to 96% with autonomous continuation + escalation.

### Novelty and Differentiation
- Not a chatbot; this is an autonomous workflow runtime.
- Built-in self-healing + self-evolution loop.
- Enterprise-grade observability via structured audit events per agent decision.
- Supports partial-success operations without losing momentum.

### Tech Stack
- Python 3.10+
- Standard library only (fast hackathon setup, no dependency risk)
- JSON-based policy and learning memory persistence
- Modular agent architecture for easy production migration to LLM-backed agents

---

## 2. Architecture

### Textual Architecture Diagram
```text
                          +---------------------------+
                          |      Evolution Agent      |
                          |  (policy optimization)    |
                          +-------------+-------------+
                                        ^
                                        | run summary + metrics
                                        |
+------------------+      plan      +---+-----------------------+
| Orchestrator     +--------------->|      Workflow Engine       |
| Agent            |                |  (state + control loop)    |
+--------+---------+                +---+-------------------+----+
         |                              |                   |
         |                              | step request      | audit event
         v                              v                   v
+--------+------------------+   +------+----------------+  +----------------+
| Execution Agents          |   | Failure Detection     |  | Audit Agent    |
| (email/slack/jira/etc.)   |-->| Agent                |->| (append-only   |
+-------------+-------------+   +----------+------------+  | event log)     |
              |                            |               +----------------+
              | failure result             | recover/escalate
              v                            v
       +------+----------------------------+------+
       |               Recovery Agent             |
       | (retry with backoff / escalation route) |
       +-------------------+----------------------+
                           |
                           | retry step / create escalation
                           v
                     (back to engine loop)
```

### Data Flow and Decision Loops
- Primary loop: Orchestrator -> Execute Step -> Detect Failure -> Recover -> Continue.
- Failure loop: Failure -> Retry N attempts -> Escalate -> Continue with next step.
- Evolution loop: End-of-run metrics -> Strategy update -> next run uses improved policy.

---

## 3. Agents

### 3.1 Orchestrator Agent
- **Role:** Build ordered execution plan with policy metadata.
- **Input:** Employee profile JSON, strategy JSON.
- **Output:** Array of step objects (`step_name`, `criticality`, `recovery_policy`).
- **Prompt Template:**
  ```text
  You are the Orchestrator Agent for enterprise workflow execution.
  Input: employee profile JSON and strategy JSON.
  Output: ordered workflow steps with policy and criticality metadata.
  Constraints: preserve autonomous execution, no human interruption required.
  ```
- **Example Execution:** Returns six mandatory onboarding steps, sets Jira retry policy.

### 3.2 Execution Agents
- **Role:** Execute each onboarding action.
- **Input:** `step_name`, employee data, context, attempt number.
- **Output:** `StepResult` JSON (`status`, `error_code`, timestamps, payload).
- **Prompt Template:**
  ```text
  You are an execution agent. Execute exactly one enterprise action.
  Input: step JSON, employee JSON, state context JSON.
  Output: success/failure result JSON with idempotent action metadata.
  ```
- **Example Execution:** `create_slack_account` -> success with resource reference.

### 3.3 Failure Detection Agent
- **Role:** Classify failure severity/recoverability.
- **Input:** Latest `StepResult`.
- **Output:** Diagnosis JSON (`is_failure`, `recoverable`, `route`, `reason`).
- **Prompt Template:**
  ```text
  You are the Failure Detection Agent.
  Input: latest step result JSON and workflow context JSON.
  Output: structured diagnosis containing severity, recoverability, and route.
  ```
- **Example Execution:** `JIRA_PROVISIONING_TIMEOUT` -> `recoverable=true`, route=`recover`.

### 3.4 Recovery Agent
- **Role:** Retry with backoff; escalate if retries fail.
- **Input:** Failed step, recovery policy, execution callback.
- **Output:** Recovery result JSON (`recovered`, `retry_results`, `escalation`).
- **Prompt Template:**
  ```text
  You are the Recovery Agent.
  Input: failed step result JSON + recovery policy JSON.
  Output: retry / fallback / escalation decision with rationale and next action payload.
  ```
- **Example Execution:** Retries Jira twice, then emits escalation payload.

### 3.5 Evolution Agent
- **Role:** Improve strategy using run outcomes.
- **Input:** Run summary + historical memory.
- **Output:** Updated strategy JSON.
- **Prompt Template:**
  ```text
  You are the Evolution Agent.
  Input: completed workflow state JSON and historical run metrics JSON.
  Output: updated strategy JSON to improve reliability and execution outcomes.
  ```
- **Example Execution:** High Jira failure rate -> increase `max_retries` from 2 to 3.

### 3.6 Audit Agent
- **Role:** Persist append-only trace of all agent decisions/actions.
- **Input:** Event envelope (`run_id`, actor, action, payload).
- **Output:** JSON audit file per run.
- **Prompt Template:**
  ```text
  You are the Audit Agent.
  Input: event JSON from all agents.
  Output: immutable append-only audit record with correlation IDs.
  ```
- **Example Execution:** Logs `recovery_attempted` with retry and escalation details.

---

## 4. Code Structure

```text
/backend
  /agents
    orchestrator_agent.py
    execution_agents.py
    failure_detection_agent.py
    recovery_agent.py
    evolution_agent.py
    audit_agent.py
  /services
    workflow_engine.py
  /utils
    constants.py
    helpers.py
    models.py
  /data
    .gitkeep
  main.py
README.md
requirements.txt
context/prompt-1.txt
```

### File Responsibilities
- `backend/main.py`: Entry point, runs one onboarding demo end-to-end.
- `backend/services/workflow_engine.py`: Core control loop and state management.
- `backend/agents/*.py`: Agent implementations with role-specific logic.
- `backend/utils/models.py`: Dataclasses for `WorkflowState` and `StepResult`.
- `backend/utils/constants.py`: Workflow steps, simulation settings, default policies.
- `backend/utils/helpers.py`: JSON persistence helpers.
- `backend/data/learning_state.json` (generated): Evolution memory.
- `backend/data/audit_<run_id>.json` (generated): Run audit trail.

---

## 5. Implementation

### Run Locally
```bash
cd /Users/kavyabhand/Desktop/ET-DEV
python -m backend.main
```

### Core Implementation Details
- Orchestrator creates plan from mandatory steps.
- Execution agent intentionally fails Jira provisioning.
- Failure detector marks Jira timeout as recoverable.
- Recovery agent retries with backoff, then escalates to IT Ops.
- Engine continues with buddy assignment, orientation, welcome email.
- Audit events are exported as JSON.
- Evolution agent updates reliability strategy for next run.

### Productionization Path (Post-Hackathon)
- Replace simulated execution with API adapters (Google Workspace, Slack, Jira, Calendar).
- Add queue + worker execution model for horizontal scaling.
- Store state/audit in Postgres + object storage.
- Add policy guardrails (RBAC, approval thresholds, PII redaction).

---

## 6. Example Run

### Input
```json
{
  "employee_id": "E-1042",
  "full_name": "Aarav Mehta",
  "email": "aarav.mehta@company.com",
  "department": "Data Platform",
  "role": "Senior Data Engineer",
  "location": "Bengaluru",
  "start_date": "2026-04-01"
}
```

### Step-by-Step Execution
1. `create_email_account` -> success
2. `create_slack_account` -> success
3. `create_jira_access` -> failed (`JIRA_PROVISIONING_TIMEOUT`)
4. Retry 1 -> failed
5. Retry 2 -> failed
6. Escalation created (`it-ops@company.com`)
7. `assign_buddy` -> success
8. `schedule_orientation_meetings` -> success
9. `send_welcome_email` -> success
10. Run status -> `completed_with_escalation`

### Evolution Insight (Example)
- Jira failure rate observed >= 0.5
- Strategy update:
  - `jira.max_retries` increased from 2 to 3
  - `jira.precheck_enabled` set to `true`

---

## 7. Audit Logs

### JSON Event Schema
```json
{
  "timestamp": "2026-03-25T10:12:44.212Z",
  "run_id": "3dbd7e89-6f58-4fd7-8f66-2c8a83da0234",
  "actor": "recovery_agent",
  "action": "recovery_attempted",
  "payload": {
    "recovered": false,
    "recovery_mode": "escalation",
    "retry_results": [],
    "escalation": {
      "type": "manual_intervention",
      "target": "it-ops@company.com",
      "reason": "create_jira_access failed after 3 attempts",
      "severity": "high",
      "status": "open"
    }
  }
}
```

### Example Audit Sequence
- `plan_created`
- `step_executed` (email)
- `step_executed` (slack)
- `step_executed` (jira fail)
- `failure_analysis`
- `recovery_attempted` (retry loop)
- `escalation_created`
- `step_executed` (buddy)
- `step_executed` (orientation)
- `step_executed` (welcome email)
- `run_completed`
- `strategy_evolved`

---

## 8. Demo Script

### 2–3 Minute Walkthrough

#### 0:00–0:30 — Setup Context
"EvoFlow AI autonomously executes enterprise onboarding across multiple systems, self-heals on failures, and improves strategy every run."

Show:
- Architecture section in `README.md`
- Agent folders in `/backend/agents`

#### 0:30–1:30 — Live Run + Failure Handling
Run:
```bash
python -m backend.main
```
Narrate:
- "Email and Slack are provisioned automatically."
- "Jira provisioning fails intentionally."
- "Recovery Agent retries with policy-driven backoff."
- "After persistent failure, escalation is generated, but workflow continues."

Show output fields:
- `run.status = completed_with_escalation`
- `run.escalations[0]`
- `run.metrics`

#### 1:30–2:10 — Auditability
Open generated `backend/data/audit_<run_id>.json`.
Narrate:
- "Every agent decision is timestamped and correlated by run_id."
- "This is compliance-ready and supports post-incident analysis."

#### 2:10–2:50 — Self-Evolution Wow Moment
Open `backend/data/learning_state.json`.
Narrate:
- "The system learns from repeated Jira failures and automatically adjusts retry policy for the next run."
- "That closes the loop from automation to autonomous optimization."

### Wow Moment
The strongest moment is when the system does **all three** in one run:
1. Detects failure,
2. Self-recovers and escalates,
3. Updates future strategy without human reconfiguration.
