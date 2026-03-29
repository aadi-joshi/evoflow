'use strict';

const LANDING_SESSION_KEY = 'evoflow_started';

function resolveApiBase() {
  const { protocol, hostname, port, origin } = window.location;
  if (port === '8000') return origin;
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return `${protocol}//${hostname}:8000`;
  }
  return origin;
}

const API = resolveApiBase();

const WORKFLOW_STEPS = {
  employee_onboarding: [
    { key: 'create_email_account', label: 'Create email account', icon: '•', system: 'Google Workspace' },
    { key: 'create_slack_account', label: 'Create Slack account', icon: '•', system: 'Slack' },
    { key: 'create_jira_access', label: 'Provision Jira access', icon: '•', system: 'Jira' },
    { key: 'assign_buddy', label: 'Assign buddy', icon: '•', system: 'HR' },
    { key: 'schedule_orientation_meetings', label: 'Schedule orientation', icon: '•', system: 'Calendar' },
    { key: 'send_welcome_email', label: 'Send welcome email', icon: '•', system: 'SMTP' },
  ],
  meeting_action: [
    { key: 'parse_transcript', label: 'Parse transcript', icon: '•', system: 'Meeting Intelligence' },
    { key: 'extract_action_items', label: 'Extract action items', icon: '•', system: 'Reasoning' },
    { key: 'assign_owners', label: 'Assign owners', icon: '•', system: 'Resolution' },
    { key: 'create_tasks', label: 'Create tasks', icon: '•', system: 'Project Tracker' },
    { key: 'send_summary', label: 'Send summary', icon: '•', system: 'Email' },
  ],
  sla_breach: [
    { key: 'detect_breach_risk', label: 'Detect breach risk', icon: '•', system: 'SLA Monitor' },
    { key: 'identify_bottleneck', label: 'Identify bottleneck', icon: '•', system: 'Analysis' },
    { key: 'find_delegate', label: 'Find delegate', icon: '•', system: 'Org Chart' },
    { key: 'reroute_approval', label: 'Reroute approval', icon: '•', system: 'Approval System' },
    { key: 'log_override', label: 'Log override', icon: '•', system: 'Audit' },
    { key: 'notify_stakeholders', label: 'Notify stakeholders', icon: '•', system: 'Notifications' },
  ],
};

const DEFAULT_PROBS = {
  employee_onboarding: {
    create_email_account: 0.05,
    create_slack_account: 0.05,
    create_jira_access: 0.85,
    assign_buddy: 0.05,
    schedule_orientation_meetings: 0.05,
    send_welcome_email: 0.03,
  },
  meeting_action: {
    parse_transcript: 0.05,
    extract_action_items: 0.10,
    assign_owners: 0.15,
    create_tasks: 0.08,
    send_summary: 0.04,
  },
  sla_breach: {
    detect_breach_risk: 0.05,
    identify_bottleneck: 0.08,
    find_delegate: 0.20,
    reroute_approval: 0.10,
    log_override: 0.03,
    notify_stakeholders: 0.05,
  },
};

const WORKFLOW_COPY = {
  employee_onboarding: {
    title: 'Employee onboarding orchestration',
    subtitle: 'Provision systems, coordinate orientation, and surface real escalation signals as the workflow unfolds.',
  },
  meeting_action: {
    title: 'Meeting-to-action conversion',
    subtitle: 'Turn transcript intelligence into owners, tasks, and polished downstream communication.',
  },
  sla_breach: {
    title: 'SLA breach prevention loop',
    subtitle: 'Make risk visible, reroute decisions, and preserve the full audit chain for every intervention.',
  },
};

const AGENT_MAP = {
  orchestrator_agent: 'ag-orchestrator',
  execution_agents: 'ag-execution',
  failure_detection_agent: 'ag-failure',
  strategy_agent: 'ag-strategy',
  recovery_agent: 'ag-recovery',
  hitl_agent: 'ag-hitl',
  evolution_agent: 'ag-evolution',
  audit_agent: 'ag-audit',
};

const AGENT_LABELS = {
  orchestrator_agent: 'Orchestrator',
  failure_detection_agent: 'Failure Detection',
  strategy_agent: 'Strategy',
  recovery_agent: 'Recovery',
  evolution_agent: 'Evolution',
};

const DECISION_ICONS = {
  continue: 'Continue',
  retry: 'Retry',
  escalated: 'Escalate',
  escalate: 'Escalate',
  recovered: 'Recovered',
  plan_created: 'Plan',
  strategy_evolved: 'Evolve',
  clarify: 'Clarify',
};

const state = {
  activeWorkflow: 'employee_onboarding',
  activeRunView: 'setup',
  activeRunId: null,
  simProbs: JSON.parse(JSON.stringify(DEFAULT_PROBS)),
  stepState: {},
  reasoningCount: 0,
  logEmpty: true,
  reasoningEmpty: true,
  integrationEmpty: true,
  hitlTimerInterval: null,
  scenarios: {},
  liveMetrics: {},
  currentAuditTarget: 'live',
  activeAgent: null,
};

document.addEventListener('DOMContentLoaded', () => {
  initLandingScreen();
  bindViewTabs();
  bindRunViewTabs();
  bindWorkflowCards();
  bindModeControls();
  bindForms();
  bindButtons();
  bindMicroInteractions();
  applyRunView(state.activeRunView);
  resetAgents();
  setActiveWorkflow('employee_onboarding');
  resetRunPanels();
  refreshSystemStatus();
});

function bindViewTabs() {
  document.querySelectorAll('.view-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.view-tab').forEach(node => node.classList.remove('active'));
      document.querySelectorAll('.view-panel').forEach(panel => panel.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`panel-${tab.dataset.tab}`).classList.add('active');
      document.body.dataset.activeTab = tab.dataset.tab;
      if (tab.dataset.tab === 'history') loadHistory();
      if (tab.dataset.tab === 'learning') loadLearning();
    });
  });
}

function bindRunViewTabs() {
  document.querySelectorAll('.run-page-tab').forEach(tab => {
    tab.addEventListener('click', () => applyRunView(tab.dataset.runView || 'setup'));
  });
}

function applyRunView(view) {
  const allowedViews = new Set(['setup', 'live', 'intel']);
  const normalizedView = allowedViews.has(view) ? view : 'setup';
  state.activeRunView = normalizedView;
  const runGrid = document.querySelector('#panel-run .run-grid');
  if (!runGrid) return;
  runGrid.dataset.runView = normalizedView;
  document.querySelectorAll('.run-page-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.runView === normalizedView);
  });
}

function initLandingScreen() {
  const landingScreen = document.getElementById('landingScreen');
  const appShell = document.getElementById('appShell');
  const getStartedButton = document.getElementById('btnGetStarted');

  const rememberStarted = () => {
    try {
      window.sessionStorage.setItem(LANDING_SESSION_KEY, '1');
    } catch (_) { }
  };

  const wasStarted = () => {
    try {
      return window.sessionStorage.getItem(LANDING_SESSION_KEY) === '1';
    } catch (_) {
      return false;
    }
  };

  const revealApp = ({ immediate = false } = {}) => {
    if (appShell) appShell.hidden = false;
    document.body.classList.remove('landing-active');
    rememberStarted();

    if (landingScreen) {
      if (immediate) {
        landingScreen.hidden = true;
      } else {
        landingScreen.classList.add('is-exiting');
        window.setTimeout(() => {
          landingScreen.hidden = true;
        }, 420);
      }
    }

    if (!immediate) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  if (!landingScreen || !appShell || !getStartedButton) {
    revealApp();
    return;
  }

  if (wasStarted()) {
    revealApp({ immediate: true });
    return;
  }

  getStartedButton.addEventListener('click', () => revealApp());

  window.setTimeout(() => {
    if (document.body.classList.contains('landing-active')) {
      revealApp();
    }
  }, 8000);
}

function bindWorkflowCards() {
  document.querySelectorAll('.workflow-card').forEach(card => {
    card.addEventListener('click', () => setActiveWorkflow(card.dataset.wf));
  });
}

function bindMicroInteractions() {
  document.querySelectorAll('button, .workflow-card').forEach(enablePressFeedback);
}

function enablePressFeedback(element) {
  if (!element || element.dataset.pressBound === 'true') return;
  element.dataset.pressBound = 'true';
  const triggerPress = () => {
    element.classList.add('is-pressed');
    window.setTimeout(() => element.classList.remove('is-pressed'), 160);
  };
  element.addEventListener('pointerdown', triggerPress);
  element.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') triggerPress();
  });
}

function animateEntry(element) {
  if (!element) return;
  element.classList.add('is-entering');
  window.setTimeout(() => element.classList.remove('is-entering'), 260);
}

function bindModeControls() {
  const simulationToggle = document.getElementById('simulationToggle');
  if (simulationToggle) {
    simulationToggle.addEventListener('change', () => renderSimSliders(state.activeWorkflow));
  }

  const realModeToggle = document.getElementById('realModeToggle');
  if (realModeToggle) {
    realModeToggle.addEventListener('change', () => {
      const selectedWorkflowBadge = document.getElementById('selectedWorkflowBadge');
      if (selectedWorkflowBadge) {
        selectedWorkflowBadge.textContent = `${state.activeWorkflow} · ${currentIntegrationMode()}`;
      }
    });
  }
}

function bindForms() {
  document.getElementById('runForm').addEventListener('submit', event => {
    event.preventDefault();
    if (state.activeWorkflow !== 'employee_onboarding') return;
    startRun({
      url: '/api/run',
      payload: {
        workflow_type: 'employee_onboarding',
        employee_id: document.getElementById('f-id').value,
        full_name: document.getElementById('f-name').value,
        email: document.getElementById('f-email').value,
        department: document.getElementById('f-dept').value,
        role: document.getElementById('f-role').value,
        location: document.getElementById('f-loc').value,
        start_date: document.getElementById('f-date').value,
        simulation_config: buildSimConfig('employee_onboarding'),
        integration_mode: currentIntegrationMode(),
      },
    });
  });

  document.getElementById('meetingForm').addEventListener('submit', event => {
    event.preventDefault();
    const participants = document.getElementById('m-participants').value
      .split(',')
      .map(entry => entry.trim())
      .filter(Boolean);
    startRun({
      url: '/api/run/meeting',
      payload: {
        workflow_type: 'meeting_action',
        meeting_title: document.getElementById('m-title').value,
        transcript: document.getElementById('m-transcript').value,
        participants,
        simulation_config: buildSimConfig('meeting_action'),
        integration_mode: currentIntegrationMode(),
      },
    });
  });

  document.getElementById('slaForm').addEventListener('submit', event => {
    event.preventDefault();
    const stuckHours = parseInt(document.getElementById('s-stuck').value || '52', 10);
    const deadlineHours = parseInt(document.getElementById('s-deadline').value || '20', 10);
    const now = Date.now();
    const stuckSince = new Date(now - stuckHours * 60 * 60 * 1000).toISOString();
    const deadline = new Date(now + deadlineHours * 60 * 60 * 1000).toISOString();
    const delegates = document.getElementById('s-delegate').value
      .split(',')
      .map(entry => entry.trim())
      .filter(Boolean);
    const orgChart = {};
    delegates.forEach((entry, index) => {
      orgChart[`delegate_${index + 1}`] = entry;
    });

    startRun({
      url: '/api/run/sla',
      payload: {
        workflow_type: 'sla_breach',
        approval: {
          approval_id: document.getElementById('s-id').value,
          description: document.getElementById('s-desc').value,
          approver_name: document.getElementById('s-approver').value,
          approver_role: document.getElementById('s-approver-role').value,
          approver_email: `${document.getElementById('s-approver').value.toLowerCase().replace(/ /g, '.')}@company.com`,
          stuck_since: stuckSince,
          sla_deadline: deadline,
          hours_remaining: deadlineHours,
        },
        org_chart: orgChart,
        simulation_config: buildSimConfig('sla_breach'),
        integration_mode: currentIntegrationMode(),
      },
    });
  });
}

function bindButtons() {
  document.getElementById('btnRunDemo').addEventListener('click', () => {
    const scenario = document.getElementById('demoScenarioSelect').value || 'jira_failure';
    setActiveWorkflow('employee_onboarding');
    startRun({
      url: `/api/run/scenario/${scenario}?integration_mode=${encodeURIComponent(currentIntegrationMode())}`,
      payload: null,
    });
  });

  document.getElementById('btnClearLog').addEventListener('click', () => {
    const log = document.getElementById('eventLog');
    log.innerHTML = '<div class="empty-state compact">Run events will stream here.</div>';
    state.logEmpty = true;
  });

  document.getElementById('btnReset').addEventListener('click', async () => {
    if (!window.confirm('Reset all run history, audit files, and learning state?')) return;
    await fetch(`${API}/api/reset`, { method: 'POST' });
    resetRunPanels();
    document.getElementById('historyList').innerHTML = '<div class="empty-state">State reset complete.</div>';
    document.getElementById('learningGrid').innerHTML = '<div class="empty-state">No learning data yet.</div>';
    document.getElementById('strategyTimeline').innerHTML = '<div class="empty-state">Timeline will populate after multiple runs.</div>';
  });

  document.getElementById('btnRefreshHistory').addEventListener('click', loadHistory);
  document.getElementById('btnRefreshLearning').addEventListener('click', loadLearning);
  document.getElementById('btnViewAudit').addEventListener('click', () => {
    if (!state.activeRunId) {
      logEvent('error', { message: 'No active run yet. Execute a workflow first.' });
      return;
    }
    loadAudit(state.activeRunId, 'live');
    document.getElementById('liveAuditSummary').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  document.getElementById('btnHitlSubmit').addEventListener('click', submitHITLAnswer);
  document.getElementById('hitlAnswer').addEventListener('keydown', event => {
    if (event.key === 'Enter') submitHITLAnswer();
  });
}

async function refreshSystemStatus() {
  try {
    const data = await fetch(`${API}/api/status`).then(response => response.json());
    setStatusChip('aiBadge', data.ai_available ? 'AI active' : 'AI fallback', data.ai_available ? 'good' : 'warn');
    setStatusChip('slackBadge', data.integrations?.slack_configured ? 'Slack ready' : 'Slack not configured', data.integrations?.slack_configured ? 'good' : 'offline');
    setStatusChip('emailBadge', data.integrations?.email_configured ? 'Email ready' : 'Email simulated', data.integrations?.email_configured ? 'good' : 'warn');
    state.scenarios = data.demo_scenarios || {};
    renderScenarioOptions();
  } catch (error) {
    setStatusChip('aiBadge', 'AI unavailable', 'offline');
    setStatusChip('slackBadge', 'Slack unknown', 'offline');
    setStatusChip('emailBadge', 'Email unknown', 'offline');
  }
}

function setStatusChip(id, text, statusClass) {
  const element = document.getElementById(id);
  element.textContent = text;
  element.className = `status-chip ${statusClass || ''}`.trim();
}

function setActiveWorkflow(workflowType) {
  state.activeWorkflow = workflowType;
  document.querySelectorAll('.workflow-card').forEach(card => {
    card.classList.toggle('active', card.dataset.wf === workflowType);
  });

  document.getElementById('runForm').style.display = workflowType === 'employee_onboarding' ? 'grid' : 'none';
  document.getElementById('meetingForm').style.display = workflowType === 'meeting_action' ? 'grid' : 'none';
  document.getElementById('slaForm').style.display = workflowType === 'sla_breach' ? 'grid' : 'none';

  const copy = WORKFLOW_COPY[workflowType];
  document.getElementById('workspaceTitle').textContent = copy.title;
  document.getElementById('workspaceSubtitle').textContent = copy.subtitle;
  document.getElementById('selectedWorkflowBadge').textContent = `${workflowType} · ${currentIntegrationMode()}`;
  renderSimSliders(workflowType);
  initTimeline(workflowType);
  resetMetrics();
}

function renderScenarioOptions() {
  const select = document.getElementById('demoScenarioSelect');
  const entries = Object.entries(state.scenarios);
  if (!entries.length) {
    select.innerHTML = '<option value="jira_failure">jira_failure</option>';
    return;
  }
  select.innerHTML = entries.map(([key, label]) => {
    return `<option value="${escHtml(key)}">${escHtml(label)}</option>`;
  }).join('');
  if ([...select.options].some(option => option.value === 'jira_failure')) {
    select.value = 'jira_failure';
  }
}

function renderSimSliders(workflowType) {
  const container = document.getElementById('simSliders');
  const simulationEnabled = document.getElementById('simulationToggle').checked;
  if (!simulationEnabled) {
    container.innerHTML = '<div class="empty-state compact">Simulation disabled. Real-mode runs will use zero forced failure probability unless a demo scenario is launched.</div>';
    return;
  }

  const steps = WORKFLOW_STEPS[workflowType] || [];
  container.innerHTML = '';
  steps.forEach(step => {
    const pctValue = Math.round((state.simProbs[workflowType][step.key] || 0) * 100);
    const row = document.createElement('div');
    row.className = 'sim-row';
    row.innerHTML = `
      <div class="sim-step-name">${escHtml(step.label)}</div>
      <input class="sim-slider" type="range" min="0" max="100" step="5" value="${pctValue}" data-step="${escHtml(step.key)}">
      <div class="sim-pct" id="sim-pct-${escHtml(step.key)}">${pctValue}%</div>
    `;
    const slider = row.querySelector('.sim-slider');
    slider.addEventListener('input', () => {
      const next = parseInt(slider.value, 10);
      state.simProbs[workflowType][step.key] = next / 100;
      document.getElementById(`sim-pct-${step.key}`).textContent = `${next}%`;
    });
    container.appendChild(row);
  });
}

function initTimeline(workflowType) {
  state.stepState = {};
  const container = document.getElementById('timelineSteps');
  const steps = WORKFLOW_STEPS[workflowType] || [];
  container.innerHTML = '';
  steps.forEach((step, index) => {
    state.stepState[step.key] = { status: 'pending', attempts: 0, message: 'Waiting to start.' };
    const item = document.createElement('article');
    item.className = 'timeline-step pending';
    item.id = `step-${step.key}`;
    item.dataset.index = String(index + 1);
    item.innerHTML = `
      <div class="timeline-connector" aria-hidden="true"></div>
      <div class="timeline-node" data-default-icon="${step.icon}">${step.icon}</div>
      <div class="timeline-body">
        <div class="timeline-topline">
          <span class="timeline-title">${escHtml(step.label)}</span>
          <span class="status-chip muted timeline-status">pending</span>
        </div>
        <div class="timeline-topline">
          <span class="timeline-system">${escHtml(step.system)}</span>
          <span class="timeline-attempt" id="attempt-${step.key}">Awaiting execution</span>
        </div>
        <p class="section-note" id="message-${step.key}">Waiting to start.</p>
      </div>
    `;
    container.appendChild(item);
    window.setTimeout(() => animateEntry(item), index * 35);
  });
}

function setStepState(stepKey, status, attempts = 0, message = '') {
  const item = document.getElementById(`step-${stepKey}`);
  if (!item) return;
  const statusChip = item.querySelector('.timeline-status');
  const node = item.querySelector('.timeline-node');
  const attemptNode = document.getElementById(`attempt-${stepKey}`);
  const messageNode = document.getElementById(`message-${stepKey}`);
  item.className = `timeline-step ${status}`;
  statusChip.textContent = status.replace(/_/g, ' ');
  statusChip.className = `status-chip ${statusTone(status)}`;
  if (node) {
    node.classList.toggle('is-running', status === 'running' || status === 'retrying');
    node.classList.toggle('is-failed', status === 'failed' || status === 'escalated');
    node.classList.toggle('is-success', status === 'success');
    node.textContent = statusIcon(status, node.dataset.defaultIcon || '•');
  }
  attemptNode.textContent = attempts > 1 ? `Attempt ${attempts}` : attemptLabel(status);
  if (message) messageNode.textContent = message;
  state.stepState[stepKey] = { status, attempts, message };
  item.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
}

function statusIcon(status, fallback = '•') {
  if (status === 'pending') return '○';
  if (status === 'running') return '⏳';
  if (status === 'retrying') return '↻';
  if (status === 'success') return '✓';
  if (status === 'failed' || status === 'escalated') return '✕';
  if (status === 'waiting') return '…';
  return fallback;
}

function statusTone(status) {
  if (status === 'success') return 'good';
  if (status === 'failed' || status === 'escalated') return 'offline';
  if (status === 'retrying' || status === 'waiting') return 'warn';
  if (status === 'running') return 'good';
  return 'muted';
}

function attemptLabel(status) {
  if (status === 'running') return 'Executing';
  if (status === 'retrying') return 'Retry in progress';
  if (status === 'waiting') return 'Waiting for input';
  if (status === 'success') return 'Completed';
  if (status === 'failed') return 'Blocked';
  if (status === 'escalated') return 'Escalated';
  return 'Awaiting execution';
}

function resetAgents() {
  Object.values(AGENT_MAP).forEach(id => setAgentState(id, '', 'standby'));
}

function setAgentState(agentId, stateClass, label) {
  const element = document.getElementById(agentId);
  if (!element) return;
  element.className = `agent-card ${stateClass}`.trim();
  element.querySelector('.agent-state').textContent = label;
  if (stateClass === 'active' || stateClass === 'alert') {
    const readable = element.querySelector('.agent-name')?.textContent || 'unknown';
    state.activeAgent = readable;
    document.getElementById('activeAgentLabel').textContent = `Active: ${readable}`;
  }
}

function resetMetrics() {
  state.liveMetrics = {
    successes: 0,
    failures: 0,
    retries: 0,
    escalations: 0,
    total: (WORKFLOW_STEPS[state.activeWorkflow] || []).length,
    mttrSeconds: null,
    totalExecutionTime: null,
  };
  renderMetrics();
}

function renderMetrics(finalMetrics = null) {
  const metrics = finalMetrics || {};
  const successPercent = finalMetrics
    ? `${Math.round((metrics.success_rate || 0) * 100)}%`
    : `${Math.round((state.liveMetrics.successes / Math.max(state.liveMetrics.total, 1)) * 100)}%`;
  const successSubtext = finalMetrics
    ? `${metrics.success_events || 0} successful events of ${metrics.total_step_events || 0}`
    : `${state.liveMetrics.successes} completed of ${state.liveMetrics.total} steps`;

  document.getElementById('metricSuccess').textContent = successPercent;
  document.getElementById('metricSuccessSub').textContent = successSubtext;

  document.getElementById('metricRetries').textContent = finalMetrics
    ? Math.max((metrics.total_step_events || 0) - (metrics.distinct_steps || 0), 0)
    : state.liveMetrics.retries;
  document.getElementById('metricRetriesSub').textContent = 'Recovery attempts observed';

  document.getElementById('metricFailures').textContent = finalMetrics
    ? metrics.failed_events || 0
    : state.liveMetrics.failures;
  document.getElementById('metricFailuresSub').textContent = finalMetrics
    ? `${metrics.escalation_count || 0} escalations created`
    : `${state.liveMetrics.escalations} escalations so far`;

  document.getElementById('metricMttr').textContent = finalMetrics && metrics.mttr_seconds != null
    ? `${metrics.mttr_seconds}s`
    : '—';
  document.getElementById('metricMttrSub').textContent = finalMetrics && metrics.total_execution_time_secs != null
    ? `${metrics.total_execution_time_secs}s total runtime`
    : 'Recovery time will populate after retries';

  document.getElementById('metricRuntime').textContent = finalMetrics && metrics.total_execution_time_secs != null
    ? `${metrics.total_execution_time_secs}s`
    : '—';
  document.getElementById('metricRuntimeSub').textContent = finalMetrics
    ? 'Measured for completed run'
    : 'Total runtime appears on completion';
}

function resetRunPanels() {
  state.activeRunId = null;
  resetAgents();
  initTimeline(state.activeWorkflow);
  resetMetrics();
  setEngineStatus('', 'Idle');
  document.getElementById('runIdDisplay').textContent = 'run not started';
  document.getElementById('selectedWorkflowBadge').textContent = `${state.activeWorkflow} · ${currentIntegrationMode()}`;
  setEmpty('eventLog', 'Run events will stream here.');
  setEmpty('reasoningLog', 'Reasoning cards will appear when AI or fallback logic makes explicit decisions.');
  setEmpty('integrationFeed', 'Live Slack and email receipts will appear here.');
  setEmpty('resultsGrid', 'Run metrics will appear here.');
  setEmpty('impactGrid', 'Impact calculations will appear after a run.');
  setEmpty('liveAuditSummary', 'The audit chain will appear after export.');
  document.getElementById('liveAuditEvents').innerHTML = '';
  document.getElementById('auditIntegrityBadge').textContent = 'No audit loaded';
  document.getElementById('auditIntegrityBadge').className = 'audit-status pending';
  state.reasoningCount = 0;
  state.reasoningEmpty = true;
  state.logEmpty = true;
  state.integrationEmpty = true;
  state.activeAgent = null;
  document.getElementById('activeAgentLabel').textContent = 'Active: none';
  document.getElementById('reasoningCount').textContent = '0 decisions';
}

function setEmpty(id, text) {
  const element = document.getElementById(id);
  element.innerHTML = `<div class="empty-state compact">${escHtml(text)}</div>`;
}

function currentIntegrationMode() {
  return document.getElementById('realModeToggle').checked ? 'real' : 'simulation';
}

function buildSimConfig(workflowType) {
  const steps = WORKFLOW_STEPS[workflowType] || [];
  const config = {};
  const simulationEnabled = document.getElementById('simulationToggle').checked;
  steps.forEach(step => {
    config[step.key] = {
      failure_probability: simulationEnabled ? (state.simProbs[workflowType][step.key] || 0) : 0,
    };
  });
  return config;
}

function startRun({ url, payload }) {
  applyRunView('live');
  disableRunButtons(true);
  resetRunPanels();
  initTimeline(state.activeWorkflow);
  setEngineStatus('running', 'Running');

  const request = {
    method: 'POST',
    headers: payload ? { 'Content-Type': 'application/json' } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  };

  fetch(`${API}${url}`, request)
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      function pump() {
        reader.read().then(({ done, value }) => {
          if (done) {
            disableRunButtons(false);
            return;
          }

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();
          lines.forEach(line => {
            if (!line.startsWith('data: ')) return;
            try {
              const event = JSON.parse(line.slice(6));
              handleEvent(event.type, event.data || {});
            } catch (_) { }
          });
          pump();
        }).catch(error => {
          handleEvent('error', { message: String(error) });
          disableRunButtons(false);
        });
      }

      pump();
    })
    .catch(error => {
      handleEvent('error', { message: String(error) });
      disableRunButtons(false);
    });
}

function disableRunButtons(disabled) {
  const mapping = [
    ['btnRun', disabled ? 'Running…' : 'Execute Workflow'],
    ['btnRunMeeting', disabled ? 'Running…' : 'Process Meeting'],
    ['btnRunSLA', disabled ? 'Running…' : 'Run SLA Response'],
    ['btnRunDemo', disabled ? 'Running…' : 'Run Workflow'],
  ];
  mapping.forEach(([id, label]) => {
    const node = document.getElementById(id);
    if (!node) return;
    node.disabled = disabled;
    node.textContent = label;
  });
}

function handleEvent(type, data) {
  logEvent(type, data);

  switch (type) {
    case 'plan_created':
      state.activeRunId = data.run_id;
      document.getElementById('runIdDisplay').textContent = `run ${data.run_id.slice(0, 8)} · ${data.integration_mode}`;
      setAgentState(AGENT_MAP.orchestrator_agent, 'done', 'planned');
      setAgentState(AGENT_MAP.audit_agent, 'active', 'logging');
      break;

    case 'step_started':
      setAgentState(AGENT_MAP.execution_agents, 'active', 'executing');
      setStepState(data.step_name, 'running', data.attempt || 1, `Executing ${humanizeStep(data.step_name)}.`);
      break;

    case 'step_executed':
      if (data.status === 'failed') {
        setAgentState(AGENT_MAP.failure_detection_agent, 'active', 'analyzing');
        state.liveMetrics.failures += 1;
        renderMetrics();
      }
      break;

    case 'step_success':
      state.liveMetrics.successes += 1;
      setStepState(data.step_name, 'success', 0, `${humanizeStep(data.step_name)} completed.`);
      setAgentState(AGENT_MAP.failure_detection_agent, 'done', 'clear');
      renderMetrics();
      break;

    case 'step_failed':
      setStepState(data.step_name, 'failed', 1, data.diagnosis?.reasoning || `${humanizeStep(data.step_name)} failed.`);
      setAgentState(AGENT_MAP.failure_detection_agent, 'alert', 'failure');
      break;

    case 'step_retry':
      state.liveMetrics.retries += 1;
      setStepState(data.step_name, 'retrying', data.attempt, `Recovery attempt ${data.attempt} in progress.`);
      setAgentState(AGENT_MAP.recovery_agent, 'active', `retry ${data.attempt}`);
      renderMetrics();
      break;

    case 'strategy_generated':
      setAgentState(AGENT_MAP.strategy_agent, 'active', 'adapting');
      addStrategyCard(data);
      break;

    case 'recovery_attempted':
      if (data.recovered) {
        state.liveMetrics.successes += 1;
        setAgentState(AGENT_MAP.recovery_agent, 'done', 'recovered');
        setStepState(data.step_name, 'success', data.retry_count, data.reasoning || 'Recovered successfully.');
      } else {
        setAgentState(AGENT_MAP.recovery_agent, 'done', 'escalated');
        setStepState(data.step_name, 'escalated', data.retry_count, data.reasoning || 'Recovery exhausted.');
      }
      renderMetrics();
      break;

    case 'escalation_created':
      state.liveMetrics.escalations += 1;
      if (data.step_name) {
        setStepState(data.step_name, 'escalated', 0, data.reason || 'Escalated for manual intervention.');
      }
      renderMetrics();
      break;

    case 'clarification_needed':
      setAgentState(AGENT_MAP.hitl_agent, 'alert', 'waiting');
      setStepState(data.step_name, 'waiting', 0, data.question || 'Waiting for clarification.');
      showHITL(data);
      break;

    case 'clarification_received':
    case 'clarification_timeout':
      hideHITL();
      break;

    case 'integration_delivery':
      addIntegrationCard(data);
      break;

    case 'run_completed':
      renderMetrics(data.metrics || {});
      renderResults(data);
      setEngineStatus('success', data.status === 'completed_with_escalation' ? 'Completed with escalation' : 'Completed');
      break;

    case 'strategy_evolved':
      setAgentState(AGENT_MAP.evolution_agent, 'done', 'evolved');
      break;

    case 'audit_exported':
      setAgentState(AGENT_MAP.audit_agent, 'done', 'exported');
      if (data.run_id) loadAudit(data.run_id, 'live');
      break;

    case 'ai_reasoning':
      addReasoningCard(data);
      break;

    case 'done':
      setEngineStatus('success', 'Done');
      disableRunButtons(false);
      break;

    case 'error':
      setEngineStatus('error', 'Error');
      disableRunButtons(false);
      break;

    default:
      break;
  }
}

function logEvent(type, data) {
  if (type === 'heartbeat' || type === 'ai_reasoning') return;
  const log = document.getElementById('eventLog');
  if (state.logEmpty) {
    log.innerHTML = '';
    state.logEmpty = false;
  }
  const row = document.createElement('div');
  const tone = eventTone(type);
  row.className = 'event-row';
  row.innerHTML = `
    <div class="event-time">${formatTime(new Date().toISOString())}</div>
    <div class="event-tag ${tone}">${escHtml(type.replace(/_/g, ' '))}</div>
    <div class="event-copy">${escHtml(buildLogMessage(type, data))}</div>
  `;
  log.appendChild(row);
  animateEntry(row);
  log.scrollTop = log.scrollHeight;
}

function eventTone(type) {
  if (['step_success', 'run_completed', 'done'].includes(type)) return 'success';
  if (['step_failed', 'error'].includes(type)) return 'failure';
  if (['step_retry', 'recovery_attempted', 'clarification_needed'].includes(type)) return 'warning';
  if (['integration_delivery', 'strategy_generated', 'audit_exported', 'plan_created'].includes(type)) return 'info';
  return 'neutral';
}

function buildLogMessage(type, data) {
  switch (type) {
    case 'plan_created':
      return `Plan ready with ${data.plan?.length || 0} steps for ${data.workflow_type}.`;
    case 'step_started':
      return `Started ${humanizeStep(data.step_name)}.`;
    case 'step_executed':
      return `${humanizeStep(data.step_name)} returned ${data.status}${data.error_code ? ` (${data.error_code})` : ''}.`;
    case 'step_success':
      return `${humanizeStep(data.step_name)} completed successfully.`;
    case 'step_failed':
      return `${humanizeStep(data.step_name)} failed: ${data.error_code || 'unknown error'}.`;
    case 'step_retry':
      return `Retrying ${humanizeStep(data.step_name)} at attempt ${data.attempt}.`;
    case 'recovery_attempted':
      return `${humanizeStep(data.step_name)} recovery finished. recovered=${String(data.recovered)}.`;
    case 'escalation_created':
      return `Escalation sent to ${data.target || 'ops'} for ${data.step_name || 'workflow'}.`;
    case 'integration_delivery':
      return `${capitalize(data.provider || 'integration')} ${data.delivery || 'recorded'} for ${data.notification_type || 'event'}.`;
    case 'strategy_generated':
      return `Adaptive strategy "${data.strategy_name || 'default'}" generated for ${data.step_name}.`;
    case 'run_completed':
      return `Run finished with status ${data.status}.`;
    case 'strategy_evolved':
      return 'Global strategy evolved from the latest run outcomes.';
    case 'audit_exported':
      return `Audit exported to ${data.audit_file}.`;
    case 'clarification_needed':
      return `Human clarification requested for ${data.step_name}.`;
    case 'clarification_received':
      return `Clarification received: ${data.answer}.`;
    case 'clarification_timeout':
      return `Clarification timed out for ${data.step_name}.`;
    case 'done':
      return 'Stream completed.';
    case 'error':
      return `Execution error: ${data.message}.`;
    default:
      return type;
  }
}

function addReasoningCard(data) {
  const panel = document.getElementById('reasoningLog');
  if (state.reasoningEmpty) {
    panel.innerHTML = '';
    state.reasoningEmpty = false;
  }
  state.reasoningCount += 1;
  document.getElementById('reasoningCount').textContent = `${state.reasoningCount} decision${state.reasoningCount === 1 ? '' : 's'}`;
  const confidence = Math.round((data.confidence || 0.5) * 100);
  const card = document.createElement('details');
  card.className = `reasoning-card ${(data.decision === 'escalate' || data.decision === 'escalated') ? 'warn' : ''}`;
  card.open = state.reasoningCount <= 2;
  card.innerHTML = `
    <summary>
      <div class="reasoning-topline">
        <span class="reasoning-agent">${escHtml(AGENT_LABELS[data.agent] || data.agent || 'Agent')}</span>
        ${data.step_name ? `<span class="reasoning-step">${escHtml(data.step_name)}</span>` : ''}
        <span class="status-chip muted">${escHtml(DECISION_ICONS[data.decision] || data.decision || 'Decision')}</span>
        <span class="status-chip ${confidence >= 75 ? 'good' : confidence >= 55 ? 'warn' : 'offline'} reasoning-confidence">${confidence}%</span>
      </div>
    </summary>
    <div class="reasoning-copy">
      <pre class="reasoning-code">${formatReasoningCode(data.reasoning || '')}</pre>
      ${data.severity ? `<p class="audit-meta">Severity: ${escHtml(data.severity)}</p>` : ''}
    </div>
  `;
  panel.appendChild(card);
  animateEntry(card);
  panel.scrollTop = panel.scrollHeight;
}

function addStrategyCard(data) {
  addReasoningCard({
    agent: 'strategy_agent',
    step_name: data.step_name,
    decision: 'retry',
    reasoning: `${data.justification || ''} Retry policy: max_retries=${data.retry_policy?.max_retries ?? '—'}, backoff=${(data.retry_policy?.backoff || []).join(', ') || '—'}.`,
    confidence: data.confidence,
  });
}

function addIntegrationCard(receipt) {
  const panel = document.getElementById('integrationFeed');
  if (state.integrationEmpty) {
    panel.innerHTML = '';
    state.integrationEmpty = false;
  }
  const card = document.createElement('article');
  card.className = 'integration-card';
  const deliveryTone = receipt.delivery === 'sent'
    ? 'good'
    : receipt.delivery === 'simulated'
      ? 'warn'
      : receipt.delivery === 'fallback_simulated'
        ? 'warn'
        : 'offline';

  card.innerHTML = `
    <div class="integration-topline">
      <strong>${escHtml(capitalize(receipt.provider || 'integration'))}</strong>
      <span class="status-chip ${deliveryTone}">${escHtml(receipt.delivery || 'unknown')}</span>
      <span class="status-chip muted">${escHtml(receipt.notification_type || 'event')}</span>
    </div>
    <div class="integration-meta">
      ${receipt.workflow_type ? `<div>Workflow: ${escHtml(receipt.workflow_type)}</div>` : ''}
      ${receipt.step_name ? `<div>Step: ${escHtml(receipt.step_name)}</div>` : ''}
      ${receipt.run_id ? `<div>Run: <code>${escHtml(receipt.run_id)}</code></div>` : ''}
      ${receipt.error ? `<div>Error: ${escHtml(receipt.error)}</div>` : ''}
    </div>
  `;
  panel.appendChild(card);
  animateEntry(card);
  panel.scrollTop = panel.scrollHeight;
}

function formatReasoningCode(reasoning) {
  const escaped = escHtml(reasoning || '');
  return escaped
    .replace(/\b(retry|recover|continue|escalate|failed|success|critical|severity|timeout|fallback)\b/gi, '<span class="reasoning-key">$1</span>')
    .replace(/\b(\d+(?:\.\d+)?%?)\b/g, '<span class="reasoning-num">$1</span>');
}

function renderResults(data) {
  const metrics = data.metrics || {};
  const impact = data.impact || {};
  const resultsGrid = document.getElementById('resultsGrid');
  const impactGrid = document.getElementById('impactGrid');

  const summaryItems = [
    { label: 'Status', value: data.status || '—' },
    { label: 'Step events', value: metrics.total_step_events ?? '—' },
    { label: 'Escalations', value: metrics.escalation_count ?? '—' },
    { label: 'Runtime', value: metrics.total_execution_time_secs != null ? `${metrics.total_execution_time_secs}s` : '—' },
  ];

  resultsGrid.innerHTML = summaryItems.map(item => `
    <div class="summary-cell">
      <div class="summary-value">${escHtml(String(item.value))}</div>
      <div class="summary-label">${escHtml(item.label)}</div>
    </div>
  `).join('');

  impactGrid.innerHTML = getImpactMetrics(state.activeWorkflow, impact).map(item => `
    <div class="impact-cell">
      <div class="impact-value">${escHtml(item.value)}</div>
      <div class="impact-label">${escHtml(item.label)}</div>
      <div class="impact-sub">${escHtml(item.sub)}</div>
    </div>
  `).join('') || '<div class="empty-state compact">No impact model available for this workflow.</div>';
}

function getImpactMetrics(workflowType, impact) {
  if (workflowType === 'employee_onboarding') {
    return [
      { label: 'Time saved / run', value: `${impact.time_saved_hours_per_run ?? 0}h`, sub: 'Compared with manual onboarding' },
      { label: 'Cost saved / run', value: `$${Number(impact.cost_saved_per_run_usd ?? 0).toLocaleString()}`, sub: 'Includes remediation avoided' },
      { label: 'Monthly savings', value: `$${Number(impact.monthly_cost_savings_usd ?? 0).toLocaleString()}`, sub: 'At current onboarding volume' },
      { label: 'Ramp-up gain', value: `${impact.time_to_productive_improvement_days ?? 0} days`, sub: 'Faster time to productivity' },
    ];
  }
  if (workflowType === 'meeting_action') {
    return [
      { label: 'Time saved / meeting', value: `${impact.time_saved_hours_per_meeting ?? 0}h`, sub: 'Minutes and follow-up reduced' },
      { label: 'Monthly time saved', value: `${impact.monthly_time_savings_hours ?? 0}h`, sub: 'At current meeting volume' },
      { label: 'Revenue protected', value: `$${Number(impact.monthly_revenue_at_risk_protected_usd ?? 0).toLocaleString()}`, sub: 'Prevented follow-up drop-off' },
      { label: 'Action items captured', value: `${impact.action_items_captured ?? 0}`, sub: 'Detected in the current run' },
    ];
  }
  if (workflowType === 'sla_breach') {
    return [
      { label: 'Penalties avoided', value: `$${Number(impact.penalties_avoided_per_month_usd ?? 0).toLocaleString()}`, sub: 'Monthly estimate' },
      { label: 'Firefighting saved', value: `${impact.monthly_firefighting_hours_saved ?? 0}h`, sub: 'Operational effort reduced' },
      { label: 'Total value', value: `$${Number(impact.total_monthly_value_usd ?? 0).toLocaleString()}`, sub: 'Protected monthly value' },
      { label: 'Response acceleration', value: `${impact.time_saved_per_breach_hours ?? 0}h`, sub: 'Faster than manual escalation' },
    ];
  }
  return [];
}

async function loadAudit(runId, target) {
  const audit = await fetch(`${API}/api/audit/${runId}`).then(response => response.json());
  const events = Array.isArray(audit) ? audit : audit.events || [];
  const integrity = Array.isArray(audit) ? {} : audit.integrity || {};
  renderAuditViewer(events, integrity, target);
}

function renderAuditViewer(events, integrity, target) {
  const summaryId = target === 'history' ? 'historyAuditSummary' : 'liveAuditSummary';
  const eventsId = target === 'history' ? 'historyAuditEvents' : 'liveAuditEvents';
  const badgeId = target === 'history' ? 'historyAuditBadge' : 'auditIntegrityBadge';
  const titleId = target === 'history' ? 'historyAuditTitle' : null;

  if (titleId && events[0]?.run_id) {
    document.getElementById(titleId).textContent = `Run ${events[0].run_id.slice(0, 8)}`;
  }

  const badge = document.getElementById(badgeId);
  if (integrity.verified) {
    badge.textContent = 'Chain verified';
    badge.className = 'audit-status good';
  } else if (events.length) {
    badge.textContent = 'Chain unverified';
    badge.className = 'audit-status bad';
  } else {
    badge.textContent = 'No audit loaded';
    badge.className = 'audit-status pending';
  }

  const summary = document.getElementById(summaryId);
  summary.innerHTML = events.length ? `
    <div class="audit-summary-grid">
      <div class="summary-cell">
        <div class="summary-value">${integrity.chain_length ?? events.length}</div>
        <div class="summary-label">Events</div>
      </div>
      <div class="summary-cell">
        <div class="summary-value">${integrity.algorithm || 'sha256'}</div>
        <div class="summary-label">Integrity algorithm</div>
      </div>
      <div class="summary-cell">
        <div class="summary-value">${escHtml((integrity.final_hash || 'n/a').slice(0, 12))}</div>
        <div class="summary-label">Final hash prefix</div>
      </div>
    </div>
  ` : '<div class="empty-state compact">No audit events available.</div>';

  const list = document.getElementById(eventsId);
  list.innerHTML = events.map(event => `
    <details class="audit-item">
      <summary>
        <div>
          <div class="audit-action">${escHtml(event.action || 'event')}</div>
          <div class="audit-meta">${escHtml(event.actor || 'system')} · ${escHtml(formatTime(event.timestamp))}</div>
        </div>
        <span class="status-chip muted">#${escHtml(String(event.sequence ?? '0'))}</span>
      </summary>
      <div class="audit-body">
        <pre class="audit-payload">${escHtml(JSON.stringify(event.payload, null, 2))}</pre>
      </div>
    </details>
  `).join('');
}

async function loadHistory() {
  try {
    const data = await fetch(`${API}/api/history`).then(response => response.json());
    const list = document.getElementById('historyList');
    if (!data.runs?.length) {
      list.innerHTML = '<div class="empty-state">No runs yet.</div>';
      return;
    }

    list.innerHTML = data.runs.map(run => `
      <article class="history-item" data-run-id="${escHtml(run.run_id)}">
        <div class="history-item-header">
          <span class="wf-tag">${escHtml((run.workflow_type || 'workflow').replace(/_/g, ' '))}</span>
          <span class="history-run-id"><code>${escHtml(run.run_id.slice(0, 8))}</code></span>
          <span class="history-time">${escHtml(formatTime(run.timestamp))}</span>
          <span class="ai-pill">${escHtml(String(run.ai_decisions || 0))} AI decisions</span>
        </div>
        <div class="history-metrics">
          <span class="history-pill">steps ${escHtml(String(run.metrics?.distinct_steps ?? '—'))}</span>
          <span class="history-pill ${run.metrics?.failed_events ? 'failure' : ''}">failures ${escHtml(String(run.metrics?.failed_events ?? '—'))}</span>
          <span class="history-pill">escalations ${escHtml(String(run.metrics?.escalation_count ?? '—'))}</span>
          ${formatImpactSummary(run.workflow_type, run.impact) ? `<span class="history-pill impact">${escHtml(formatImpactSummary(run.workflow_type, run.impact))}</span>` : ''}
        </div>
      </article>
    `).join('');

    list.querySelectorAll('.history-item').forEach(item => {
      enablePressFeedback(item);
      item.addEventListener('click', () => loadAudit(item.dataset.runId, 'history'));
    });
  } catch (error) {
    document.getElementById('historyList').innerHTML = `<div class="empty-state">Failed to load history: ${escHtml(error.message)}</div>`;
  }
}

function formatImpactSummary(workflowType, impact) {
  if (!impact || !Object.keys(impact).length) return '';
  if (workflowType === 'employee_onboarding' && impact.monthly_cost_savings_usd != null) {
    return `$${Number(impact.monthly_cost_savings_usd).toLocaleString()} / month`;
  }
  if (workflowType === 'meeting_action' && impact.action_items_captured != null) {
    return `${impact.action_items_captured} action items`;
  }
  if (workflowType === 'sla_breach' && impact.total_monthly_value_usd != null) {
    return `$${Number(impact.total_monthly_value_usd).toLocaleString()} protected`;
  }
  return '';
}

async function loadLearning() {
  try {
    const learning = await fetch(`${API}/api/learning`).then(response => response.json());
    const history = await fetch(`${API}/api/strategy-history`).then(response => response.json());
    renderLearning(learning);
    renderStrategyTimeline(history);
  } catch (error) {
    document.getElementById('learningGrid').innerHTML = `<div class="empty-state">Failed to load learning: ${escHtml(error.message)}</div>`;
  }
}

function renderLearning(memory) {
  const strategy = memory.strategy?.jira || {};
  const cards = [
    { label: 'Total runs', value: memory.total_runs ?? 0, note: 'Persisted adaptive memory' },
    { label: 'Max retries', value: strategy.max_retries ?? '—', note: 'Current Jira policy' },
    { label: 'Precheck', value: strategy.precheck_enabled ? 'Enabled' : 'Disabled', note: 'Before retry' },
    { label: 'Backoff', value: `${strategy.backoff_multiplier ?? '—'}x`, note: 'Retry spacing factor' },
  ];

  const grid = document.getElementById('learningGrid');
  grid.innerHTML = cards.map(card => `
    <article class="learn-cell">
      <div class="learn-value">${escHtml(String(card.value))}</div>
      <div class="learn-label">${escHtml(card.label)}</div>
      <div class="learn-note">${escHtml(card.note)}</div>
    </article>
  `).join('');

  const stats = memory.step_stats || {};
  const stepNames = Object.keys(stats);
  if (stepNames.length) {
    const table = document.createElement('div');
    table.className = 'reliability-table';
    stepNames.forEach(step => {
      const entry = stats[step];
      const total = (entry.success || 0) + (entry.failed || 0);
      const rate = total ? Math.round((entry.success / total) * 100) : 100;
      const tone = rate >= 90 ? '' : rate >= 60 ? 'warn' : 'bad';
      const row = document.createElement('div');
      row.className = 'rel-row';
      row.innerHTML = `
        <div class="rel-name">${escHtml(step)}</div>
        <div class="rel-bar">
          <div class="rel-fill ${tone}" style="width:${rate}%"></div>
        </div>
        <div>${rate}%</div>
        <div>${escHtml(String(entry.success || 0))}✓ ${escHtml(String(entry.failed || 0))}✗</div>
      `;
      table.appendChild(row);
    });
    grid.appendChild(table);
  }
}

function renderStrategyTimeline(history) {
  const container = document.getElementById('strategyTimeline');
  const entries = history.strategy_history || [];
  if (!entries.length) {
    container.innerHTML = '<div class="empty-state">Timeline will populate after multiple runs.</div>';
    return;
  }

  container.innerHTML = entries.slice(-10).reverse().map(entry => `
    <article class="timeline-entry">
      <div class="timeline-header">
        <strong>Run ${escHtml(String(entry.run_number || '—'))}</strong>
        <span class="status-chip ${entry.ai_generated ? 'good' : 'warn'}">${entry.ai_generated ? 'AI' : 'Deterministic'}</span>
      </div>
      <div class="timeline-reasoning">Jira failure rate ${Math.round((entry.jira_failure_rate || 0) * 100)}% · max_retries ${entry.strategy?.jira?.max_retries ?? '—'}</div>
      ${entry.reasoning ? `<div class="audit-meta">${escHtml(entry.reasoning)}</div>` : ''}
    </article>
  `).join('');
}

function setEngineStatus(stateClass, label) {
  const dot = document.getElementById('engineStatus');
  dot.className = `engine-dot ${stateClass}`.trim();
  document.getElementById('engineStatusLabel').textContent = label;
}

function showHITL(data) {
  document.getElementById('hitlOverlay').style.display = 'flex';
  document.getElementById('hitlStepName').textContent = data.step_name || '';
  document.getElementById('hitlQuestion').textContent = data.question || '';
  document.getElementById('hitlAnswer').value = '';
  const options = document.getElementById('hitlOptions');
  options.innerHTML = '';
  (data.options || []).forEach(option => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = option;
    button.addEventListener('click', () => {
      document.getElementById('hitlAnswer').value = option;
    });
    options.appendChild(button);
  });

  let remaining = data.timeout_seconds || 300;
  clearInterval(state.hitlTimerInterval);
  state.hitlTimerInterval = setInterval(() => {
    remaining -= 1;
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    document.getElementById('hitlTimer').textContent = `${minutes}:${String(seconds).padStart(2, '0')} remaining before auto-escalation`;
    if (remaining <= 0) hideHITL();
  }, 1000);
}

function hideHITL() {
  document.getElementById('hitlOverlay').style.display = 'none';
  clearInterval(state.hitlTimerInterval);
  setAgentState(AGENT_MAP.hitl_agent, '', 'standby');
}

async function submitHITLAnswer() {
  const answer = document.getElementById('hitlAnswer').value.trim();
  if (!answer || !state.activeRunId) return;
  try {
    await fetch(`${API}/api/clarify/${state.activeRunId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    hideHITL();
    setAgentState(AGENT_MAP.hitl_agent, 'done', 'answered');
  } catch (error) {
    logEvent('error', { message: error.message });
  }
}

function humanizeStep(stepName) {
  const match = (WORKFLOW_STEPS[state.activeWorkflow] || []).find(step => step.key === stepName);
  return match ? match.label : (stepName || '').replace(/_/g, ' ');
}

function formatTime(timestamp) {
  if (!timestamp) return '';
  try {
    return new Date(timestamp).toLocaleTimeString('en-US', { hour12: false });
  } catch (_) {
    return String(timestamp);
  }
}

function capitalize(value) {
  const text = String(value || '');
  if (!text) return text;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function escHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
