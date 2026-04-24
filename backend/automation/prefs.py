from __future__ import annotations

from settings import settings

from .store import get_automation_kv

_BROWSER_PICK: frozenset[str] = frozenset({"chromium", "chrome", "firefox", "msedge"})

# First-run when `automation_kv` has no row: user choices are persisted in DB via
# POST /api/automation/browser and /api/automation/env-options, with fallbacks from settings
# (optional .env) for `default_timeout_ms` alongside browser/headless/etc. Post-run analysis uses `settings` only.
_DEFAULT_BROWSER = "chromium"  # bundled Chromium
_DEFAULT_HEADLESS = True  # headless until user turns it off (no DB row yet)
_DEFAULT_SCREENSHOT_ON_PASS = False
_DEFAULT_TRACE_FILE_GENERATION = False


def get_effective_automation_browser() -> str:
    """Playwright: chromium (bundled), chrome (Google Chrome), firefox, or msedge."""
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


def get_effective_automation_default_timeout_ms() -> int:
    raw = get_automation_kv("default_timeout_ms")
    if raw is None or not str(raw).strip():
        return int(settings.automation_default_timeout_ms)
    try:
        n = int(str(raw).strip())
    except ValueError:
        return int(settings.automation_default_timeout_ms)
    return min(max(n, 1000), 600_000)


def get_effective_automation_parallel_execution() -> int:
    """Saved suite: max concurrent cases (1–4). Default 1 (sequential)."""
    raw = get_automation_kv("parallel_execution")
    if raw is None or not str(raw).strip():
        return min(max(int(settings.automation_parallel_execution), 1), 4)
    try:
        n = int(str(raw).strip())
    except ValueError:
        return min(max(int(settings.automation_parallel_execution), 1), 4)
    return min(max(n, 1), 4)
