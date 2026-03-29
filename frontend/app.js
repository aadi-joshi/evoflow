'use strict';

const API = window.location.origin;

// ─── STATE ────────────────────────────────────────────────────────────────────
let activeWorkflow = 'employee_onboarding';
let activeRunId = null;
let completedSteps = 0;
let reasoningCount = 0;
let hitlTimerInterval = null;

// ─── STEP DEFINITIONS ─────────────────────────────────────────────────────────
const WORKFLOW_STEPS = {
  employee_onboarding: [
    { key: 'create_email_account',          label: 'Email Account',  icon: '✉',  system: 'Google Workspace' },
    { key: 'create_slack_account',          label: 'Slack Account',  icon: '💬', system: 'Slack' },
    { key: 'create_jira_access',            label: 'Jira Access',    icon: '🎫', system: 'Jira' },
    { key: 'assign_buddy',                  label: 'Buddy Assigned', icon: '👥', system: 'HR Portal' },
    { key: 'schedule_orientation_meetings', label: 'Orientation',    icon: '📅', system: 'Calendar' },
    { key: 'send_welcome_email',            label: 'Welcome Email',  icon: '✉',  system: 'Notification' },
  ],
  meeting_action: [
    { key: 'parse_transcript',    label: 'Parse Transcript', icon: '📄', system: 'Meeting Intelligence' },
    { key: 'extract_action_items', label: 'Extract Actions', icon: '🔍', system: 'LLM Reasoning' },
    { key: 'assign_owners',       label: 'Assign Owners',   icon: '👤', system: 'HR Portal' },
    { key: 'create_tasks',        label: 'Create Tasks',    icon: '✅', system: 'Project Tracker' },
    { key: 'send_summary',        label: 'Send Summary',    icon: '📧', system: 'Email' },
  ],
  sla_breach: [
    { key: 'detect_breach_risk',  label: 'Detect Risk',     icon: '🔎', system: 'SLA Monitor' },
    { key: 'identify_bottleneck', label: 'Find Bottleneck', icon: '🔍', system: 'Workflow Analytics' },
    { key: 'find_delegate',       label: 'Find Delegate',   icon: '👥', system: 'Org Chart' },
    { key: 'reroute_approval',    label: 'Reroute Approval', icon: '🔄', system: 'Approval System' },
    { key: 'log_override',        label: 'Log Override',    icon: '📋', system: 'Audit Log' },
    { key: 'notify_stakeholders', label: 'Notify All',      icon: '📢', system: 'Notification' },
  ],
};

// Default simulation probabilities shown in sliders
const DEFAULT_PROBS = {
  employee_onboarding: {
    create_email_account: 0.05, create_slack_account: 0.05,
    create_jira_access: 0.85, assign_buddy: 0.05,
    schedule_orientation_meetings: 0.05, send_welcome_email: 0.03,
  },
  meeting_action: {
    parse_transcript: 0.05, extract_action_items: 0.10,
    assign_owners: 0.15, create_tasks: 0.08, send_summary: 0.04,
  },
  sla_breach: {
    detect_breach_risk: 0.05, identify_bottleneck: 0.08,
    find_delegate: 0.20, reroute_approval: 0.10,
    log_override: 0.03, notify_stakeholders: 0.05,
  },
};

let simProbs = JSON.parse(JSON.stringify(DEFAULT_PROBS));

// ─── AI STATUS ────────────────────────────────────────────────────────────────
async function checkAiStatus() {
  try {
    const data = await fetch(`${API}/api/status`).then(r => r.json());
    const badge = document.getElementById('aiBadge');
    if (data.ai_available) {
      badge.textContent = 'AI: active';
      badge.classList.add('ai-active');
    } else {
      badge.textContent = 'AI: fallback mode';
      badge.classList.add('ai-fallback');
      badge.title = 'Set OPENAI_API_KEY in .env to enable GenAI reasoning';
    }
  } catch (_) {}
}
checkAiStatus();

// ─── TAB SWITCHING ────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`panel-${tab.dataset.tab}`).classList.add('active');
    if (tab.dataset.tab === 'history')   loadHistory();
    if (tab.dataset.tab === 'learning')  loadLearning();
    if (tab.dataset.tab === 'metrics')   loadMetrics();
    if (tab.dataset.tab === 'benchmark') loadBenchmark();
  });
});

// ─── WORKFLOW SELECTOR ────────────────────────────────────────────────────────
document.querySelectorAll('.wf-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.wf-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeWorkflow = btn.dataset.wf;
    // Switch forms
    document.querySelectorAll('.wf-form').forEach(f => f.style.display = 'none');
    document.getElementById(`form-${activeWorkflow}`).style.display = 'block';
    // Reset pipeline
    document.getElementById('pipelineSteps').innerHTML =
      '<div class="pipeline-empty">Configure the workflow above and click Execute to begin.</div>';
    document.getElementById('resultsArea').style.display = 'none';
    // Update sim sliders
    renderSimSliders(activeWorkflow);
  });
});

// ─── SIMULATION SLIDERS ───────────────────────────────────────────────────────
function renderSimSliders(wf) {
  const steps = WORKFLOW_STEPS[wf] || [];
  const probs = simProbs[wf] || {};
  const container = document.getElementById('simSliders');
  container.innerHTML = '';
  steps.forEach(step => {
    const prob = probs[step.key] ?? 0.05;
    const pct  = Math.round(prob * 100);
    const row  = document.createElement('div');
    row.className = 'sim-row';
    row.innerHTML = `
      <div class="sim-step-name">${step.label}</div>
      <input type="range" class="sim-slider" min="0" max="100" step="5" value="${pct}"
        data-step="${step.key}" title="${pct}%">
      <span class="sim-pct" id="sim-pct-${step.key}">${pct}%</span>
    `;
    const slider = row.querySelector('.sim-slider');
    slider.addEventListener('input', () => {
      const v = parseInt(slider.value);
      document.getElementById(`sim-pct-${step.key}`).textContent = v + '%';
      simProbs[wf][step.key] = v / 100;
    });
    container.appendChild(row);
  });
}
renderSimSliders('employee_onboarding');

// ─── PIPELINE ─────────────────────────────────────────────────────────────────
const STEP_STATE = {};

function initPipeline(wf) {
  const steps = WORKFLOW_STEPS[wf] || [];
  const container = document.getElementById('pipelineSteps');
  container.innerHTML = '';
  completedSteps = 0;
  reasoningCount = 0;
  document.getElementById('reasoningCount').textContent = '0 decisions';

  steps.forEach((step, index) => {
    STEP_STATE[step.key] = { status: 'pending', attempts: 0 };
    const node = document.createElement('div');
    node.className = 'step-node pending';
    node.id = `step-${step.key}`;
    node.innerHTML = `
      <div class="step-box">
        <span class="step-icon">${step.icon}</span>
        <div class="step-label">${step.label}</div>
        <div class="step-system">${step.system}</div>
        <div class="step-status-badge">pending</div>
        <div class="step-attempt-count"></div>
      </div>
    `;
    container.appendChild(node);
    if (index < steps.length - 1) {
      const arrow = document.createElement('div');
      arrow.className = 'step-arrow';
      arrow.id = `conn-${index}`;
      arrow.textContent = '→';
      container.appendChild(arrow);
    }
  });
}

function setStepState(stepKey, status, attempts) {
  const node = document.getElementById(`step-${stepKey}`);
  if (!node) return;
  const steps = WORKFLOW_STEPS[activeWorkflow] || [];
  node.className = `step-node ${status}`;
  node.querySelector('.step-status-badge').textContent = status;
  const attEl = node.querySelector('.step-attempt-count');
  if (attempts > 1)         attEl.textContent = `attempt ${attempts}`;
  else if (status === 'running') attEl.textContent = 'executing…';
  else                           attEl.textContent = '';
  STEP_STATE[stepKey] = { status, attempts: attempts || 0 };

  const stepIndex = steps.findIndex(s => s.key === stepKey);
  if (stepIndex > 0) {
    const prevArrow = document.getElementById(`conn-${stepIndex - 1}`);
    if (prevArrow) {
      if (['running', 'success', 'escalated', 'waiting'].includes(status))
        prevArrow.className = 'step-arrow completed';
      else if (status === 'retrying')
        prevArrow.className = 'step-arrow running';
    }
  }
  if (stepIndex >= 0 && stepIndex < steps.length - 1) {
    const nextArrow = document.getElementById(`conn-${stepIndex}`);
    if (nextArrow) {
      if (['running', 'retrying'].includes(status))
        nextArrow.className = 'step-arrow running';
      else if (['success', 'escalated'].includes(status))
        nextArrow.className = 'step-arrow completed';
    }
  }
}

// ─── AGENT STATE ──────────────────────────────────────────────────────────────
const AGENT_MAP = {
  orchestrator_agent:      'ag-orchestrator',
  execution_agents:        'ag-execution',
  failure_detection_agent: 'ag-failure',
  strategy_agent:          'ag-strategy',
  recovery_agent:          'ag-recovery',
  hitl_agent:              'ag-hitl',
  evolution_agent:         'ag-evolution',
  audit_agent:             'ag-audit',
};

function setAgentState(agentId, state, label) {
  const el = document.getElementById(agentId);
  if (!el) return;
  el.className = `agent-item ${state}`;
  el.querySelector('.agent-state').textContent = label;
}

function resetAgents() {
  Object.values(AGENT_MAP).forEach(id => setAgentState(id, '', 'standby'));
}

// ─── EVENT LOG ────────────────────────────────────────────────────────────────
let logEmpty = true;

function logEvent(type, data) {
  const log = document.getElementById('eventLog');
  if (logEmpty) { log.innerHTML = ''; logEmpty = false; }
  const time = new Date().toLocaleTimeString('en-US', { hour12: false });
  const msg = buildLogMessage(type, data);
  if (!msg) return;
  const row = document.createElement('div');
  row.className = 'log-event';
  row.innerHTML = `
    <span class="log-time">${time}</span>
    <span class="log-tag tag-${type}">${type}</span>
    <span class="log-msg">${escHtml(msg)}</span>
  `;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function buildLogMessage(type, data) {
  switch (type) {
    case 'plan_created':
      return `Plan ready — ${data.plan?.length} steps for ${data.workflow_type} ${data.ai_generated ? '(AI-enriched)' : '(deterministic)'}`;
    case 'step_started':
      return `Starting ${data.step_name} (attempt ${data.attempt})`;
    case 'step_executed':
      return `${data.step_name} → ${data.status}${data.error_code ? ' [' + data.error_code + ']' : ''}`;
    case 'step_success':
      return `${data.step_name} completed`;
    case 'step_failed':
      return `${data.step_name} FAILED — ${data.error_code}`;
    case 'step_retry':
      return `Retrying ${data.step_name} — attempt ${data.attempt}`;
    case 'recovery_attempted':
      return `Recovery [${data.strategy_name || 'default'}]: ${data.retry_count} retries, recovered=${data.recovered}`;
    case 'escalation_created':
      return `Escalation → ${data.target} — "${(data.reason || '').slice(0, 80)}"`;
    case 'strategy_generated':
      return `Strategy: "${data.strategy_name}" (confidence ${pct(data.confidence)}) ${data.ai_generated ? '[AI]' : '[fallback]'}`;
    case 'run_completed':
      return `Run finished — status: ${data.status} | ${data.metrics?.failed_events ?? 0} failed`;
    case 'strategy_evolved':
      return `Evolution: jira_failure_rate=${pct(data.jira_failure_rate)}, max_retries → ${data.updated_strategy?.max_retries} ${data.ai_generated ? '[AI]' : '[deterministic]'}`;
    case 'audit_exported':
      return `Audit trail saved → ${data.audit_file}`;
    case 'clarification_needed':
      return `HITL: Paused at ${data.step_name} — "${data.question?.slice(0, 80)}"`;
    case 'clarification_received':
      return `HITL: Answer received — "${data.answer}"`;
    case 'clarification_timeout':
      return `HITL: Timed out at ${data.step_name} — auto-escalating`;
    case 'ai_reasoning':
      return null;
    case 'done':
      return `— run complete —`;
    case 'error':
      return `ERROR: ${data.message}`;
    default:
      return null;
  }
}

document.getElementById('btnClearLog').addEventListener('click', () => {
  document.getElementById('eventLog').innerHTML = '<div class="log-empty">Events will appear here during execution.</div>';
  logEmpty = true;
});

// ─── AI REASONING PANEL ───────────────────────────────────────────────────────
let reasoningEmpty = true;

const AGENT_LABELS = {
  orchestrator_agent:      'Orchestrator',
  failure_detection_agent: 'Failure Detection',
  strategy_agent:          'Strategy',
  recovery_agent:          'Recovery',
  evolution_agent:         'Evolution',
};

const DECISION_ICONS = {
  continue: '✓', retry: '↻', escalate: '⚠', escalated: '⚠',
  recovered: '✓', plan_created: '📋', strategy_evolved: '🧬', clarify: '🤔',
};

function addReasoningCard(data) {
  const panel = document.getElementById('reasoningLog');
  if (reasoningEmpty) { panel.innerHTML = ''; reasoningEmpty = false; }
  reasoningCount++;
  document.getElementById('reasoningCount').textContent =
    `${reasoningCount} decision${reasoningCount !== 1 ? 's' : ''}`;

  const confidencePct = Math.round((data.confidence || 0.5) * 100);
  const confidenceCls = confidencePct >= 80 ? 'conf-high' : confidencePct >= 60 ? 'conf-med' : 'conf-low';
  const icon = DECISION_ICONS[data.decision] || '•';
  const agentLabel = AGENT_LABELS[data.agent] || data.agent;
  const aiBadge = data.ai_generated
    ? '<span class="ai-tag">AI</span>'
    : '<span class="ai-tag fallback">fallback</span>';

  const card = document.createElement('div');
  card.className = `reasoning-card ${data.decision === 'escalated' || data.decision === 'escalate' ? 'reasoning-warn' : ''}`;
  card.innerHTML = `
    <div class="reasoning-card-header">
      <span class="reasoning-agent">${icon} ${agentLabel}</span>
      ${data.step_name ? `<span class="reasoning-step">${data.step_name}</span>` : ''}
      ${aiBadge}
      <span class="reasoning-confidence ${confidenceCls}">${confidencePct}%</span>
    </div>
    <div class="reasoning-decision">Decision: <strong>${data.decision}</strong></div>
    <div class="reasoning-text">${escHtml(data.reasoning || '')}</div>
    ${data.severity ? `<div class="reasoning-meta">Severity: <span class="sev-${data.severity}">${data.severity}</span></div>` : ''}
  `;
  panel.appendChild(card);
  panel.scrollTop = panel.scrollHeight;
}

function addStrategyCard(data) {
  const panel = document.getElementById('reasoningLog');
  if (reasoningEmpty) { panel.innerHTML = ''; reasoningEmpty = false; }
  reasoningCount++;
  document.getElementById('reasoningCount').textContent =
    `${reasoningCount} decision${reasoningCount !== 1 ? 's' : ''}`;

  const confidencePct = Math.round((data.confidence || 0.5) * 100);
  const confidenceCls = confidencePct >= 80 ? 'conf-high' : confidencePct >= 60 ? 'conf-med' : 'conf-low';
  const aiBadge = data.ai_generated
    ? '<span class="ai-tag">AI</span>'
    : '<span class="ai-tag fallback">fallback</span>';
  const rp = data.retry_policy || {};

  const card = document.createElement('div');
  card.className = 'reasoning-card reasoning-strategy';
  card.innerHTML = `
    <div class="reasoning-card-header">
      <span class="reasoning-agent">🔧 Strategy Agent</span>
      ${data.step_name ? `<span class="reasoning-step">${data.step_name}</span>` : ''}
      ${aiBadge}
      <span class="reasoning-confidence ${confidenceCls}">${confidencePct}%</span>
    </div>
    <div class="reasoning-decision">Strategy: <strong>${escHtml(data.strategy_name || '')}</strong></div>
    <div class="reasoning-text">${escHtml(data.justification || '')}</div>
    <div class="strategy-policy">
      max_retries: <strong>${rp.max_retries ?? '—'}</strong> &nbsp;|&nbsp;
      backoff: <strong>[${(rp.backoff || []).map(v => v + 's').join(', ')}]</strong>
    </div>
    ${data.prechecks?.length ? `<div class="strategy-checks">Prechecks: ${data.prechecks.map(p => `<code>${escHtml(p)}</code>`).join(' ')}</div>` : ''}
  `;
  panel.appendChild(card);
  panel.scrollTop = panel.scrollHeight;
}

// ─── HITL MODAL ───────────────────────────────────────────────────────────────
function showHITL(data) {
  const overlay = document.getElementById('hitlOverlay');
  document.getElementById('hitlStepName').textContent = data.step_name || '';
  document.getElementById('hitlQuestion').textContent = data.question || '';
  document.getElementById('hitlAnswer').value = '';
  setAgentState(AGENT_MAP.hitl_agent, 'alert', 'waiting');

  // Options
  const optionsEl = document.getElementById('hitlOptions');
  optionsEl.innerHTML = '';
  (data.options || []).forEach(opt => {
    const btn = document.createElement('button');
    btn.className = 'hitl-option-btn';
    btn.textContent = opt;
    btn.addEventListener('click', () => {
      document.getElementById('hitlAnswer').value = opt;
    });
    optionsEl.appendChild(btn);
  });

  overlay.style.display = 'flex';
  document.getElementById('hitlAnswer').focus();

  // Countdown timer
  let remaining = data.timeout_seconds || 300;
  clearInterval(hitlTimerInterval);
  hitlTimerInterval = setInterval(() => {
    remaining--;
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    document.getElementById('hitlTimer').textContent =
      `${m}:${s.toString().padStart(2, '0')} remaining before auto-escalation`;
    if (remaining <= 0) {
      clearInterval(hitlTimerInterval);
      hideHITL();
    }
  }, 1000);
}

function hideHITL() {
  document.getElementById('hitlOverlay').style.display = 'none';
  clearInterval(hitlTimerInterval);
  setAgentState(AGENT_MAP.hitl_agent, '', 'standby');
}

document.getElementById('btnHitlSubmit').addEventListener('click', async () => {
  const answer = document.getElementById('hitlAnswer').value.trim();
  if (!answer || !activeRunId) return;
  try {
    await fetch(`${API}/api/clarify/${activeRunId}`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ answer }),
    });
    hideHITL();
    setAgentState(AGENT_MAP.hitl_agent, 'done', 'answered');
  } catch (e) {
    console.error('HITL submit failed:', e);
  }
});

document.getElementById('hitlAnswer').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('btnHitlSubmit').click();
});

// ─── ENGINE STATUS ─────────────────────────────────────────────────────────────
function setEngineStatus(state, label) {
  document.getElementById('engineStatus').className = `status-dot ${state}`;
  document.getElementById('engineStatusLabel').textContent = label;
}

// ─── SSE EVENT HANDLER ────────────────────────────────────────────────────────
function handleEvent(type, data) {
  logEvent(type, data);

  switch (type) {
    case 'plan_created':
      activeRunId = data.run_id;
      document.getElementById('runIdDisplay').textContent = `run: ${data.run_id?.slice(0, 8)}…`;
      setAgentState(AGENT_MAP.orchestrator_agent, 'done', 'done');
      setAgentState(AGENT_MAP.audit_agent, 'active', 'logging');
      break;

    case 'step_started':
      setAgentState(AGENT_MAP.execution_agents, 'active', 'executing');
      setStepState(data.step_name, 'running', 1);
      break;

    case 'step_executed':
      if (data.status === 'failed') {
        setAgentState(AGENT_MAP.failure_detection_agent, 'active', 'analyzing…');
      }
      break;

    case 'step_success':
      completedSteps++;
      setStepState(data.step_name, 'success', 0);
      setAgentState(AGENT_MAP.failure_detection_agent, 'done', 'clear');
      break;

    case 'step_failed':
      setStepState(data.step_name, 'failed', 1);
      setAgentState(AGENT_MAP.failure_detection_agent, 'alert', 'FAILURE');
      break;

    case 'step_retry': {
      const att = data.attempt;
      setStepState(data.step_name, 'retrying', att);
      setAgentState(AGENT_MAP.recovery_agent, 'active', `retry ${att}`);
      setAgentState(AGENT_MAP.failure_detection_agent, 'alert', 'failure');
      break;
    }

    case 'strategy_generated':
      setAgentState(AGENT_MAP.strategy_agent, 'active', 'generating…');
      addStrategyCard(data);
      break;

    case 'recovery_attempted':
      if (data.recovered) {
        setAgentState(AGENT_MAP.recovery_agent, 'done', 'recovered');
        setStepState(data.step_name, 'success', data.retry_count);
      } else {
        setAgentState(AGENT_MAP.recovery_agent, 'done', 'escalated');
        setStepState(data.step_name, 'escalated', data.retry_count);
      }
      break;

    case 'escalation_created':
      if (data.step_name) setStepState(data.step_name, 'escalated', 0);
      break;

    case 'clarification_needed':
      setStepState(data.step_name, 'waiting', 0);
      setAgentState(AGENT_MAP.hitl_agent, 'alert', 'waiting');
      showHITL(data);
      break;

    case 'clarification_received':
    case 'clarification_timeout':
      hideHITL();
      break;

    case 'strategy_generated':
      setAgentState(AGENT_MAP.strategy_agent, 'active', 'generating…');
      addStrategyCard(data);
      break;

    case 'strategy_evolved':
      setAgentState(AGENT_MAP.evolution_agent, 'done', 'evolved');
      break;

    case 'audit_exported':
      setAgentState(AGENT_MAP.audit_agent, 'done', 'exported');
      break;

    case 'run_completed':
      setEngineStatus('success', 'Complete');
      document.getElementById('btnRun').disabled = false;
      document.getElementById('btnRun').textContent = '▶ Execute Workflow';
      renderResults(data);
      break;

    case 'ai_reasoning':
      addReasoningCard(data);
      break;

    case 'done':
      setEngineStatus('success', 'Done');
      document.getElementById('btnRun').disabled = false;
      break;

    case 'error':
      setEngineStatus('error', 'Error');
      document.getElementById('btnRun').disabled = false;
      break;
  }
}

// ─── RESULTS + IMPACT ────────────────────────────────────────────────────────
function renderResults(data) {
  const area = document.getElementById('resultsArea');
  area.style.display = 'flex';

  // Impact card
  const impact = data.impact || {};
  const impactGrid = document.getElementById('impactGrid');
  impactGrid.innerHTML = '';

  const impactMetrics = getImpactMetrics(activeWorkflow, impact);
  impactMetrics.forEach(({ label, value, sub }) => {
    const cell = document.createElement('div');
    cell.className = 'impact-cell';
    cell.innerHTML = `
      <div class="impact-value">${value}</div>
      <div class="impact-label">${label}</div>
      ${sub ? `<div class="impact-sub">${sub}</div>` : ''}
    `;
    impactGrid.appendChild(cell);
  });

  // Run summary
  const metrics = data.metrics || {};
  const grid = document.getElementById('resultsGrid');
  const items = [
    { label: 'Status',        value: data.status || '—' },
    { label: 'Steps Run',     value: metrics.distinct_steps ?? '—' },
    { label: 'Step Events',   value: metrics.total_step_events ?? '—' },
    { label: 'Failures',      value: metrics.failed_events ?? '—' },
    { label: 'Escalations',   value: metrics.escalation_count ?? '—' },
    { label: 'Automation %',  value: impact.automation_rate_pct != null ? impact.automation_rate_pct + '%' : '—' },
  ];
  grid.innerHTML = '';
  items.forEach(({ label, value }) => {
    const cell = document.createElement('div');
    cell.className = 'result-cell';
    cell.innerHTML = `<div class="result-value">${escHtml(String(value))}</div><div class="result-label">${label}</div>`;
    grid.appendChild(cell);
  });
}

function getImpactMetrics(wf, impact) {
  if (wf === 'employee_onboarding') return [
    { label: 'Time Saved / Run', value: `${impact.time_saved_hours_per_run ?? 0}h`, sub: 'vs manual process' },
    { label: 'Cost Saved / Run', value: `$${(impact.cost_saved_per_run_usd ?? 0).toLocaleString()}`, sub: 'incl. error remediation' },
    { label: 'Monthly Savings', value: `$${(impact.monthly_cost_savings_usd ?? 0).toLocaleString()}`, sub: `at ${20} onboardings/mo` },
    { label: 'Days to Productive', value: `−${impact.time_to_productive_improvement_days ?? 0} days`, sub: 'faster ramp-up' },
  ];
  if (wf === 'meeting_action') return [
    { label: 'Time Saved / Meeting', value: `${impact.time_saved_hours_per_meeting ?? 0}h`, sub: 'vs manual follow-up' },
    { label: 'Monthly Time Savings', value: `${impact.monthly_time_savings_hours ?? 0}h`, sub: `across ${80} meetings/mo` },
    { label: 'Revenue Protected', value: `$${(impact.monthly_revenue_at_risk_protected_usd ?? 0).toLocaleString()}`, sub: 'from missed follow-ups' },
    { label: 'Action Items Captured', value: impact.action_items_captured ?? '—', sub: 'this run' },
  ];
  if (wf === 'sla_breach') return [
    { label: 'Penalties Avoided / Mo', value: `$${(impact.penalties_avoided_per_month_usd ?? 0).toLocaleString()}`, sub: 'avg $15K/breach' },
    { label: 'Total Monthly Value', value: `$${(impact.total_monthly_value_usd ?? 0).toLocaleString()}`, sub: 'penalties + labor' },
    { label: 'Firefighting Hours Saved', value: `${impact.monthly_firefighting_hours_saved ?? 0}h/mo`, sub: 'per breach prevented' },
    { label: 'Response Time', value: `${impact.time_saved_per_breach_hours ?? 0}h faster`, sub: 'vs manual escalation' },
  ];
  return [];
}

// ─── FORM SUBMISSIONS ─────────────────────────────────────────────────────────
document.getElementById('runForm').addEventListener('submit', async e => {
  e.preventDefault();
  if (activeWorkflow !== 'employee_onboarding') return;

  const payload = {
    workflow_type: 'employee_onboarding',
    employee_id:   document.getElementById('f-id').value,
    full_name:     document.getElementById('f-name').value,
    email:         document.getElementById('f-email').value,
    department:    document.getElementById('f-dept').value,
    role:          document.getElementById('f-role').value,
    location:      document.getElementById('f-loc').value,
    start_date:    document.getElementById('f-date').value,
    simulation_config: buildSimConfig('employee_onboarding'),
  };

  startRun('/api/run', payload);
});

document.getElementById('meetingForm').addEventListener('submit', async e => {
  e.preventDefault();
  const rawParticipants = document.getElementById('m-participants').value;
  const participants = rawParticipants.split(',').map(p => p.trim()).filter(Boolean);
  const payload = {
    workflow_type:  'meeting_action',
    transcript:     document.getElementById('m-transcript').value,
    participants,
    meeting_title:  document.getElementById('m-title').value,
    simulation_config: buildSimConfig('meeting_action'),
  };
  startRun('/api/run/meeting', payload);
});

document.getElementById('slaForm').addEventListener('submit', async e => {
  e.preventDefault();
  const stuckHours    = parseInt(document.getElementById('s-stuck').value) || 52;
  const deadlineHours = parseInt(document.getElementById('s-deadline').value) || 20;
  const now = new Date();
  const stuckSince = new Date(now.getTime() - stuckHours * 3600000).toISOString();
  const deadline   = new Date(now.getTime() + deadlineHours * 3600000).toISOString();

  const delegateStr = document.getElementById('s-delegate').value;
  const delegateNames = delegateStr.split(',').map(d => d.trim()).filter(Boolean);
  const orgChart = {};
  delegateNames.forEach((d, i) => { orgChart[`delegate_${i+1}`] = d; });

  const payload = {
    workflow_type: 'sla_breach',
    approval: {
      approval_id:       document.getElementById('s-id').value,
      description:       document.getElementById('s-desc').value,
      approver_name:     document.getElementById('s-approver').value,
      approver_role:     document.getElementById('s-approver-role').value,
      approver_email:    document.getElementById('s-approver').value.toLowerCase().replace(/ /g, '.') + '@company.com',
      stuck_since:       stuckSince,
      sla_deadline:      deadline,
      hours_remaining:   deadlineHours,
    },
    org_chart: orgChart,
    simulation_config: buildSimConfig('sla_breach'),
  };
  startRun('/api/run/sla', payload);
});

function buildSimConfig(wf) {
  const probs = simProbs[wf] || {};
  const cfg = {};
  Object.entries(probs).forEach(([step, prob]) => {
    cfg[step] = { failure_probability: prob };
  });
  return cfg;
}

function startRun(endpoint, payload) {
  const btnRun = document.getElementById('btnRun');
  const btnMeeting = document.getElementById('btnRunMeeting');
  const btnSLA = document.getElementById('btnRunSLA');
  [btnRun, btnMeeting, btnSLA].forEach(b => { if (b) { b.disabled = true; b.textContent = 'Running…'; } });

  setEngineStatus('running', 'Running');
  resetAgents();
  initPipeline(activeWorkflow);
  document.getElementById('resultsArea').style.display = 'none';
  document.getElementById('runIdDisplay').textContent = '';

  // Reset reasoning
  document.getElementById('reasoningLog').innerHTML = '<div class="log-empty">Agent reasoning will appear here when AI is active.</div>';
  reasoningEmpty = true;

  const evtSource = new EventSource('');  // placeholder; we'll use fetch + manual parse
  evtSource.close();

  // Use fetch + ReadableStream for SSE
  fetch(`${API}${endpoint}`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  }).then(resp => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    function pump() {
      reader.read().then(({ done, value }) => {
        if (done) {
          setEngineStatus('success', 'Done');
          [btnRun, btnMeeting, btnSLA].forEach(b => {
            if (b) { b.disabled = false; b.textContent = b.id.includes('Meeting') ? '▶ Process Meeting' : b.id.includes('SLA') ? '▶ Run SLA Response' : '▶ Execute Workflow'; }
          });
          return;
        }
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        lines.forEach(line => {
          if (!line.startsWith('data: ')) return;
          try {
            const ev = JSON.parse(line.slice(6));
            handleEvent(ev.type, ev.data);
          } catch (_) {}
        });
        pump();
      }).catch(err => {
        console.error('SSE error:', err);
        setEngineStatus('error', 'Error');
        [btnRun, btnMeeting, btnSLA].forEach(b => { if (b) b.disabled = false; });
      });
    }
    pump();
  }).catch(err => {
    setEngineStatus('error', 'Error');
    logEvent('error', { message: String(err) });
    [btnRun, btnMeeting, btnSLA].forEach(b => { if (b) b.disabled = false; });
  });
}

// ─── RESET ────────────────────────────────────────────────────────────────────
document.getElementById('btnReset').addEventListener('click', async () => {
  if (!confirm('Reset all run history and learning state?')) return;
  await fetch(`${API}/api/reset`, { method: 'POST' });
  document.getElementById('historyList').innerHTML = '<div class="log-empty">Reset complete.</div>';
  document.getElementById('learningGrid').innerHTML = '<div class="log-empty">No evolution data yet.</div>';
  document.getElementById('strategyTimeline').innerHTML = '<div class="log-empty">Timeline will populate after multiple runs.</div>';
  document.getElementById('metricsKpiRow').innerHTML = '<div class="log-empty">No metrics yet. Run a workflow first.</div>';
  document.getElementById('stepReliabilityGrid').innerHTML = '';
  document.getElementById('runTrend').innerHTML = '';
  document.getElementById('benchmarkBadges').innerHTML = '<div class="log-empty">Click "Run 30 Simulations" to generate benchmark data.</div>';
  document.getElementById('benchmarkTable').innerHTML = '';
  document.getElementById('benchmarkChart').innerHTML = '';
  document.getElementById('benchmarkVerdict').style.display = 'none';
  document.getElementById('resultsArea').style.display = 'none';
});

// ─── HISTORY TAB ──────────────────────────────────────────────────────────────
async function loadHistory() {
  const list = document.getElementById('historyList');
  try {
    const data = await fetch(`${API}/api/history`).then(r => r.json());
    if (!data.runs?.length) {
      list.innerHTML = '<div class="log-empty">No runs yet.</div>'; return;
    }
    const WF_ICONS = { employee_onboarding: '👤', meeting_action: '📋', sla_breach: '⚡' };
    list.innerHTML = data.runs.map(run => {
      const m = run.metrics || {};
      const imp = run.impact || {};
      const wfIcon = WF_ICONS[run.workflow_type] || '🔄';
      const impactStr = formatImpactSummary(run.workflow_type, imp);
      return `
        <div class="history-item" onclick="loadAudit('${escHtml(run.run_id)}')">
          <div class="history-item-header">
            <span class="wf-tag">${wfIcon} ${(run.workflow_type || 'onboarding').replace(/_/g, ' ')}</span>
            <span class="history-run-id">${run.run_id?.slice(0, 8)}</span>
            <span class="history-time">${formatTime(run.timestamp)}</span>
            <span class="ai-decisions-badge">${run.ai_decisions} AI decisions</span>
          </div>
          <div class="history-metrics">
            <span class="hm-item">steps: ${m.distinct_steps ?? '—'}</span>
            <span class="hm-item ${m.failed_events > 0 ? 'hm-fail' : ''}">failures: ${m.failed_events ?? '—'}</span>
            <span class="hm-item">escalations: ${m.escalation_count ?? '—'}</span>
            ${impactStr ? `<span class="hm-item hm-impact">${impactStr}</span>` : ''}
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    list.innerHTML = `<div class="log-empty">Error loading history: ${e.message}</div>`;
  }
}

function formatImpactSummary(wf, imp) {
  if (!imp || !Object.keys(imp).length) return '';
  if (wf === 'employee_onboarding' && imp.monthly_cost_savings_usd)
    return `$${imp.monthly_cost_savings_usd.toLocaleString()}/mo savings`;
  if (wf === 'meeting_action' && imp.action_items_captured)
    return `${imp.action_items_captured} action items`;
  if (wf === 'sla_breach' && imp.total_monthly_value_usd)
    return `$${imp.total_monthly_value_usd.toLocaleString()} protected`;
  return '';
}

async function loadAudit(runId) {
  document.getElementById('auditRunId').textContent = runId;
  document.getElementById('auditDetail').style.display = 'block';
  document.getElementById('auditDetail').scrollIntoView({ behavior: 'smooth' });

  // Verify hash chain integrity
  let chainBadge = '';
  try {
    const verify = await fetch(`${API}/api/audit/${runId}/verify`).then(r => r.json());
    const cls = verify.valid ? 'valid' : 'invalid';
    const icon = verify.valid ? '✓ Chain Intact' : '✗ Tampered!';
    chainBadge = `<span class="integrity-badge ${cls}" style="margin-left:12px">${icon}</span>`;
  } catch (_) {}
  document.getElementById('auditRunId').innerHTML = escHtml(runId) + chainBadge;

  const events = await fetch(`${API}/api/audit/${runId}`).then(r => r.json());
  const container = document.getElementById('auditEvents');
  container.innerHTML = (Array.isArray(events) ? events : []).map(ev => {
    const ai = ev.llm_trace?.ai_generated;
    return `
      <div class="audit-event ${ai ? 'audit-ai' : ''}">
        <div class="audit-event-header">
          <span class="audit-action">${escHtml(ev.action || '')}</span>
          <span class="audit-agent">${escHtml(ev.agent || '')}</span>
          <span class="audit-ts">${formatTime(ev.timestamp)}</span>
          ${ai ? '<span class="ai-tag">AI</span>' : ''}
        </div>
        ${ev.llm_trace?.model ? `<div class="audit-model">model: ${ev.llm_trace.model} | latency: ${ev.llm_trace.latency_ms}ms</div>` : ''}
        <pre class="audit-payload">${escHtml(JSON.stringify(ev.payload, null, 2))}</pre>
      </div>
    `;
  }).join('') || '<div class="log-empty">No events found.</div>';
}

function closeAudit() {
  document.getElementById('auditDetail').style.display = 'none';
}

// ─── LEARNING / EVOLUTION TAB ─────────────────────────────────────────────────
async function loadLearning() {
  try {
    const memory = await fetch(`${API}/api/learning`).then(r => r.json());
    renderLearning(memory);
    const hist = await fetch(`${API}/api/strategy-history`).then(r => r.json());
    renderStrategyTimeline(hist);
  } catch (e) {
    document.getElementById('learningGrid').innerHTML =
      `<div class="log-empty">Error: ${e.message}</div>`;
  }
}

function renderLearning(memory) {
  const grid = document.getElementById('learningGrid');
  const stats = memory.step_stats || {};
  const strategy = memory.strategy?.jira || {};

  const cells = [
    { label: 'Total Runs',    value: memory.total_runs ?? 0 },
    { label: 'Max Retries',   value: strategy.max_retries ?? '—', note: 'Jira (evolved)' },
    { label: 'Precheck',      value: strategy.precheck_enabled ? 'Enabled' : 'Disabled', note: 'Jira' },
    { label: 'Backoff',       value: `${strategy.backoff_multiplier ?? 1.0}x`, note: 'Jira' },
    { label: 'Escalate After', value: strategy.escalate_after_attempts ?? '—', note: 'attempts' },
  ];
  grid.innerHTML = cells.map(c => `
    <div class="learn-cell">
      <div class="learn-value">${c.value}</div>
      <div class="learn-label">${c.label}</div>
      ${c.note ? `<div class="learn-note">${c.note}</div>` : ''}
    </div>
  `).join('');

  // Step reliability bars
  const stepNames = Object.keys(stats);
  if (stepNames.length) {
    const bars = document.createElement('div');
    bars.className = 'reliability-bars';
    bars.innerHTML = '<div class="panel-header" style="margin-bottom:12px">Step Reliability</div>';
    stepNames.forEach(step => {
      const s = stats[step];
      const total = (s.success || 0) + (s.failed || 0);
      const rate = total > 0 ? (s.success / total) * 100 : 100;
      const cls = rate >= 90 ? 'rel-good' : rate >= 60 ? 'rel-warn' : 'rel-bad';
      bars.innerHTML += `
        <div class="rel-row">
          <div class="rel-name">${step}</div>
          <div class="rel-bar-bg"><div class="rel-bar ${cls}" style="width:${rate}%"></div></div>
          <div class="rel-pct">${Math.round(rate)}%</div>
          <div class="rel-counts">${s.success || 0}✓ ${s.failed || 0}✗</div>
        </div>
      `;
    });
    grid.appendChild(bars);
  }
}

function renderStrategyTimeline(hist) {
  const container = document.getElementById('strategyTimeline');
  const history = hist.strategy_history || [];
  if (!history.length) {
    container.innerHTML = '<div class="log-empty">Timeline will populate after multiple runs.</div>';
    return;
  }
  container.innerHTML = history.slice(-10).reverse().map(entry => `
    <div class="timeline-entry ${entry.ai_generated ? 'timeline-ai' : ''}">
      <div class="timeline-header">
        <span class="timeline-run">Run #${entry.run_number}</span>
        <span class="timeline-rate">Jira failure rate: ${pct(entry.jira_failure_rate)}</span>
        ${entry.ai_generated ? '<span class="ai-tag">AI</span>' : '<span class="ai-tag fallback">deterministic</span>'}
      </div>
      <div class="timeline-strategy">max_retries: <strong>${entry.strategy?.jira?.max_retries ?? '—'}</strong></div>
      ${entry.reasoning ? `<div class="timeline-reasoning">${escHtml(entry.reasoning)}</div>` : ''}
    </div>
  `).join('');
}

// ─── METRICS TAB ──────────────────────────────────────────────────────────────
async function loadMetrics() {
  try {
    const data = await fetch(`${API}/api/metrics`).then(r => r.json());
    renderMetricsKpis(data);
    renderStepReliability(data.step_reliability || {});
    renderRunTrend(data.trend || []);
  } catch (e) {
    document.getElementById('metricsKpiRow').innerHTML =
      `<div class="log-empty">Error: ${escHtml(e.message)}</div>`;
  }
}

function renderMetricsKpis(data) {
  const kpis = [
    { label: 'Total Runs',      value: data.total_runs ?? 0, cls: '' },
    { label: 'Success Rate',    value: `${data.success_rate_pct ?? 0}%`,
      cls: data.success_rate_pct >= 80 ? 'kpi-success' : data.success_rate_pct >= 50 ? 'kpi-warn' : 'kpi-danger' },
    { label: 'Failure Rate',    value: `${data.failure_rate_pct ?? 0}%`,
      cls: data.failure_rate_pct > 30 ? 'kpi-danger' : data.failure_rate_pct > 10 ? 'kpi-warn' : 'kpi-success' },
    { label: 'Escalation Rate', value: `${data.escalation_rate_pct ?? 0}%`,
      cls: data.escalation_rate_pct > 40 ? 'kpi-danger' : 'kpi-warn' },
    { label: 'Total Retries',   value: data.total_retries ?? 0, cls: '' },
    { label: 'Avg Retries/Run', value: data.avg_retries_per_run ?? 0, cls: '' },
    { label: 'Avg Completion',  value: data.avg_completion_sec != null ? `${data.avg_completion_sec}s` : '—', cls: '' },
    { label: 'MTTR',            value: data.mttr_seconds != null ? `${data.mttr_seconds}s` : '—',
      cls: data.mttr_seconds != null ? 'kpi-warn' : '' },
  ];
  document.getElementById('metricsKpiRow').innerHTML = kpis.map(k => `
    <div class="kpi-card">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value ${k.cls}">${k.value}</div>
    </div>
  `).join('');
}

function renderStepReliability(steps) {
  const grid = document.getElementById('stepReliabilityGrid');
  const entries = Object.entries(steps);
  if (!entries.length) { grid.innerHTML = '<div class="log-empty">No step data yet.</div>'; return; }

  grid.innerHTML = entries.map(([step, s]) => {
    const rate = s.success_rate || 0;
    const barCls = rate >= 80 ? '' : rate >= 50 ? 'warn' : 'danger';
    return `
      <div class="step-rel-card">
        <div class="step-rel-name">${escHtml(step.replace(/_/g, ' '))}</div>
        <div class="step-rel-bar-bg">
          <div class="step-rel-bar ${barCls}" style="width:${Math.min(rate,100)}%"></div>
        </div>
        <div class="step-rel-stats">
          <span>${rate}% success</span>
          <span>${s.success ?? 0}✓ ${s.failed ?? 0}✗</span>
        </div>
      </div>
    `;
  }).join('');
}

function renderRunTrend(trend) {
  const row = document.getElementById('runTrend');
  if (!trend.length) { row.innerHTML = '<div class="log-empty">Not enough runs yet.</div>'; return; }
  row.innerHTML = trend.map((r, i) => {
    const ok = r.success;
    return `<div class="trend-dot ${ok ? 'success' : 'failure'}" title="Run ${i+1}: ${ok ? 'OK' : 'FAILED'}${r.dur ? ` (${r.dur.toFixed(1)}s)` : ''}">${ok ? '✓' : '✗'}</div>`;
  }).join('');
}

// ─── BENCHMARK TAB ────────────────────────────────────────────────────────────
async function loadBenchmark() {
  try {
    const data = await fetch(`${API}/api/benchmark`).then(r => r.json());
    if (data.static) renderBenchmark(data);
  } catch (e) {
    // Silent fail — no data yet
  }
}

async function runBenchmark() {
  const btn = document.getElementById('btnRunBenchmark');
  btn.disabled = true;
  btn.textContent = 'Running 30 simulations…';
  document.getElementById('benchmarkBadges').innerHTML =
    '<div class="log-empty">Simulating 30 static + 30 adaptive runs…</div>';
  try {
    const data = await fetch(`${API}/api/benchmark/run?n=30`, { method: 'POST' }).then(r => r.json());
    renderBenchmark(data);
  } catch (e) {
    document.getElementById('benchmarkBadges').innerHTML =
      `<div class="log-empty">Error: ${escHtml(e.message)}</div>`;
  }
  btn.disabled = false;
  btn.textContent = 'Re-run 30 Simulations';
}

function renderBenchmark(data) {
  const imp = data.improvements || {};
  const st  = data.static || {};
  const ad  = data.adaptive || {};

  // Badges
  const badges = [
    { value: `+${imp.success_rate_improvement_pct ?? 0}%`, label: 'Success Rate Improvement' },
    { value: `−${imp.escalation_reduction_pct ?? 0}%`,     label: 'Escalation Reduction' },
    { value: ad.avg_retries != null ? `${ad.avg_retries}` : '—', label: 'Avg Retries (Adaptive)' },
    { value: imp.completion_time_reduction_pct != null
        ? `−${imp.completion_time_reduction_pct}%` : 'N/A',
      label: 'Completion Time' },
  ];
  document.getElementById('benchmarkBadges').innerHTML = badges.map(b => `
    <div class="bench-badge">
      <div class="bench-badge-value">${escHtml(String(b.value))}</div>
      <div class="bench-badge-label">${b.label}</div>
    </div>
  `).join('');

  // Table
  const rows = [
    ['Success Rate',    pct(st.success_rate / 100),   pct(ad.success_rate / 100)],
    ['Failure Rate',    pct(st.failure_rate / 100),   pct(ad.failure_rate / 100)],
    ['Escalation Rate', pct(st.escalation_rate / 100), pct(ad.escalation_rate / 100)],
    ['Avg Escalations/Run', st.avg_escalations ?? '—', ad.avg_escalations ?? '—'],
    ['Avg Retries/Run',     st.avg_retries ?? '0',      ad.avg_retries ?? '—'],
    ['Total Runs Simulated', st.total_runs ?? '—',       ad.total_runs ?? '—'],
  ];
  document.getElementById('benchmarkTable').innerHTML = `
    <div class="bt-row header">
      <span class="bt-metric">Metric</span>
      <span class="bt-static">Static (no recovery)</span>
      <span class="bt-adaptive">EvoFlow Adaptive</span>
    </div>
  ` + rows.map(([m, s, a]) => `
    <div class="bt-row">
      <span class="bt-metric">${m}</span>
      <span class="bt-static">${s}</span>
      <span class="bt-adaptive">${a}</span>
    </div>
  `).join('');

  // Chart
  const chart = data.chart || {};
  const staticSeries   = chart.static   || [];
  const adaptiveSeries = chart.adaptive || [];
  if (staticSeries.length) {
    document.getElementById('benchmarkChart').innerHTML = `
      <div class="bench-chart-row">
        <span class="bench-chart-label">Static</span>
        <div class="bench-chart-cells">${staticSeries.map((v, i) =>
          `<div class="bench-cell ${v ? 'success' : 'failure'}" title="Run ${i+1}">${v ? '✓' : '✗'}</div>`
        ).join('')}</div>
      </div>
      <div class="bench-chart-row">
        <span class="bench-chart-label">Adaptive</span>
        <div class="bench-chart-cells">${adaptiveSeries.map((v, i) =>
          `<div class="bench-cell ${v ? 'success' : 'failure'}" title="Run ${i+1}">${v ? '✓' : '✗'}</div>`
        ).join('')}</div>
      </div>
    `;
  }

  // Verdict
  const verdictEl = document.getElementById('benchmarkVerdict');
  if (imp.verdict) {
    verdictEl.textContent = imp.verdict;
    verdictEl.style.display = 'block';
  }
}

// ─── UTILITIES ────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function pct(v) {
  return v != null ? Math.round(v * 100) + '%' : '—';
}

function formatTime(ts) {
  if (!ts) return '';
  try { return new Date(ts).toLocaleTimeString('en-US', { hour12: false }); }
  catch (_) { return ts.slice(11, 19) || ts; }
}
