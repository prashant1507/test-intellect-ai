from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import mcp.types as mcp_types
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from settings import settings

from .prefs import get_effective_automation_browser, get_effective_automation_headless

from .mcp_js import (
    build_mcp_content_code,
    build_mcp_count_code,
    build_mcp_screenshot_b64_code,
    build_mcp_step_code,
)

_FENCE = re.compile(r"^```(?:\w*)\s*", re.MULTILINE)
_COUNT_RE = re.compile(r"['\"]?c['\"]?\s*:\s*(\d+)")
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}")
_MCP_TOOL_READ_TIMEOUT = timedelta(seconds=240)


def playwright_mcp_output_dir() -> Path:
    p = Path(settings.automation_artifacts_dir).resolve().parent / "playwright-mcp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def mcp_effective_args() -> list[str]:
    args = list(json.loads(settings.automation_mcp_args))
    cmd = (settings.automation_mcp_cmd or "npx").strip().lower()
    if cmd in ("npx",) and not any(str(x) == "-y" or str(x) == "--yes" for x in args):
        args = ["-y", *args]
    if get_effective_automation_headless() and not any(str(x) == "--headless" for x in args):
        args.append("--headless")
    bmap = {
        "chromium": "chrome",
        "chrome": "chrome",
        "firefox": "firefox",
        "webkit": "webkit",
        "msedge": "msedge",
    }
    ab = get_effective_automation_browser()
    if not any(str(x).startswith("--browser=") for x in args):
        args.append(f"--browser={bmap.get(ab, 'chrome')}")
    if "--output-dir" not in args and not any(str(x).startswith("--output-dir=") for x in args):
        out = playwright_mcp_output_dir()
        out.mkdir(parents=True, exist_ok=True)
        args.extend(["--output-dir", str(out)])
    return args


def mcp_stdio_params() -> StdioServerParameters:
    cmd = (settings.automation_mcp_cmd or "npx").strip() or "npx"
    args = mcp_effective_args()
    env = dict(**__import__("os").environ)
    env["PLAYWRIGHT_MCP_HEADLESS"] = "1" if get_effective_automation_headless() else "0"
    env["PLAYWRIGHT_MCP_OUTPUT_DIR"] = str(playwright_mcp_output_dir())
    return StdioServerParameters(command=cmd, args=args, env=env)


def tool_result_to_text(res: mcp_types.CallToolResult) -> str:
    parts: list[str] = []
    for c in res.content or []:
        if isinstance(c, mcp_types.TextContent):
            parts.append(c.text)
    return "".join(parts)


def parse_mcp_json_text(raw: str) -> Any:
    t = (raw or "").strip()
    t = _FENCE.sub("", t, count=1).strip()
    if t.rstrip().endswith("```"):
        t = t.rstrip()[:-3].strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJ_RE.search(t)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError("MCP result not JSON")


async def mcp_call_run_code(session: ClientSession, code: str) -> str:
    name = (settings.automation_mcp_tool_run_code or "browser_run_code").strip()
    res = await session.call_tool(
        name,
        arguments={"code": code},
        read_timeout_seconds=_MCP_TOOL_READ_TIMEOUT,
    )
    if res.isError:
        raise RuntimeError(tool_result_to_text(res) or "MCP tool error")
    return tool_result_to_text(res)


async def mcp_call_navigate(session: ClientSession, url: str) -> str:
    tw = int(settings.automation_default_timeout_ms)
    name = (settings.automation_mcp_tool_navigate or "browser_navigate").strip()
    res = await session.call_tool(
        name,
        arguments={"url": url, "timeout": tw * 2},
        read_timeout_seconds=_MCP_TOOL_READ_TIMEOUT,
    )
    if res.isError:
        raise RuntimeError(tool_result_to_text(res) or "MCP navigate error")
    return tool_result_to_text(res)


async def mcp_get_page_content(session: ClientSession) -> str:
    return await mcp_call_run_code(session, build_mcp_content_code())


async def mcp_get_locator_count(
    session: ClientSession, selector: str, *, log: list[str] | None
) -> int | None:
    raw = await mcp_call_run_code(session, build_mcp_count_code(selector))
    try:
        data = parse_mcp_json_text(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        if log is not None:
            log.append(f"MCP: unparseable count for {selector[:80]!r} (raw: {raw!r}) {e!r}")
        return None
    if not isinstance(data, dict):
        return None
    m = _COUNT_RE.search(json.dumps(data))
    if m:
        return int(m.group(1))
    c = data.get("c")
    if isinstance(c, int):
        return c
    return None


async def mcp_run_step(
    session: ClientSession,
    selector: str,
    action: str,
    value: str,
    tw: int,
) -> tuple[bool, str | None, dict[str, Any]]:
    raw = await mcp_call_run_code(session, build_mcp_step_code(selector, action, value, tw))
    try:
        data = parse_mcp_json_text(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        return False, f"MCP result not JSON: {raw[:400]!r}", {}
    if not isinstance(data, dict):
        return False, "MCP result not an object", {}
    ok = bool(data.get("ok"))
    err = data.get("err")
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    if ok:
        return True, None, extra
    return False, str(err) if err else "failed", extra


async def mcp_screenshot_to_file(session: ClientSession, path: Path) -> bool:
    raw = await mcp_call_run_code(session, build_mcp_screenshot_b64_code())
    try:
        b = base64.standard_b64decode((raw or "").strip())
    except (binascii.Error, ValueError):
        return False
    try:
        path.write_bytes(b)
    except OSError:
        return False
    return True
