"""
Unified LLM service for EvoFlow AI.

Provides structured JSON generation via OpenAI-compatible APIs.
- Reads OPENAI_API_KEY, MODEL_NAME_FAST, MODEL_NAME_SMART from environment / .env.
- complexity="low"  → MODEL_NAME_FAST (gpt-4o-mini by default) — orchestration, simple steps
- complexity="high" → MODEL_NAME_SMART (gpt-4o by default) — failure reasoning, strategy, evolution
- Returns (response_dict, audit_record) tuples so every call is auditable.
- Falls back to deterministic logic when the key is absent or calls fail.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Literal, Optional, Tuple

from backend.utils.env import load_env

logger = logging.getLogger(__name__)

load_env()


# ─── Lazy client factory ─────────────────────────────────────────────────────

_client = None
_model_fast: Optional[str] = None
_model_smart: Optional[str] = None


def _get_client(complexity: Literal["low", "high"] = "low"):
    """Return (client, model_name) or (None, None) when unavailable."""
    global _client, _model_fast, _model_smart
    if _client is not None:
        model = _model_smart if complexity == "high" else _model_fast
        return _client, model

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.warning(
            "OPENAI_API_KEY not set. EvoFlow AI will run with deterministic fallback logic."
        )
        return None, None

    try:
        from openai import OpenAI
        _client = OpenAI(api_key=api_key)
        _model_fast  = os.getenv("MODEL_NAME_FAST",  "gpt-4o-mini")
        _model_smart = os.getenv("MODEL_NAME_SMART", "gpt-4o")
        logger.info(f"LLM service initialised — fast={_model_fast}, smart={_model_smart}")
        model = _model_smart if complexity == "high" else _model_fast
        return _client, model
    except ImportError:
        logger.error("openai package not installed. Run: pip install openai")
        return None, None


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_response(
    prompt: str,
    schema: Dict[str, Any],
    temperature: float = 0.3,
    complexity: Literal["low", "high"] = "low",
    max_retries: int = 2,
    timeout: float = 30.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Generate a structured JSON response from the configured LLM.

    Parameters
    ----------
    prompt:      Task-specific instructions built by the calling agent.
    schema:      JSON Schema dict describing the expected output object.
    temperature: Sampling temperature (0.2–0.4 recommended for agents).
    complexity:  "low" → fast/cheap model; "high" → best reasoning model.
    max_retries: How many times to retry on transient failures.
    timeout:     Per-request timeout in seconds.

    Returns
    -------
    (response_dict, audit_record)
    """
    client, model = _get_client(complexity)

    if client is None:
        return _empty_response(schema), _no_key_audit(prompt)

    system_msg = (
        "You are a production AI agent inside EvoFlow AI, an enterprise workflow "
        "automation system. Every response MUST be a single valid JSON object — "
        "no markdown fences, no prose outside JSON. Be analytical, concise, and "
        "specific in all reasoning fields."
    )

    user_msg = (
        f"{prompt}\n\n"
        f"Respond with a JSON object that matches this schema exactly:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Output ONLY the JSON object."
    )

    last_error: str = ""
    for attempt in range(max_retries):
        try:
            t0 = time.time()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=temperature,
                timeout=timeout,
                response_format={"type": "json_object"},
            )
            latency_ms = int((time.time() - t0) * 1000)
            raw = response.choices[0].message.content
            parsed = json.loads(raw)

            logger.info(f"LLM OK — model={model} latency={latency_ms}ms attempt={attempt+1}")
            return parsed, {
                "ai_generated": True,
                "model": model,
                "complexity": complexity,
                "prompt": prompt,
                "raw_response": raw,
                "latency_ms": latency_ms,
                "attempt": attempt + 1,
                "error": None,
            }

        except Exception as exc:
            last_error = str(exc)
            logger.warning(f"LLM attempt {attempt+1} failed: {exc}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    logger.error(f"All LLM retries exhausted. Last error: {last_error}")
    return _empty_response(schema), {
        "ai_generated": False,
        "model": model,
        "complexity": complexity,
        "prompt": prompt,
        "raw_response": None,
        "latency_ms": 0,
        "attempt": max_retries,
        "error": last_error,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _empty_response(schema: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, prop in schema.get("properties", {}).items():
        t = prop.get("type", "string")
        if t == "string":
            result[key] = prop.get("enum", [""])[0] if "enum" in prop else ""
        elif t == "boolean":
            result[key] = False
        elif t in ("number", "integer"):
            result[key] = 0
        elif t == "array":
            result[key] = []
        elif t == "object":
            result[key] = {}
        else:
            result[key] = None
    return result


def _no_key_audit(prompt: str) -> Dict[str, Any]:
    return {
        "ai_generated": False,
        "model": None,
        "complexity": "low",
        "prompt": prompt,
        "raw_response": None,
        "latency_ms": 0,
        "attempt": 0,
        "error": "OPENAI_API_KEY not configured",
    }


def is_ai_available() -> bool:
    client, _ = _get_client()
    return client is not None
