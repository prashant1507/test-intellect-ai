from __future__ import annotations

from settings import settings

from .store import get_automation_kv

_BROWSER_PICK: frozenset[str] = frozenset({"chromium", "chrome", "firefox", "msedge"})

_DEFAULT_BROWSER = "chromium"
_DEFAULT_HEADLESS = True
_DEFAULT_SCREENSHOT_ON_PASS = False
_DEFAULT_TRACE_FILE_GENERATION = False


def get_effective_automation_browser() -> str:
    raw = (get_automation_kv("browser") or "").strip().lower()
    if raw in _BROWSER_PICK:
        return raw
    return _DEFAULT_BROWSER


def _get_bool_from_kv_or_default(kv_key: str, default: bool) -> bool:
    raw = get_automation_kv(kv_key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def get_effective_automation_headless() -> bool:
    return _get_bool_from_kv_or_default("headless", _DEFAULT_HEADLESS)


def get_effective_automation_screenshot_on_pass() -> bool:
    return _get_bool_from_kv_or_default("screenshot_on_pass", _DEFAULT_SCREENSHOT_ON_PASS)


def get_effective_automation_trace_file_generation() -> bool:
    return _get_bool_from_kv_or_default("trace_file_generation", _DEFAULT_TRACE_FILE_GENERATION)


def get_effective_automation_post_analysis() -> bool:
    return bool(settings.automation_post_analysis)


def _int_from_kv_parsed(
    key: str,
    lo: int,
    hi: int,
    *,
    on_missing: int,
    on_bad: int,
) -> int:
    raw = get_automation_kv(key)
    if raw is None or not str(raw).strip():
        return on_missing
    try:
        n = int(str(raw).strip())
    except ValueError:
        return on_bad
    return min(max(n, lo), hi)


def get_effective_automation_default_timeout_ms() -> int:
    d = int(settings.automation_default_timeout_ms)
    return _int_from_kv_parsed(
        "default_timeout_ms", 1000, 600_000, on_missing=d, on_bad=d
    )


def get_effective_automation_parallel_execution() -> int:
    d = min(max(int(settings.automation_parallel_execution), 1), 4)
    return _int_from_kv_parsed("parallel_execution", 1, 4, on_missing=d, on_bad=d)
