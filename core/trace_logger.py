import json
import os
import threading
from datetime import datetime
from pathlib import Path

from core.utils import get_persistent_root


def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_TRACE_ENABLED = _env_enabled("OMNIPACK_TRACE_SELECTION", False)
_TRACE_LOCK = threading.Lock()
_TRACE_PATH = None

if _TRACE_ENABLED:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _TRACE_PATH = get_persistent_root() / f"selection_trace_{stamp}.jsonl"


def is_trace_enabled() -> bool:
    return _TRACE_ENABLED


def get_trace_path() -> str:
    return str(_TRACE_PATH) if _TRACE_PATH else ""


def trace_event(component: str, event: str, **fields):
    if not _TRACE_ENABLED or _TRACE_PATH is None:
        return

    payload = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "component": component,
        "event": event,
        "fields": fields,
    }

    line = json.dumps(payload, ensure_ascii=False)
    with _TRACE_LOCK:
        Path(_TRACE_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
