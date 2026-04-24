from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from settings import settings

from .errors import SpikeUserError
from .prefs import get_effective_automation_screenshot_on_pass
from .mcp_client import (
    mcp_call_run_code,
    mcp_call_navigate,
    mcp_get_page_content,
    mcp_get_locator_count,
    mcp_run_step,
    mcp_screenshot_to_file,
    mcp_stdio_params,
)
from .mcp_js import build_mcp_computed_style_code, build_mcp_stabilize_code
from .spike import (
    _quoted_hint,
    _first_when_index,
    _llm_base_ok,
    _llm_repair_after_runtime_fail,
    _llm_repair_zero_match_steps,
    _llm_build_steps,
    _llm_validate_and_refine_steps,
    _l,
    _merge_to_run_steps,
    _normalize_spike_action,
    _raise_if_spike_cancelled,
    spike_prerun_zero_match_message,
)


def _unwrap_spike_user_error(e: BaseException) -> SpikeUserError | None:
    if isinstance(e, SpikeUserError):
        return e
    exn = type(e).__name__
    if exn in ("ExceptionGroup", "BaseExceptionGroup") and hasattr(e, "exceptions"):
        for s in getattr(e, "exceptions", ()):
            if isinstance(s, BaseException):
                u = _unwrap_spike_user_error(s)
                if u is not None:
                    return u
    return None


def _flatten_base_exception(e: BaseException) -> str:
    name = type(e).__name__
    if name in ("ExceptionGroup", "BaseExceptionGroup") and hasattr(e, "exceptions"):
        exs = list(getattr(e, "exceptions", ()))
        if exs:
            return " | ".join(
                _flatten_base_exception(x) if isinstance(x, BaseException) else str(x)
                for x in exs
            )
    return f"{name}: {e!s}"


async def _mcp_list_bad_locators(
    session: Any,
    run_steps: list[dict[str, Any]],
    log: list[str],
    *,
    precheck_upto: int | None = None,
) -> list[int]:
    bad: list[int] = []
    for i, st in enumerate(run_steps):
        if precheck_upto is not None and i >= precheck_upto:
            _l(log, f"Pre-run: skip count check step {i} (on/after first When).")
            continue
        sel = (st.get("selector") or "").strip()
        if not sel:
            bad.append(i)
            continue
        try:
            c = await mcp_get_locator_count(session, sel, log=log)
        except (RuntimeError, OSError) as e:
            _l(log, f"Pre-run: step {i} count() error {e!r}")
            bad.append(i)
            continue
        if c is None:
            _l(
                log,
                f"Pre-run: step {i} could not get locator count (MCP); skipping precheck for this index",
            )
            continue
        if c == 0:
            _l(log, f"Pre-run: step {i} 0 matches {sel[:120]!r}")
            bad.append(i)
        else:
            _l(log, f"Pre-run: step {i} ok count={c}")
    return bad


async def _run_mcp_spike_one_browser(
    run_id: str,
    title: str,
    bdd_lines: list[str],
    url: str,
    spec_from_cache: list[dict[str, Any]] | None,
    log: list[str],
    *,
    html_dom: str | None = None,
) -> list[dict[str, Any]]:
    shot_on_pass = get_effective_automation_screenshot_on_pass()
    tw = int(settings.automation_default_timeout_ms)
    run_dir = Path(settings.automation_artifacts_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    params = mcp_stdio_params()
    _l(
        log,
        f"MCP: starting stdio {params.command!r} args={params.args!r} (Playwright MCP server).",
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await mcp_call_navigate(session, url.strip())
            try:
                await mcp_call_run_code(session, build_mcp_stabilize_code(tw))
            except RuntimeError as e:
                _l(log, f"MCP: post-navigate load wait (non-fatal): {e!r}")
            _raise_if_spike_cancelled(log)
            if spec_from_cache is None:
                dom = (html_dom or "").strip() or (await mcp_get_page_content(session))
                if (html_dom or "").strip():
                    _l(
                        log,
                        f"LLM: using pasted HTML for selectors ({len(dom)} chars), MCP page for actions",
                    )
                else:
                    _l(log, f"MCP: DOM {len(dom)} chars for LLM")
                _raise_if_spike_cancelled(log)
                spec = _llm_build_steps(title, bdd_lines, dom, log)
                fwi = _first_when_index(bdd_lines)
                spec = _llm_validate_and_refine_steps(
                    title, bdd_lines, dom, spec, log, first_when_index=fwi
                )
                _raise_if_spike_cancelled(log)
                run_steps = _merge_to_run_steps(bdd_lines, spec, "llm", log)
                if bool(getattr(settings, "automation_spike_prerun", True)):
                    pre_upto = fwi
                    bad = await _mcp_list_bad_locators(
                        session, run_steps, log, precheck_upto=pre_upto
                    )
                    if bad:
                        spec = _llm_repair_zero_match_steps(
                            title, bdd_lines, dom, spec, bad, log
                        )
                        run_steps = _merge_to_run_steps(bdd_lines, spec, "llm", log)
                        bad2 = await _mcp_list_bad_locators(
                            session, run_steps, log, precheck_upto=pre_upto
                        )
                        if bad2:
                            raise SpikeUserError(
                                spike_prerun_zero_match_message(bad2),
                                logs=log,
                            )
                else:
                    _l(
                        log,
                        "Prerun: locator pre-check disabled (automation_spike_prerun).",
                    )
            else:
                _l(log, "MCP: using cached selector plan")
                run_steps = _merge_to_run_steps(
                    bdd_lines, spec_from_cache, "cache", log
                )
            results = [dict(s) for s in run_steps]
            for i, st in enumerate(results):
                _raise_if_spike_cancelled(log)
                abort = False
                for attempt in (0, 1):
                    sel = (st.get("selector") or "").strip()
                    action = _normalize_spike_action(
                        str(st.get("action") or "click"), log
                    )
                    st["action"] = action
                    val = (st.get("value") or "") or ""
                    if action == "assert_contains" and not (val or "").strip():
                        qh = _quoted_hint(bdd_lines[i])
                        if qh:
                            val = qh
                            st["value"] = val
                    _l(
                        log,
                        f"MCP: step {i} att {attempt + 1} {action!r} {sel[:100]!r}",
                    )
                    ok, err, extra = await mcp_run_step(
                        session, sel, action, val, tw
                    )
                    for k, v in extra.items():
                        st[k] = v
                    st["pass"] = ok
                    st["err"] = err
                    if ok:
                        st["err"] = None
                        pth = run_dir / f"shot_step_{i}.png"
                        if shot_on_pass and await mcp_screenshot_to_file(
                            session, pth
                        ):
                            st["screenshot_path"] = f"{run_id}/{pth.name}"
                        break
                    st["pass"] = False
                    if attempt == 0 and _llm_base_ok():
                        dom2 = await mcp_get_page_content(session)
                        sh = ""
                        if sel:
                            try:
                                raw = await mcp_call_run_code(
                                    session,
                                    build_mcp_computed_style_code(sel),
                                )
                                t = (raw or "").strip()
                                if t.startswith("```"):
                                    t = t.split("\n", 1)[-1]
                                if t.rstrip().endswith("```"):
                                    t = t.rstrip()[:-3]
                                sh = t.strip()[:12_000]
                            except (RuntimeError, OSError) as e:
                                _l(log, f"MCP: computed style hint: {e!r}")
                        tnew = _llm_repair_after_runtime_fail(
                            title,
                            bdd_lines[i],
                            i,
                            {
                                "playwright_selector": st.get("selector", ""),
                                "action": st.get("action", "click"),
                                "value": (st.get("value") or "") or "",
                            },
                            (st.get("err") or err or "unknown") or "",
                            dom2,
                            log,
                            style_hint=sh,
                        )
                        if tnew is not None:
                            mg = _merge_to_run_steps(
                                [bdd_lines[i]], [tnew], "llm", log
                            )[0]
                            st["selector"] = mg["selector"]
                            st["action"] = mg["action"]
                            st["value"] = mg["value"]
                            st["source"] = "llm"
                        continue
                    pthf = run_dir / f"shot_step_{i}_fail.png"
                    if not await mcp_screenshot_to_file(session, pthf):
                        st["screenshot_path"] = None
                    else:
                        st["screenshot_path"] = f"{run_id}/{pthf.name}"
                    for j in range(i + 1, len(results)):
                        results[j]["pass"] = False
                        results[j]["err"] = "skipped (previous step failed)"
                    abort = True
                    break
                if abort:
                    break
            _ = await mcp_screenshot_to_file(
                session, run_dir / "shot_final.png"
            )
    return results


def run_mcp_spike_one_browser(
    run_id: str,
    title: str,
    bdd_lines: list[str],
    url: str,
    spec_from_cache: list[dict[str, Any]] | None,
    log: list[str],
    *,
    html_dom: str | None = None,
) -> list[dict[str, Any]]:
    try:
        return asyncio.run(
            _run_mcp_spike_one_browser(
                run_id,
                title,
                bdd_lines,
                url,
                spec_from_cache,
                log,
                html_dom=html_dom,
            )
        )
    except SpikeUserError:
        raise
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:
        s = _unwrap_spike_user_error(e)
        if s is not None:
            raise s
        msg = _flatten_base_exception(e)
        tb = traceback.format_exc()
        _l(log, f"MCP TaskGroup/stdio failed: {msg}")
        _l(log, tb[-8_000:] if len(tb) > 8_000 else tb)
        hint = (
            "Check npx/Playwright MCP. Install: npx playwright install chrome. "
            "Try: npx -y @playwright/mcp@latest --version"
        )
        raise SpikeUserError(f"{hint} — {msg}", logs=log) from e
