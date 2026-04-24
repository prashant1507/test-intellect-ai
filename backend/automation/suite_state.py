from __future__ import annotations

import threading

_lock = threading.Lock()
_running_case_ids: set[str] = set()


def add_running_case(case_id: str | None) -> None:
    t = (case_id or "").strip()
    if not t:
        return
    with _lock:
        _running_case_ids.add(t)


def remove_running_case(case_id: str | None) -> None:
    t = (case_id or "").strip()
    if not t:
        return
    with _lock:
        _running_case_ids.discard(t)


def clear_running_cases() -> None:
    with _lock:
        _running_case_ids.clear()


def get_running_case_ids() -> list[str]:
    with _lock:
        return sorted(_running_case_ids)


def get_running_case() -> str | None:
    """First id (sorted) for backward compatibility with single-id clients."""
    ids = get_running_case_ids()
    return ids[0] if ids else None


def clear_running_case() -> None:
    clear_running_cases()
