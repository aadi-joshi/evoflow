"""
Slack Service — real delivery via Incoming Webhook or Bot API with safe audit receipts.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.utils.env import load_env
from backend.utils.security import mask_url, sanitize_for_audit

logger = logging.getLogger(__name__)

load_env()


class SlackService:
    def __init__(self) -> None:
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
        self.bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
        self.default_channel = os.getenv("SLACK_DEFAULT_CHANNEL", "").strip()
        self.timeout_seconds = float(os.getenv("SLACK_TIMEOUT_SECONDS", "10"))
        self.max_retries = int(os.getenv("SLACK_MAX_RETRIES", "3"))

    def is_configured(self) -> bool:
        return bool(self.webhook_url or self.bot_token)

    def send_message(
        self,
        channel: Optional[str],
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        integration_mode: str = "simulation",
        allow_fallback: bool = True,
    ) -> Dict[str, Any]:
        meta = metadata or {}
        payload = self._build_payload(channel, text, meta)
        receipt: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": "slack",
            "mode": integration_mode,
            "channel": channel or self.default_channel or "webhook-default",
            "notification_type": meta.get("notification_type", "generic"),
            "workflow_type": meta.get("workflow_type"),
            "step_name": meta.get("step_name"),
            "severity": meta.get("severity"),
            "run_id": meta.get("run_id"),
            "target": mask_url(self.webhook_url) if self.webhook_url else "slack-api",
            "text_preview": text[:180],
            "metadata": sanitize_for_audit(meta),
        }

        if integration_mode != "real":
            receipt["delivery"] = "simulated"
            receipt["message"] = "Slack integration disabled; simulated notification recorded."
            return receipt

        if not self.is_configured():
            receipt["delivery"] = "fallback_simulated" if allow_fallback else "failed"
            receipt["error"] = "Slack webhook or bot token not configured."
            return receipt

        try:
            if self.webhook_url:
                api_result = self._send_via_webhook(payload)
                receipt["transport"] = "incoming_webhook"
            else:
                api_result = self._send_via_bot(payload, channel or self.default_channel)
                receipt["transport"] = "bot_api"

            receipt["delivery"] = "sent"
            receipt.update(api_result)
            return receipt
        except Exception as exc:  # pragma: no cover - exercised in integration with live config
            logger.error("Slack delivery failed: %s", exc)
            receipt["error"] = str(exc)
            receipt["delivery"] = "fallback_simulated" if allow_fallback else "failed"
            return receipt

    def send_escalation_alert(
        self,
        workflow_type: str,
        step_name: str,
        reason: str,
        run_id: str,
        severity: str = "high",
        integration_mode: str = "simulation",
    ) -> Dict[str, Any]:
        return self.send_message(
            channel=None,
            text=f"EvoFlow escalation: {step_name} requires manual intervention.",
            metadata={
                "notification_type": "escalation",
                "status": "open",
                "workflow_type": workflow_type,
                "step_name": step_name,
                "failure_reason": reason,
                "run_id": run_id,
                "severity": severity,
            },
            integration_mode=integration_mode,
        )

    def send_critical_failure(
        self,
        workflow_type: str,
        step_name: str,
        reason: str,
        run_id: str,
        severity: str,
        integration_mode: str = "simulation",
    ) -> Dict[str, Any]:
        return self.send_message(
            channel=None,
            text=f"EvoFlow critical failure detected in {step_name}. Recovery may be required.",
            metadata={
                "notification_type": "critical_failure",
                "status": "investigating",
                "workflow_type": workflow_type,
                "step_name": step_name,
                "failure_reason": reason,
                "run_id": run_id,
                "severity": severity,
            },
            integration_mode=integration_mode,
        )

    def send_run_completion(
        self,
        workflow_type: str,
        run_id: str,
        status: str,
        metrics: Dict[str, Any],
        integration_mode: str = "simulation",
    ) -> Dict[str, Any]:
        return self.send_message(
            channel=None,
            text=f"EvoFlow run completed with status {status}.",
            metadata={
                "notification_type": "run_completed",
                "status": status,
                "workflow_type": workflow_type,
                "run_id": run_id,
                "failed_events": metrics.get("failed_events"),
                "retry_rate": metrics.get("retry_rate"),
                "escalation_count": metrics.get("escalation_count"),
                "mttr_seconds": metrics.get("mttr_seconds"),
            },
            integration_mode=integration_mode,
        )

    def _build_payload(
        self,
        channel: Optional[str],
        text: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        notification_type = metadata.get("notification_type", "workflow_event")
        title_map = {
            "escalation": "Escalation Created",
            "critical_failure": "Critical Failure",
            "run_completed": "Workflow Completed",
        }
        title = title_map.get(notification_type, "Workflow Event")

        fields = [
            {"type": "mrkdwn", "text": f"*Workflow*\n{metadata.get('workflow_type', 'unknown')}"},
            {"type": "mrkdwn", "text": f"*Run ID*\n`{metadata.get('run_id', 'n/a')}`"},
        ]
        if metadata.get("step_name"):
            fields.append({"type": "mrkdwn", "text": f"*Step*\n{metadata['step_name']}"})
        if metadata.get("severity"):
            fields.append({"type": "mrkdwn", "text": f"*Severity*\n{metadata['severity']}"})
        if metadata.get("status"):
            fields.append({"type": "mrkdwn", "text": f"*Status*\n{metadata['status']}"})

        reason = metadata.get("failure_reason")
        summary_parts = []
        for key in ("failed_events", "retry_rate", "escalation_count", "mttr_seconds"):
            if metadata.get(key) is not None:
                summary_parts.append(f"{key}: {metadata[key]}")

        blocks: list[Dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": f"EvoFlow AI | {title}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "section", "fields": fields[:10]},
        ]
        if reason:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Reason*\n>{str(reason)[:500]}"},
            })
        if summary_parts:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " | ".join(summary_parts)}],
            })

        payload: Dict[str, Any] = {"text": text, "blocks": blocks}
        if channel and self.bot_token:
            payload["channel"] = channel
        return payload

    def _send_via_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._post_json(self.webhook_url, payload, headers={"Content-Type": "application/json"})

    def _send_via_bot(self, payload: Dict[str, Any], channel: Optional[str]) -> Dict[str, Any]:
        if not channel:
            raise ValueError("Slack channel is required when using the Bot API.")
        payload = dict(payload)
        payload["channel"] = channel
        result = self._post_json(
            "https://slack.com/api/chat.postMessage",
            payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self.bot_token}",
            },
        )
        body = result.get("response_json", {})
        if not body.get("ok", True):
            raise RuntimeError(body.get("error", "Slack Bot API rejected the request."))
        return result

    def _post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    response_json: Dict[str, Any]
                    try:
                        response_json = json.loads(body)
                    except json.JSONDecodeError:
                        response_json = {"raw": body}
                    return {
                        "status_code": response.getcode(),
                        "response_body": body[:500],
                        "response_json": sanitize_for_audit(response_json),
                        "attempt": attempt,
                    }
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {body}"
            except urllib.error.URLError as exc:
                last_error = f"Network error: {exc.reason}"

            if attempt < self.max_retries:
                time.sleep(0.5 * attempt)

        raise RuntimeError(last_error or "Slack request failed.")
