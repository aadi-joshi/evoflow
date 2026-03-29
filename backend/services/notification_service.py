"""
Notification Service — Email notification with simulated/real delivery.

When SMTP_HOST environment variable is set:
  - Sends real emails via SMTP
Otherwise:
  - Logs as "simulated delivery" to the audit trail

Used by the workflow engine for welcome emails, escalation notices, etc.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.utils.env import load_env
from backend.utils.security import sanitize_for_audit

logger = logging.getLogger(__name__)

load_env()


class NotificationService:
    """Handles email notifications with real or simulated delivery."""

    def __init__(self) -> None:
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_pass = os.getenv("SMTP_PASS", "")
        self.from_addr = os.getenv("SMTP_FROM", "evoflow@company.com")
        self.delivery_log: list[Dict[str, Any]] = []

    def is_configured(self) -> bool:
        return bool(self.smtp_host)

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        cc: Optional[str] = None,
        integration_mode: str = "simulation",
        allow_fallback: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Send an email notification.

        Returns a delivery receipt dict.
        """
        receipt = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "to":        to,
            "cc":        cc,
            "subject":   subject,
            "body":      body[:500],  # truncate for audit
            "html_preview": (html_body or "")[:500],
            "from":      self.from_addr,
            "provider":  "smtp",
            "mode":      integration_mode,
            "metadata":  sanitize_for_audit(metadata or {}),
        }

        if integration_mode == "real" and self.smtp_host:
            try:
                receipt.update(self._send_real(to, subject, body, html_body, cc))
            except Exception as exc:
                receipt["delivery"] = "fallback_simulated" if allow_fallback else "failed"
                receipt["error"] = str(exc)
                logger.error(f"SMTP delivery failed: {exc}")
        elif integration_mode == "real" and not self.smtp_host:
            receipt["delivery"] = "fallback_simulated" if allow_fallback else "failed"
            receipt["message"] = "SMTP not configured. Email delivery simulated."
        else:
            receipt["delivery"] = "simulated"
            receipt["message"] = (
                f"Email to {to} simulated (real delivery disabled). "
                f"Subject: {subject}"
            )
            logger.info(f"SIMULATED EMAIL → {to}: {subject}")

        self.delivery_log.append(receipt)
        return receipt

    def send_escalation_notice(
        self,
        target: str,
        step_name: str,
        reason: str,
        run_id: str,
        workflow_name: str = "employee_onboarding",
        severity: str = "high",
        integration_mode: str = "simulation",
    ) -> Dict[str, Any]:
        """Send an escalation email to the ops team."""
        subject = f"[EvoFlow Escalation] {step_name} requires manual intervention"
        body = (
            f"Workflow run {run_id} has escalated step '{step_name}'.\n\n"
            f"Reason: {reason}\n\n"
            f"Workflow: {workflow_name}\n"
            f"Severity: {severity}\n\n"
            f"Please review and resolve in the EvoFlow dashboard.\n"
            f"— EvoFlow AI Autonomous Agent"
        )
        html = self._render_escalation_email(
            workflow_name=workflow_name,
            step_name=step_name,
            reason=reason,
            run_id=run_id,
            severity=severity,
        )
        return self.send_email(
            target,
            subject,
            body,
            html_body=html,
            integration_mode=integration_mode,
            metadata={
                "notification_type": "escalation_email",
                "workflow_type": workflow_name,
                "step_name": step_name,
                "run_id": run_id,
                "severity": severity,
            },
        )

    def send_welcome_email(
        self,
        employee_email: str,
        employee_name: str,
        department: str,
        integration_mode: str = "simulation",
    ) -> Dict[str, Any]:
        """Send a welcome email to a new hire."""
        subject = f"Welcome to the team, {employee_name}!"
        body = (
            f"Hi {employee_name},\n\n"
            f"Welcome to the {department} team! Your accounts have been "
            f"provisioned and you're all set to get started.\n\n"
            f"Here's what's been set up for you:\n"
            f"• Email account\n"
            f"• Slack workspace access\n"
            f"• Orientation meetings scheduled\n\n"
            f"Your buddy will reach out shortly. Looking forward to working with you!\n\n"
            f"— EvoFlow AI Onboarding System"
        )
        html = self._render_welcome_email(employee_name, department)
        return self.send_email(
            employee_email,
            subject,
            body,
            html_body=html,
            integration_mode=integration_mode,
            metadata={
                "notification_type": "welcome_email",
                "workflow_type": "employee_onboarding",
                "step_name": "send_welcome_email",
                "department": department,
            },
        )

    def _send_real(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str],
        cc: Optional[str],
    ) -> Dict[str, Any]:
        """Actually send via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            if self.smtp_user:
                server.login(self.smtp_user, self.smtp_pass)
            recipients = [to]
            if cc:
                recipients.append(cc)
            server.sendmail(self.from_addr, recipients, msg.as_string())

        return {"delivery": "sent", "smtp_host": self.smtp_host}

    def _render_welcome_email(self, employee_name: str, department: str) -> str:
        content = (
            f"<p style='margin:0 0 16px;'>Hi {employee_name},</p>"
            f"<p style='margin:0 0 16px;'>Welcome to the {department} team. EvoFlow has completed "
            "your onboarding workflow and prepared your initial access so you can start smoothly.</p>"
            "<div style='background:#FFFFFF;border-radius:12px;padding:18px 20px;margin:24px 0;'>"
            "<p style='margin:0 0 8px;font-weight:600;color:#1E293B;'>Ready for day one</p>"
            "<p style='margin:0;color:#475569;'>Email, Slack access, orientation scheduling, and your onboarding sequence are in motion.</p>"
            "</div>"
            "<p style='margin:0;'>Your onboarding buddy will reach out shortly.</p>"
        )
        return self._wrap_template("Welcome to EvoFlow", content, "Onboarding completed successfully")

    def _render_escalation_email(
        self,
        workflow_name: str,
        step_name: str,
        reason: str,
        run_id: str,
        severity: str,
    ) -> str:
        content = (
            "<p style='margin:0 0 16px;'>EvoFlow created a manual escalation that needs review.</p>"
            "<div style='background:#FFFFFF;border-radius:12px;padding:18px 20px;margin:24px 0;'>"
            f"<p style='margin:0 0 8px;'><strong>Workflow:</strong> {workflow_name}</p>"
            f"<p style='margin:0 0 8px;'><strong>Step:</strong> {step_name}</p>"
            f"<p style='margin:0 0 8px;'><strong>Severity:</strong> {severity}</p>"
            f"<p style='margin:0;'><strong>Run ID:</strong> <code>{run_id}</code></p>"
            "</div>"
            f"<p style='margin:0 0 12px;'><strong>Reason</strong></p>"
            f"<p style='margin:0;color:#475569;'>{reason}</p>"
        )
        return self._wrap_template("Manual Escalation Required", content, "Ops review requested")

    @staticmethod
    def _wrap_template(title: str, content: str, eyebrow: str) -> str:
        return f"""\
<!DOCTYPE html>
<html lang="en">
  <body style="margin:0;padding:0;background:#FAF9F6;color:#1E293B;font-family:Inter,Segoe UI,Arial,sans-serif;">
    <div style="max-width:640px;margin:0 auto;padding:32px 20px 48px;">
      <div style="background:#FFFFFF;border-radius:18px;box-shadow:0 18px 45px rgba(15,23,42,0.08);overflow:hidden;">
        <div style="padding:28px 32px;background:#E0E7FF;border-bottom:1px solid rgba(37,99,235,0.12);">
          <div style="font-size:12px;letter-spacing:0.12em;text-transform:uppercase;color:#2563EB;font-weight:700;">{eyebrow}</div>
          <h1 style="margin:10px 0 0;font-size:28px;line-height:1.15;">{title}</h1>
        </div>
        <div style="padding:28px 32px;font-size:15px;line-height:1.7;color:#1E293B;">
          {content}
        </div>
      </div>
    </div>
  </body>
</html>
"""
