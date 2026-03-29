from __future__ import annotations

from pathlib import Path

_ENV_LOADED = False


def load_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        _ENV_LOADED = True
        return

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    _ENV_LOADED = True
