from __future__ import annotations

from .store import get_automation_kv

_BROWSER_PICK: frozenset[str] = frozenset({"chromium", "firefox", "msedge"})

# First-run values when `automation_kv` has no row. User choices are persisted in DB via the UI
# (POST /api/automation/browser, /api/automation/env-options). Intentionally not read from .env.
_DEFAULT_BROWSER = "chromium"  # Chrome
_DEFAULT_HEADLESS = False  # show browser
_DEFAULT_SCREENSHOT_ON_PASS = False
_DEFAULT_TRACE_FILE_GENERATION = False
_DEFAULT_USE_MCP = False


def get_effective_automation_browser() -> str:
    """Playwright family: chromium (Chrome), firefox, or msedge (Chromium+Edge)."""
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


def get_effective_automation_use_mcp() -> bool:
    return _get_bool_from_kv_or_default("use_mcp", _DEFAULT_USE_MCP)
