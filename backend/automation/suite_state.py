from __future__ import annotations

import threading

_lock = threading.Lock()
_running_case_id: str | None = None


def set_running_case(case_id: str | None) -> None:
    global _running_case_id
    with _lock:
        t = (case_id or "").strip()
        _running_case_id = t or None


def get_running_case() -> str | None:
    with _lock:
        return _running_case_id


def clear_running_case() -> None:
    set_running_case(None)
