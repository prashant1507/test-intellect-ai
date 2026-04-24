from __future__ import annotations

from .store import get_automation_kv

_BROWSER_PICK: frozenset[str] = frozenset({"chromium", "chrome", "firefox", "msedge"})

# First-run values when `automation_kv` has no row. User choices are persisted in DB via the UI
# (POST /api/automation/browser, /api/automation/env-options). Intentionally not read from .env.
_DEFAULT_BROWSER = "chromium"  # bundled Chromium
_DEFAULT_HEADLESS = False  # show browser
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
