"""
Real External API Integrations — EvoFlow AI.

Implements:
  1. Slack   — Incoming Webhook (no OAuth scopes needed for demo)
  2. Email   — SMTP via smtplib (works with Gmail/SendGrid/Mailtrap sandbox)

All functions return a structured IntegrationResult with:
  - success: bool
  - provider: str
  - response_metadata: dict (status codes, message IDs, latency)
  - error_code: str | None
  - error_detail: str | None

Configuration (in .env):
  SLACK_WEBHOOK_URL     — e.g. https://hooks.slack.com/services/T.../B.../...
  SMTP_HOST             — e.g. smtp.gmail.com  or  smtp.mailtrap.io
  SMTP_PORT             — e.g. 587
  SMTP_USERNAME         — your email / Mailtrap username
  SMTP_PASSWORD         — app password / Mailtrap password
  SMTP_FROM             — sender address
  INTEGRATION_ENABLED   — "true" to actually call APIs (default: false = simulation)
"""
from __future__ import annotations

import json
import os
import smtplib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional


# ── Config ────────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

SLACK_WEBHOOK_URL   = _env("SLACK_WEBHOOK_URL")
SMTP_HOST           = _env("SMTP_HOST", "smtp.mailtrap.io")
SMTP_PORT           = int(_env("SMTP_PORT", "587"))
SMTP_USERNAME       = _env("SMTP_USERNAME")
SMTP_PASSWORD       = _env("SMTP_PASSWORD")
SMTP_FROM           = _env("SMTP_FROM", "evoflow@demo.ai")
INTEGRATION_ENABLED = _env("INTEGRATION_ENABLED", "false").lower() == "true"


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class IntegrationResult:
    success:           bool
    provider:          str
    response_metadata: Dict[str, Any] = field(default_factory=dict)
    error_code:        Optional[str]  = None
    error_detail:      Optional[str]  = None
    latency_ms:        int            = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Slack ─────────────────────────────────────────────────────────────────────

def send_slack_notification(
    message: str,
    channel: str = "#evoflow-alerts",
    username: str = "EvoFlow AI",
    blocks: Optional[list] = None,
) -> IntegrationResult:
    """
    Send a message via Slack Incoming Webhook.

    Falls back to simulation if SLACK_WEBHOOK_URL is not set or
    INTEGRATION_ENABLED=false.
    """
    if not INTEGRATION_ENABLED or not SLACK_WEBHOOK_URL:
        return _simulate_slack(message, channel)

    payload: Dict[str, Any] = {
        "text":     message,
        "username": username,
        "channel":  channel,
    }
    if blocks:
        payload["blocks"] = blocks

    start = time.perf_counter()
    try:
        data    = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            latency_ms = int((time.perf_counter() - start) * 1000)
            body = response.read().decode("utf-8")
            return IntegrationResult(
                success=True,
                provider="slack",
                response_metadata={
                    "http_status": response.status,
                    "body":        body,
                    "channel":     channel,
                    "webhook_url": SLACK_WEBHOOK_URL[:40] + "...",
                },
                latency_ms=latency_ms,
            )
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        body = exc.read().decode("utf-8") if exc.fp else ""
        code = "SLACK_HTTP_ERROR"
        if exc.code == 400:
            code = "SLACK_INVALID_PAYLOAD"
        elif exc.code == 403:
            code = "SLACK_AUTH_FAILED"
        elif exc.code == 429:
            code = "SLACK_RATE_LIMITED"
        return IntegrationResult(
            success=False,
            provider="slack",
            error_code=code,
            error_detail=f"HTTP {exc.code}: {body}",
            latency_ms=latency_ms,
            response_metadata={"http_status": exc.code},
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return IntegrationResult(
            success=False,
            provider="slack",
            error_code="SLACK_CONNECTION_ERROR",
            error_detail=str(exc),
            latency_ms=latency_ms,
        )


def _simulate_slack(message: str, channel: str) -> IntegrationResult:
    return IntegrationResult(
        success=True,
        provider="slack",
        response_metadata={
            "simulated":      True,
            "channel":        channel,
            "message_length": len(message),
            "note":           "Set SLACK_WEBHOOK_URL and INTEGRATION_ENABLED=true for real calls",
        },
        latency_ms=12,
    )


# ── Email (SMTP) ──────────────────────────────────────────────────────────────

def send_email(
    to: str | list[str],
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
) -> IntegrationResult:
    """
    Send an email via SMTP.

    Works with Gmail (app passwords), Mailtrap (sandbox), SendGrid SMTP relay.
    Falls back to simulation if credentials are not set.
    """
    recipients = [to] if isinstance(to, str) else to

    if not INTEGRATION_ENABLED or not SMTP_USERNAME or not SMTP_PASSWORD:
        return _simulate_email(recipients, subject)

    start = time.perf_counter()
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = ", ".join(recipients)

        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            refused = server.sendmail(SMTP_FROM, recipients, msg.as_string())

        latency_ms = int((time.perf_counter() - start) * 1000)
        return IntegrationResult(
            success=True,
            provider="smtp",
            response_metadata={
                "host":       SMTP_HOST,
                "port":       SMTP_PORT,
                "from":       SMTP_FROM,
                "to":         recipients,
                "subject":    subject,
                "refused":    refused,   # {addr: (code, msg)} for refused recipients
            },
            latency_ms=latency_ms,
        )

    except smtplib.SMTPAuthenticationError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return IntegrationResult(
            success=False,
            provider="smtp",
            error_code="SMTP_AUTH_FAILED",
            error_detail=str(exc),
            latency_ms=latency_ms,
        )
    except smtplib.SMTPConnectError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return IntegrationResult(
            success=False,
            provider="smtp",
            error_code="SMTP_CONNECT_ERROR",
            error_detail=str(exc),
            latency_ms=latency_ms,
        )
    except smtplib.SMTPException as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return IntegrationResult(
            success=False,
            provider="smtp",
            error_code="SMTP_ERROR",
            error_detail=str(exc),
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return IntegrationResult(
            success=False,
            provider="smtp",
            error_code="EMAIL_DELIVERY_FAILED",
            error_detail=str(exc),
            latency_ms=latency_ms,
        )


def _simulate_email(recipients: list[str], subject: str) -> IntegrationResult:
    return IntegrationResult(
        success=True,
        provider="smtp",
        response_metadata={
            "simulated":    True,
            "recipients":   len(recipients),
            "subject":      subject,
            "note":         "Set SMTP_* vars and INTEGRATION_ENABLED=true for real sends",
        },
        latency_ms=8,
    )


# ── Convenience wrappers used by execution_agents ─────────────────────────────

def notify_slack_onboarding(employee_name: str, department: str) -> IntegrationResult:
    msg = (
        f":wave: *New employee onboarded via EvoFlow AI*\n"
        f">*Name:* {employee_name}\n"
        f">*Department:* {department}\n"
        f">*Status:* All systems provisioned ✅"
    )
    return send_slack_notification(msg, channel="#hr-onboarding")


def send_welcome_email_real(
    to_email: str,
    employee_name: str,
    department: str,
    start_date: str,
) -> IntegrationResult:
    html = f"""
    <h2>Welcome to the team, {employee_name}!</h2>
    <p>Your accounts have been provisioned by <strong>EvoFlow AI</strong>.</p>
    <ul>
      <li>Department: {department}</li>
      <li>Start date: {start_date}</li>
    </ul>
    <p>Your orientation schedule will follow shortly.</p>
    <p style="color:#666;font-size:12px">Sent by EvoFlow AI — Autonomous Onboarding Engine</p>
    """
    text = (
        f"Welcome to the team, {employee_name}!\n\n"
        f"Department: {department}\n"
        f"Start date: {start_date}\n\n"
        f"Your orientation schedule will follow shortly."
    )
    return send_email(
        to=to_email,
        subject=f"Welcome aboard, {employee_name}!",
        body_html=html,
        body_text=text,
    )


def send_escalation_alert(
    escalation_target: str,
    step_name: str,
    error_code: str,
    run_id: str,
    severity: str = "high",
) -> IntegrationResult:
    """Send both Slack alert and email for escalations."""
    emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "🟠")
    slack_msg = (
        f"{emoji} *EvoFlow AI — Escalation Alert*\n"
        f">*Step:* `{step_name}`\n"
        f">*Error:* `{error_code}`\n"
        f">*Severity:* {severity.upper()}\n"
        f">*Run ID:* `{run_id[:8]}...`\n"
        f">*Action:* Manual intervention required"
    )
    slack_result = send_slack_notification(
        slack_msg, channel="#evoflow-escalations"
    )

    email_html = f"""
    <h3>{emoji} EvoFlow AI — Escalation Required</h3>
    <table>
      <tr><td><b>Step</b></td><td>{step_name}</td></tr>
      <tr><td><b>Error</b></td><td>{error_code}</td></tr>
      <tr><td><b>Severity</b></td><td>{severity}</td></tr>
      <tr><td><b>Run ID</b></td><td>{run_id}</td></tr>
    </table>
    <p>Please log in to the EvoFlow dashboard to review and resolve.</p>
    """
    email_result = send_email(
        to=escalation_target,
        subject=f"[EvoFlow] Escalation: {step_name} — {error_code}",
        body_html=email_html,
    )

    # Return combined result — success only if both succeeded
    combined_ok = slack_result.success and email_result.success
    return IntegrationResult(
        success=combined_ok,
        provider="slack+smtp",
        response_metadata={
            "slack": slack_result.to_dict(),
            "email": email_result.to_dict(),
        },
        latency_ms=slack_result.latency_ms + email_result.latency_ms,
        error_code=None if combined_ok else (
            slack_result.error_code or email_result.error_code
        ),
    )
