from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from ai_client import llm_chat_completion, parse_llm_json_object, spike_post_run_analysis
from prompts import (
    PLAYWRIGHT_SINGLE_STEP_FAILURE_REPAIR_SYSTEM_PROMPT,
    PLAYWRIGHT_VISION_STEP_EVIDENCE_SYSTEM_PROMPT,
    PLAYWRIGHT_STEPS_VS_DOM_INTRO_SYSTEM_PROMPT,
    playwright_map_bdd_to_locator_steps_prompt,
    playwright_reconcile_step_count_mismatch_prompt,
    playwright_refine_locators_against_html_rule,
    playwright_repair_zero_locator_matches_prompt,
)
from settings import settings

from .bdd import parse_bdd_structured, parse_bdd_step_lines
from .run_report_html import render_spike_run_html
from .errors import SpikeUserError
from .prefs import (
    get_effective_automation_browser,
    get_effective_automation_default_timeout_ms,
    get_effective_automation_headless,
    get_effective_automation_post_analysis,
    get_effective_automation_screenshot_on_pass,
    get_effective_automation_trace_file_generation,
    get_run_environment_for_report,
)
from .store import (
    begin_run,
    load_selector_cache,
    replace_run_steps,
    update_run,
    upsert_selector_cache,
)

_GH = re.compile(r"^(Given|When|Then|And)\b", re.I)
_BDD_THEN_TEXT_DISPLAYED = re.compile(
    r'(?i)\bThe text\s+"([^"]+)"\s+is\s+displayed\.?\s*$'
)
_PSEUDO_STRIP: tuple[str, ...] = (
    "::file-selector-button",
    "::first-line",
    "::placeholder",
    "::before",
    "::after",
    ":placeholder",
    ":before",
    ":after",
)
_SPIKE_ACTIONS: frozenset[str] = frozenset(
    "click dblclick fill clear focus hover check uncheck press press_sequentially "
    "select_option scroll_into_view get_text assert_text assert_contains "
    "assert_visible assert_hidden assert_value assert_checked assert_unchecked "
    "assert_enabled assert_disabled assert_attribute assert_placeholder assert_class".split()
)
_ACTION_ALIASES: dict[str, str] = {
    "type": "fill",
    "enter": "fill",
    "double_click": "dblclick",
    "keypress": "press",
    "select": "select_option",
    "scroll": "scroll_into_view",
    "is_visible": "assert_visible",
    "is_hidden": "assert_hidden",
    "to_have_text": "assert_text",
    "to_contain_text": "assert_contains",
}


def _l(log: list[str], msg: str) -> None:
    log.append(msg)


def _normalize_spike_action(raw: str, log: list[str] | None) -> str:
    s = (raw or "click").strip().lower().replace(" ", "_").replace("-", "_")
    s = _ACTION_ALIASES.get(s, s)
    if s in _SPIKE_ACTIONS:
        return s
    if s.startswith("assert"):
        if log is not None:
            _l(log, f"Unknown action {raw!r} -> assert_visible")
        return "assert_visible"
    if log is not None:
        _l(log, f"Unknown action {raw!r} -> click")
    return "click"


def _normalize_spike_type(raw: str | None) -> str:
    st = (raw or "ui").lower()
    return st if st in ("ui", "api") else "ui"


def _playwright_run_locator_action(
    expect: Any, loc: Any, action: str, value: str, tw: int
) -> tuple[bool, str | None, dict[str, Any]]:
    a = action
    v = value or ""
    ex = expect(loc)
    try:
        if a == "click":
            loc.click(timeout=tw)
        elif a == "dblclick":
            loc.dblclick(timeout=tw)
        elif a == "fill":
            loc.fill(v, timeout=tw)
        elif a == "clear":
            loc.clear(timeout=tw)
        elif a == "focus":
            loc.focus(timeout=tw)
        elif a == "hover":
            loc.hover(timeout=tw)
        elif a == "check":
            loc.check(timeout=tw)
        elif a == "uncheck":
            loc.uncheck(timeout=tw)
        elif a == "press":
            key = (v or "").strip()
            if not key:
                return False, "press requires value (key name)", {}
            loc.press(key, timeout=tw)
        elif a == "press_sequentially":
            if not v:
                return False, "press_sequentially requires value", {}
            loc.press_sequentially(v, timeout=tw)
        elif a == "select_option":
            vs = (v or "").strip()
            if not vs:
                return False, "select_option requires value", {}
            low = vs.lower()
            if low.startswith("value:"):
                loc.select_option(value=vs.split(":", 1)[1].strip(), timeout=tw)
            elif low.startswith("label:"):
                loc.select_option(label=vs.split(":", 1)[1].strip(), timeout=tw)
            elif low.startswith("index:"):
                loc.select_option(index=int(vs.split(":", 1)[1].strip()), timeout=tw)
            else:
                loc.select_option(label=vs, timeout=tw)
        elif a == "scroll_into_view":
            loc.scroll_into_view_if_needed(timeout=tw)
        elif a == "get_text":
            text = loc.inner_text(timeout=tw)
            extra: dict[str, Any] = {"actual_text": text}
            sub = (v or "").strip()
            if sub and sub not in text:
                return False, f"get_text: {sub!r} not in text", extra
            return True, None, extra
        elif a == "assert_text":
            ex.to_have_text(v, timeout=tw)
        elif a == "assert_contains":
            if not (v or "").strip():
                return False, "assert_contains requires value", {}
            ex.to_contain_text(v, timeout=tw)
        elif a == "assert_visible":
            ex.to_be_visible(timeout=tw)
        elif a == "assert_hidden":
            ex.to_be_hidden(timeout=tw)
        elif a == "assert_value":
            ex.to_have_value(v, timeout=tw)
        elif a == "assert_checked":
            ex.to_be_checked(timeout=tw)
        elif a == "assert_unchecked":
            ex.not_to_be_checked(timeout=tw)
        elif a == "assert_enabled":
            ex.to_be_enabled(timeout=tw)
        elif a == "assert_disabled":
            ex.to_be_disabled(timeout=tw)
        elif a == "assert_placeholder":
            expv = (v or "").strip()
            if not expv:
                return False, "assert_placeholder requires value", {}
            ex.to_have_attribute("placeholder", expv, timeout=tw)
        elif a == "assert_class":
            sub = (v or "").strip()
            if not sub:
                return False, "assert_class requires value", {}
            cl = str(loc.get_attribute("class", timeout=tw) or "")
            if sub not in cl:
                return False, f"class {sub!r} not in {cl!r}", {}
        elif a == "assert_attribute":
            raw = (v or "").strip()
            if "=" not in raw:
                return False, "assert_attribute needs name=value", {}
            an, av = raw.split("=", 1)
            an = an.strip()
            if not an:
                return False, "assert_attribute empty name", {}
            avs = av.strip()
            if an.lower() == "class":
                cl = str(loc.get_attribute("class", timeout=tw) or "")
                if avs not in cl:
                    return False, f"class token {avs!r} not in {cl!r}", {}
            else:
                ex.to_have_attribute(an, avs, timeout=tw)
        else:
            return False, f"Unhandled action: {a!r}", {}
        return True, None, {}
    except Exception as e:  # noqa: BLE001
        return False, str(e) or type(e).__name__, {}


def _raise_if_spike_cancelled(log: list[str]) -> None:
    from . import cancel

    if cancel.is_stop_one_spike() or cancel.is_stop_all_suite():
        _l(log, "Run cancelled (user).")
        raise SpikeUserError(cancel.cancel_message(), logs=log)


def spike_prerun_zero_match_message(bad_indices: list[int]) -> str:
    return (
        "Pre-run: no elements matched for step index(es) "
        f"{bad_indices!s} (Given/early When; locator().count() was 0). "
        "Try pasting page HTML, or set AUTOMATION_SPIKE_PRERUN=false."
    )


def _strip_invalid_css_pseudo_tail(s: str, log: list[str] | None) -> str:
    t = (s or "").strip()
    low = t.lower()
    for p in _PSEUDO_STRIP:
        if p in low:
            if log is not None:
                _l(log, f"Selector cleaned (pseudo): {s[:100]!r} -> {t.split(p)[0][:100]!r}")
            t = t.split(p)[0].rstrip(":")
            return t
    return t


def _finalize_playwright_selector(raw: str, log: list[str] | None) -> str:
    t = (raw or "").strip()
    t = _strip_invalid_css_pseudo_tail(t, log)
    return t


def _truncate_dom(s: str, limit: int = 200_000) -> str:
    t = s or ""
    if len(t) <= limit:
        return t
    return t[:limit]


def _playwright_computed_style_hint(
    page: Any, _expect: Any, sel: str, tw: int, log: list[str] | None
) -> str:
    try:
        loc = page.locator(sel).first
        o = loc.evaluate(
            """(el) => {
  const c = getComputedStyle(el);
  return ["color","background-color","display","border-color","border-width"].reduce(
    (a, k) => (a[k] = c.getPropertyValue(k), a), {}
  );
}""",
            timeout=min(tw, 10_000),
        )
        return json.dumps(o, ensure_ascii=False) if isinstance(o, dict) else str(o)[:12_000]
    except Exception as e:  # noqa: BLE001
        if log is not None:
            _l(log, f"Computed style hint: {e!r}")
        return ""


def _playwright_list_bad_locators(
    page: Any, run_steps: list[dict[str, Any]], log: list[str], *, precheck_upto: int | None
) -> list[int]:
    bad: list[int] = []
    for i, st in enumerate(run_steps):
        if precheck_upto is not None and i >= precheck_upto:
            _l(log, f"Pre-run: skip count step {i} (on/after first When).")
            continue
        sel = (st.get("selector") or "").strip()
        if not sel:
            bad.append(i)
            continue
        try:
            c = page.locator(sel).count()
        except Exception as e:  # noqa: BLE001
            _l(log, f"Pre-run: step {i} count() error {e!r}")
            bad.append(i)
            continue
        if c == 0:
            _l(log, f"Pre-run: step {i} 0 matches {sel[:80]!r}")
            bad.append(i)
        else:
            _l(log, f"Pre-run: step {i} ok count={c}")
    return bad


def compute_fingerprint(title: str, bdd: str, url: str, extra: str) -> str:
    m = f"{(title or '').strip()}\n{bdd or ''}\n{url or ''}\n{extra or ''}"
    return hashlib.sha256(m.encode("utf-8", errors="replace")).hexdigest()


def _quoted_hint(s: str) -> str:
    m = re.search(r'"([^"]{1,300})"', s or "")
    return m.group(1) if m else ""


def _bdd_literal_quoted_text_displayed(bdd_line: str) -> str | None:
    m = _BDD_THEN_TEXT_DISPLAYED.search((bdd_line or "").strip())
    return m.group(1) if m else None


def _default_selector_for_empty_bdd_step(
    bdd_line: str, st: dict[str, Any]
) -> str:
    bl = (bdd_line or "").strip()
    if re.search(r"(?i)\bdashboard\b", bl) and re.search(
        r"(?i)\b(redirect|redirects|navigate|navigation|land|lands|reach|reaches|open|opens|taken|goes|deliver|delivers)\b",
        bl,
    ):
        return "text=Dashboard"
    if re.search(r"(?i)\borangehrm\b", bl) and re.search(
        r"(?i)\b(login page|sign in|log in)\b",
        bl,
    ):
        return "text=OrangeHRM"
    if re.search(r"(?i)\busername\b", bl) and re.search(
        r"(?i)\b(enter|type|fill|input)\b",
        bl,
    ):
        return "input[name='username']"
    if re.search(r"(?i)\bpassword\b", bl) and re.search(
        r"(?i)\b(enter|type|fill|input)\b",
        bl,
    ):
        return "input[name='password']"
    if re.search(r"(?i)\blogin\b", bl) and re.search(r"(?i)\b(click|press)\b", bl):
        return "button[type='submit']"
    return "body"


def _ensure_step_selectors(
    spec: list[dict[str, Any]], bdd_lines: list[str], log: list[str]
) -> None:
    for i, st in enumerate(spec):
        if not isinstance(st, dict):
            continue
        if not isinstance(st.get("playwright_selector"), str):
            st["playwright_selector"] = ""
        if (st.get("playwright_selector") or "").strip():
            continue
        bline = bdd_lines[i] if i < len(bdd_lines) else ""
        d = _default_selector_for_empty_bdd_step(bline, st)
        st["playwright_selector"] = d
        _l(
            log,
            f"step {i}: empty playwright_selector filled -> {d!r} for {bline[:72]!r}",
        )


def _first_when_index(bdd_lines: list[str]) -> int:
    for i, ln in enumerate(bdd_lines):
        if re.match(r"^When\b", (ln or "").strip(), re.I):
            return i
    return 10_000


def _llm_base_ok() -> bool:
    return bool((settings.llm_text_url or "").strip()) and not settings.mock


def _coerce_spec_list(data: object, n: int, log: list[str]) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("steps not a list")
    if len(data) != n:
        _l(log, f"LLM: expecting {n} step object(s).")
        raise ValueError("wrong length")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"LLM step {i} is not a JSON object")
        out.append(item)
    return out


def _parse_steps_payload(raw: object, n: int, log: list[str]) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        _l(log, "LLM: top-level JSON is an array; using as steps list.")
        return _coerce_spec_list(raw, n, log)
    if isinstance(raw, dict):
        s = raw.get("steps", raw)
        if s is raw:
            s = raw.get("result", s)
        if isinstance(s, list):
            return _coerce_spec_list(s, n, log)
    raise ValueError("top-level is not a JSON object")


def _raw_steps_list_from_llm_parsed(data: Any) -> list[Any] | None:
    if data is None:
        return None
    if isinstance(data, dict) and isinstance(data.get("steps"), list):
        return data["steps"]
    if isinstance(data, list):
        return data
    return None


def _llm_reconcile_step_count(
    title: str,
    bdd_lines: list[str],
    dom: str,
    draft: list[Any],
    log: list[str],
) -> list[dict[str, Any]] | None:
    n = len(bdd_lines)
    safe = [x if isinstance(x, dict) else {} for x in draft]
    sys_r = playwright_reconcile_step_count_mismatch_prompt(n, len(draft))
    num = "\n".join(f"  {i}. {line}" for i, line in enumerate(bdd_lines))
    u = f"Title: {title}\nBDD:\n{num}\n\nDraft steps:\n{json.dumps(safe, ensure_ascii=False)}\n\nHTML:\n{_truncate_dom(dom)}"
    raw = llm_chat_completion(sys_r, u, temperature=0.05, max_tokens=12_000)
    data = parse_llm_json_object(raw)
    sl: Any = None
    if isinstance(data, dict) and isinstance(data.get("steps"), list):
        sl = data["steps"]
    elif isinstance(data, list):
        sl = data
    if not isinstance(sl, list) or len(sl) != n or not all(isinstance(x, dict) for x in sl):
        return None
    _l(log, f"LLM: reconcile -> {n} step(s).")
    return [dict(x) for x in sl]


def _heuristic_pad_to_n(
    spec: list[Any], n: int, bdd_lines: list[str], log: list[str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(n):
        o: dict[str, Any]
        if i < len(spec) and isinstance(spec[i], dict):
            o = dict(spec[i])
        else:
            bline = bdd_lines[i] if i < len(bdd_lines) else ""
            q = _quoted_hint(bline)
            if q:
                o = {"playwright_selector": f"text={q}", "action": "assert_text", "value": q}
            else:
                o = {"playwright_selector": "body", "action": "assert_visible", "value": ""}
            _l(log, f"heuristic step {i} for {bline[:90]!r}")
        if not isinstance(o.get("playwright_selector"), str) or not (o.get("playwright_selector") or "").strip():
            o["playwright_selector"] = "body"
        out.append(o)
    return out


def _llm_build_steps(
    title: str, bdd_lines: list[str], dom: str, log: list[str]
) -> list[dict[str, Any]]:
    n = len(bdd_lines)
    sys0 = playwright_map_bdd_to_locator_steps_prompt(n)
    num = "\n".join(f"  {i}. {line}" for i, line in enumerate(bdd_lines))
    user0 = f"Title: {title}\nBDD (N={n}, step[i] MUST implement line i only):\n{num}\n\nHTML:\n{_truncate_dom(dom)}"
    data: Any = None
    for attempt in (0, 1):
        u = user0 if attempt == 0 else user0 + f"\n\nCRITICAL: steps array length must be EXACTLY {n} (one per BDD line).\n"
        raw = llm_chat_completion(sys0, u, temperature=0.05, max_tokens=12_000)
        data = parse_llm_json_object(raw)
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            if len(data["steps"]) == n:
                break
        elif isinstance(data, list) and len(data) == n:
            data = {"steps": data}
            break
        _l(log, f"LLM: step count retry {attempt + 1} (got {len((data or {}).get('steps', data if isinstance(data, list) else []))!r} need {n})")
    steps_list = _raw_steps_list_from_llm_parsed(data) or []
    if len(steps_list) > n:
        _l(log, f"LLM: trim step list {len(steps_list)} -> {n}")
        steps_list = steps_list[:n]
    if len(steps_list) < n and _llm_base_ok():
        rec = _llm_reconcile_step_count(title, bdd_lines, dom, steps_list, log)
        if rec is not None:
            steps_list = rec
    if len(steps_list) < n:
        _l(
            log,
            f"LLM: still {len(steps_list)} step(s) need {n}, applying heuristic padding",
        )
        steps_list = _heuristic_pad_to_n(steps_list, n, bdd_lines, log)
    _ensure_step_selectors(steps_list, bdd_lines, log)
    for i, st in enumerate(steps_list):
        if not isinstance(st, dict):
            raise ValueError(f"step {i} is not a JSON object")
        if not isinstance(st.get("playwright_selector"), str):
            raise ValueError(f"step {i} missing playwright_selector")
    return [dict(s) for s in steps_list]


def _llm_validate_and_refine_steps(
    title: str,
    bdd_lines: list[str],
    dom: str,
    spec: list[dict[str, Any]],
    log: list[str],
    *,
    first_when_index: int,
) -> list[dict[str, Any]]:
    n = len(bdd_lines)
    proposed = json.dumps(
        [
            {
                "playwright_selector": x.get("playwright_selector", ""),
                "action": x.get("action", "click"),
                "value": (x.get("value") or "") or "",
            }
            for x in spec
        ],
        ensure_ascii=False,
    )
    fwi = first_when_index
    num = "\n".join(f"  {i}. {line}" for i, line in enumerate(bdd_lines))
    rule = playwright_refine_locators_against_html_rule(fwi, n)
    try:
        raw = llm_chat_completion(
            PLAYWRIGHT_STEPS_VS_DOM_INTRO_SYSTEM_PROMPT,
            f"Title: {title}\nBDD lines:\n{num}\nProposed:\n{proposed}\n\n{rule}\n\nHTML:\n{_truncate_dom(dom)}",
            temperature=0.1,
            max_tokens=10_000,
        )
        data = parse_llm_json_object(raw)
        out = _parse_steps_payload(data, n, log)
        _ensure_step_selectors(out, bdd_lines, log)
        _l(log, "LLM: validation pass against DOM.")
        return out
    except Exception as e:  # noqa: BLE001
        _l(log, f"LLM validation failed, keeping draft: {e!r}")
        return spec


def _llm_repair_zero_match_steps(
    title: str,
    bdd_lines: list[str],
    dom: str,
    spec: list[dict[str, Any]],
    bad: list[int],
    log: list[str],
) -> list[dict[str, Any]]:
    n = len(bdd_lines)
    sys_r = playwright_repair_zero_locator_matches_prompt(n, bad)
    u = f"Title: {title}\nBDD:\n" + "\n".join(bdd_lines) + f"\nSteps:\n{json.dumps(spec, ensure_ascii=False)}\n\nHTML:\n{_truncate_dom(dom)}"
    try:
        raw = llm_chat_completion(sys_r, u, temperature=0.1, max_tokens=10_000)
        out = _parse_steps_payload(parse_llm_json_object(raw), n, log)
        _ensure_step_selectors(out, bdd_lines, log)
        _l(log, f"LLM: repair 0-matches {bad!s}")
        return out
    except Exception as e:  # noqa: BLE001
        _l(log, f"LLM repair failed: {e!r}")
        raise SpikeUserError(
            f"Pre-run: no elements for steps {bad!s}. Repair failed: {e!s}.", logs=log
        ) from e


def _llm_repair_after_runtime_fail(
    title: str,
    bdd_line: str,
    idx: int,
    cur: dict[str, str],
    err: str,
    dom2: str,
    log: list[str],
    *,
    style_hint: str = "",
) -> dict[str, Any] | None:
    if not _llm_base_ok():
        return None
    u = f"BDD line: {bdd_line}\nFailed: {cur!r}\nError: {err!s}\nHTML:\n{_truncate_dom(dom2)}"
    if style_hint:
        u += f"\nComputed (failed selector) JSON: {style_hint[:8000]}"
    try:
        raw = llm_chat_completion(
            PLAYWRIGHT_SINGLE_STEP_FAILURE_REPAIR_SYSTEM_PROMPT,
            u,
            temperature=0.1,
            max_tokens=4000,
        )
        data = parse_llm_json_object(raw)
        st = (data.get("steps") or data) if isinstance(data, dict) else None
        if isinstance(st, list) and st and isinstance(st[0], dict):
            return st[0]
        if isinstance(data, dict) and "playwright_selector" in data:
            return data
    except Exception as e:  # noqa: BLE001
        _l(log, f"LLM: runtime repair step {idx} {e!r}")
    return None


def _llm_vision_repair_step_evidence(
    png: bytes,
    title: str,
    bdd_line: str,
    idx: int,
    cur: dict[str, str],
    err: str,
    dom2: str,
    log: list[str],
    *,
    style_hint: str = "",
) -> dict[str, Any] | Literal["not_visible"] | None:
    v = (settings.llm_vision_url or "").strip()
    if not v or not _llm_base_ok():
        return None
    u = (
        f"Title: {title}\nBDD line: {bdd_line}\nFailed: {cur!r}\n"
        f"Error: {err!s}\n\nHTML:\n{_truncate_dom(dom2)}"
    )
    if style_hint:
        u += f"\nComputed (failed selector) JSON: {style_hint[:8000]}"
    try:
        raw = llm_chat_completion(
            PLAYWRIGHT_VISION_STEP_EVIDENCE_SYSTEM_PROMPT,
            u,
            image_png=png,
            temperature=0.1,
            max_tokens=4000,
        )
        data = parse_llm_json_object(raw)
    except Exception as e:  # noqa: BLE001
        _l(log, f"LLM: vision repair step {idx} {e!r}")
        return None
    if not isinstance(data, dict):
        return None
    ev = data.get("expected_visible")
    if ev is False:
        return "not_visible"
    st0 = data.get("steps")
    step: dict[str, Any] | None = None
    if isinstance(st0, list) and st0 and isinstance(st0[0], dict):
        step = st0[0]
    if step is None and "playwright_selector" in data:
        step = data
    if not isinstance(step, dict) or not (str(step.get("playwright_selector") or "").strip()):
        return None
    return step


def _bdd_line_implies_message_hidden(line: str) -> bool:
    s = (line or "").strip()
    if re.search(r"(?i)^\s*(given|when|then|and)\s+no\s+", s):
        return True
    if re.search(
        r"(?i)\bshould\s+not\s+(appear|be\s+visible|be\s+displayed|show|display)\b",
        s,
    ) or re.search(r"(?i)\bno\s+error\s+message\b", s):
        return True
    if re.search(r"(?i)\bmust\s+not\s+appear\b", s):
        return True
    return False


def _bdd_line_implies_message_visible(line: str) -> bool:
    s = (line or "").strip()
    if _bdd_line_implies_message_hidden(s):
        return False
    if re.search(r"(?i)(should|must)\s+appear\b", s):
        return True
    if re.search(r"(?i)should\s+be\s+visible\b", s):
        return True
    if re.search(
        r"(?i)(validation\s+error\s+message|error\s+message|message).{0,120}displaying",
        s,
    ):
        return True
    return bool(re.search(r"(?i)should\s+be\s+displayed\s+below", s))


def _fix_assert_visibility_from_bdd(
    bdd_lines: list[str], spec: list[dict[str, Any]], log: list[str] | None
) -> None:
    for i, st in enumerate(spec):
        if i >= len(bdd_lines):
            break
        line = bdd_lines[i] or ""
        a = _normalize_spike_action(str(st.get("action") or "click"), log)
        if a not in ("assert_hidden", "assert_visible"):
            continue
        if _bdd_line_implies_message_hidden(line) and a == "assert_visible":
            st["action"] = "assert_hidden"
            if log is not None:
                _l(log, f"step {i}: BDD implies hidden -> assert_hidden")
        elif not _bdd_line_implies_message_hidden(
            line
        ) and a == "assert_hidden" and _bdd_line_implies_message_visible(line):
            st["action"] = "assert_visible"
            if log is not None:
                _l(log, f"step {i}: BDD implies visible/appear -> assert_visible")


def _merge_to_run_steps(
    bdd_lines: list[str], spec: list[dict[str, Any]], source: str, log: list[str]
) -> list[dict[str, Any]]:
    _fix_assert_visibility_from_bdd(bdd_lines, spec, log)
    out: list[dict[str, Any]] = []
    for i, bline in enumerate(bdd_lines):
        st: dict[str, Any] = spec[i] if i < len(spec) else {}
        ps = (st.get("playwright_selector") or st.get("selector") or "") or ""
        if not (str(ps) or "").strip():
            ps = _default_selector_for_empty_bdd_step(bline, st)
        ps = _finalize_playwright_selector(str(ps), log)
        a = _normalize_spike_action(str(st.get("action") or "click"), log)
        v = (st.get("value") or "") or ""
        lit = _bdd_literal_quoted_text_displayed(bline)
        if lit is not None:
            if a in ("assert_text", "assert_contains"):
                v = lit
            elif a == "assert_visible":
                a = "assert_text"
                v = lit
        out.append(
            {
                "step_index": i,
                "step_text": bline,
                "selector": ps,
                "action": a,
                "value": v,
                "source": source,
            }
        )
    return out


def _from_cache(bdd_lines: list[str], rows: list[dict]) -> list[dict[str, Any]] | None:
    if len(rows) != len(bdd_lines):
        return None
    return [
        {
            "playwright_selector": r.get("selector", ""),
            "action": r.get("action", "click"),
            "value": (r.get("value") or "") or "",
        }
        for r in rows
    ]


def _dom_fingerprint_snip(s: str | None) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    h = hashlib.sha256(t[:20_000].encode("utf-8")).hexdigest()[:32]
    return f"dom:{h}"


def _fingerprint_extras(spike_type: str, html_dom: str | None) -> str:
    if _normalize_spike_type(spike_type) == "api":
        return "api"
    return _dom_fingerprint_snip(html_dom)


def _run_spike_one_browser(
    run_id: str,
    title: str,
    bdd_lines: list[str],
    url: str,
    spec_from_cache: list[dict[str, Any]] | None,
    log: list[str],
    *,
    html_dom: str | None = None,
) -> list[dict[str, Any]]:
    from playwright.sync_api import expect, sync_playwright

    browser_name = get_effective_automation_browser()
    headless = get_effective_automation_headless()
    shot_on_pass = get_effective_automation_screenshot_on_pass()
    tw = int(get_effective_automation_default_timeout_ms())
    run_dir = Path(settings.automation_artifacts_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "trace.zip"
    gen_trace = get_effective_automation_trace_file_generation()

    with sync_playwright() as p:
        if browser_name == "firefox":
            browser = p.firefox.launch(headless=headless)
        elif browser_name == "msedge":
            browser = p.chromium.launch(channel="msedge", headless=headless)
        elif browser_name == "chrome":
            browser = p.chromium.launch(channel="chrome", headless=headless)
        else:
            browser = p.chromium.launch(headless=headless)
        try:
            context = browser.new_context()
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            context.set_default_timeout(tw)
            if gen_trace:
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
            else:
                _l(log, "Playwright: trace file disabled (turn on in Environment: Generate trace file).")
            page = context.new_page()
            _l(log, f"Playwright: goto {url.strip()!r}")
            page.goto(url.strip(), wait_until="domcontentloaded", timeout=tw * 2)
            try:
                page.wait_for_load_state("load", timeout=min(tw, 60_000))
            except Exception as e:  # noqa: BLE001
                _l(log, f"Playwright: load-state wait (non-fatal): {e!r}")
            _raise_if_spike_cancelled(log)
            if spec_from_cache is None:
                dom = (html_dom or "").strip() or page.content()
                if (html_dom or "").strip():
                    _l(
                        log,
                        f"LLM: pasted HTML for selectors ({len(dom)} chars), live page for actions",
                    )
                else:
                    _l(log, f"Playwright: DOM {len(dom)} chars for LLM")
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
                    bad = _playwright_list_bad_locators(
                        page, run_steps, log, precheck_upto=pre_upto
                    )
                    if bad:
                        spec = _llm_repair_zero_match_steps(
                            title, bdd_lines, dom, spec, bad, log
                        )
                        run_steps = _merge_to_run_steps(bdd_lines, spec, "llm", log)
                        bad2 = _playwright_list_bad_locators(
                            page, run_steps, log, precheck_upto=pre_upto
                        )
                        if bad2:
                            raise SpikeUserError(
                                spike_prerun_zero_match_message(bad2), logs=log
                            )
                else:
                    _l(log, "Prerun: locator pre-check disabled (automation_spike_prerun).")
            else:
                _l(log, "Playwright: using cached selector plan")
                run_steps = _merge_to_run_steps(
                    bdd_lines, spec_from_cache, "cache", log
                )
            results = [dict(s) for s in run_steps]
            for i, st in enumerate(results):
                _raise_if_spike_cancelled(log)
                abort = False
                n_step_attempts = (
                    3 if (settings.llm_vision_url or "").strip() else 2
                )
                for attempt in range(n_step_attempts):
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
                        f"Playwright: step {i} att {attempt + 1} {action!r} {sel[:100]!r}",
                    )
                    if not sel:
                        st["pass"] = False
                        st["err"] = "empty selector"
                        pthf = run_dir / f"shot_step_{i}_fail.png"
                        try:
                            page.screenshot(path=str(pthf), full_page=True)
                            st["screenshot_path"] = f"{run_id}/{pthf.name}"
                        except OSError:
                            st["screenshot_path"] = None
                        for j in range(i + 1, len(results)):
                            results[j]["pass"] = False
                            results[j]["err"] = "skipped (previous step failed)"
                        abort = True
                        break
                    try:
                        loc = page.locator(sel).first
                    except Exception as e2:  # noqa: BLE001
                        st["pass"] = False
                        st["err"] = str(e2)
                        abort = True
                        break
                    ok, err, extra = _playwright_run_locator_action(
                        expect, loc, action, val, tw
                    )
                    for k, v in extra.items():
                        st[k] = v
                    st["pass"] = ok
                    st["err"] = err
                    if ok:
                        st["err"] = None
                        pth = run_dir / f"shot_step_{i}.png"
                        if shot_on_pass:
                            try:
                                page.screenshot(path=str(pth), full_page=True)
                                st["screenshot_path"] = f"{run_id}/{pth.name}"
                            except OSError:
                                st["screenshot_path"] = None
                        break
                    st["pass"] = False
                    if attempt == 0 and _llm_base_ok():
                        dom2 = page.content()
                        sh = _playwright_computed_style_hint(
                            page, expect, sel, tw, log
                        ) if action != "assert_class" else ""
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
                    if attempt == 1 and (settings.llm_vision_url or "").strip():
                        shv = _playwright_computed_style_hint(
                            page, expect, sel, tw, log
                        ) if action != "assert_class" else ""
                        try:
                            vpng = page.screenshot(type="png", full_page=True)
                        except Exception as e3:  # noqa: BLE001
                            _l(log, f"LLM: vision repair screenshot: {e3!r}")
                            vpng = b""
                        if vpng:
                            dom2v = page.content()
                            vout = _llm_vision_repair_step_evidence(
                                vpng,
                                title,
                                bdd_lines[i],
                                i,
                                {
                                    "playwright_selector": st.get("selector", ""),
                                    "action": st.get("action", "click"),
                                    "value": (st.get("value") or "") or "",
                                },
                                (st.get("err") or err or "unknown") or "",
                                dom2v,
                                log,
                                style_hint=shv,
                            )
                            if vout == "not_visible":
                                st["err"] = "Expected content not visible on page (vision)"
                                pthf = run_dir / f"shot_step_{i}_fail.png"
                                try:
                                    page.screenshot(
                                        path=str(pthf), full_page=True
                                    )
                                    st["screenshot_path"] = (
                                        f"{run_id}/{pthf.name}"
                                    )
                                except OSError:
                                    st["screenshot_path"] = None
                                for j in range(i + 1, len(results)):
                                    results[j]["pass"] = False
                                    results[j]["err"] = (
                                        "skipped (previous step failed)"
                                    )
                                abort = True
                                break
                            if isinstance(vout, dict) and vout:
                                mg = _merge_to_run_steps(
                                    [bdd_lines[i]], [vout], "llm", log
                                )[0]
                                st["selector"] = mg["selector"]
                                st["action"] = mg["action"]
                                st["value"] = mg["value"]
                                st["source"] = "llm-vision"
                                continue
                    pthf = run_dir / f"shot_step_{i}_fail.png"
                    try:
                        page.screenshot(path=str(pthf), full_page=True)
                        st["screenshot_path"] = f"{run_id}/{pthf.name}"
                    except OSError:
                        st["screenshot_path"] = None
                    for j in range(i + 1, len(results)):
                        results[j]["pass"] = False
                        results[j]["err"] = "skipped (previous step failed)"
                    abort = True
                    break
                if abort:
                    break
            try:
                page.screenshot(path=str(run_dir / "shot_final.png"), full_page=True)
            except OSError:
                pass
            if gen_trace:
                try:
                    context.tracing.stop(path=str(trace_path))
                except Exception as e:  # noqa: BLE001
                    _l(log, f"Playwright: tracing.stop: {e!r}")
        finally:
            browser.close()
    return results


def _write_run_html(
    run_id: str,
    title: str,
    bdd: str,
    url: str,
    ok: bool,
    steps: list[dict],
    log: list[str],
    *,
    analysis: str,
    trace_href: str | None,
    jira_id: str = "",
    tag: str = "",
    requirement_ticket_id: str = "",
    run_environment: dict[str, Any] | None = None,
) -> str | None:
    if not bool(getattr(settings, "automation_write_run_html", True)):
        return None
    rep = Path(settings.automation_reports_dir)
    rep.mkdir(parents=True, exist_ok=True)
    p = rep / f"{run_id}.html"
    th: str | None = None
    if trace_href and get_effective_automation_trace_file_generation():
        th = trace_href
    body = render_spike_run_html(
        run_id,
        title,
        bdd,
        url,
        ok,
        steps,
        log,
        jira_id=jira_id,
        tag=tag,
        requirement_ticket_id=requirement_ticket_id,
        analysis=analysis,
        trace_href=th,
        run_environment=run_environment,
    )
    try:
        p.write_text(body, encoding="utf-8")
    except OSError:
        return None
    return f"/api/automation/reports/{p.name}"


def _execute_spike_finalize(
    run_id: str,
    title: str,
    bdd: str,
    u: str,
    final: list[dict[str, Any]],
    log: list[str],
    jira_id: str,
    tag: str,
    requirement_ticket_id: str,
    write_run_html: bool,
    used_cache: bool,
    fp: str,
    upsert_cache_on_ok: bool,
) -> dict[str, Any]:
    art = Path(settings.automation_artifacts_dir)
    ok = all(x.get("pass") for x in final)
    analysis = ""
    if get_effective_automation_post_analysis() and _llm_base_ok():
        analysis = spike_post_run_analysis(
            title, u, ok, [dict(s) for s in final], "\n".join(log[-500:])
        )
    for x in final:
        sp = x.get("screenshot_path")
        if sp and not (art / sp).is_file():
            x["screenshot_path"] = None
    rel_steps: list[dict[str, Any]] = []
    for x in final:
        p = x.get("screenshot_path")
        rec: dict[str, Any] = {
            "step_index": x["step_index"],
            "step_text": x["step_text"],
            "selector": x["selector"],
            "action": x["action"],
            "value": x.get("value"),
            "pass": x.get("pass", False),
            "err": x.get("err"),
            "source": x.get("source"),
            "screenshot_path": p,
        }
        if x.get("actual_text") is not None:
            rec["actual_text"] = x["actual_text"]
        rel_steps.append(rec)
    replace_run_steps(run_id, rel_steps)
    run_dir = art / run_id
    trace_rel = f"{run_id}/trace.zip"
    run_environment = get_run_environment_for_report()
    summary = {
        "steps": rel_steps,
        "ok": ok,
        "url": u,
        "debug_logs": list(log),
        "analysis": analysis,
        "run_environment": run_environment,
    }
    err_msg = None if ok else next(
        (s.get("err") for s in rel_steps if s.get("err")), "failed"
    )
    base_artifacts = f"/api/automation/artifacts/{run_id}"
    trace_href_htm = (
        f"{base_artifacts}/trace.zip" if (run_dir / "trace.zip").is_file() else None
    )
    report_url: str | None
    if write_run_html:
        report_url = _write_run_html(
            run_id,
            title,
            bdd,
            u,
            ok,
            rel_steps,
            log,
            analysis=analysis,
            trace_href=trace_href_htm,
            jira_id=jira_id,
            tag=tag,
            requirement_ticket_id=requirement_ticket_id,
            run_environment=run_environment,
        )
        if report_url:
            summary["report_url"] = report_url
    else:
        report_url = None
    update_run(
        run_id,
        status="completed" if ok else "failed",
        error=err_msg,
        trace_path=trace_rel if (run_dir / "trace.zip").is_file() else None,
        summary=summary,
        used_cache=used_cache,
    )
    if ok and upsert_cache_on_ok:
        vision_repair_passed = any(
            (s.get("source") or "") == "llm-vision" and s.get("pass")
            for s in rel_steps
        )
        if vision_repair_passed:
            _l(
                log,
                "Saved Selectors: not updated (step(s) passed after vision-based repair; "
                "selectors are not treated as stable).",
            )
        else:
            upsert_selector_cache(fp, list(rel_steps))
    base = f"/api/automation/artifacts/{run_id}"
    return {
        "run_id": run_id,
        "fingerprint": fp,
        "used_cache": used_cache,
        "status": "completed" if ok else "failed",
        "error": err_msg,
        "trace_stored": (run_dir / "trace.zip").is_file(),
        "trace_url": f"{base}/trace.zip" if (run_dir / "trace.zip").is_file() else None,
        "report_url": report_url,
        "analysis": analysis,
        "steps": rel_steps,
        "debug_logs": list(log),
    }


def _execute_spike_sync(
    run_id: str,
    title: str,
    bdd: str,
    url: str,
    log: list[str],
    html_dom: str | None = None,
    jira_id: str = "",
    tag: str = "",
    *,
    requirement_ticket_id: str = "",
    write_run_html: bool = True,
    spike_type: str = "ui",
) -> dict[str, Any]:
    st = _normalize_spike_type(spike_type)
    bdd_lines = parse_bdd_step_lines(bdd)
    _l(log, f"Parsed BDD: {len(bdd_lines)} line(s).")
    try:
        hint = parse_bdd_structured(bdd)
        if hint:
            _l(log, f"BDD parser: {len(hint)} structured hint(s) (heuristic).")
    except Exception:  # noqa: BLE001
        pass
    if not bdd_lines:
        raise SpikeUserError("BDD is empty (no steps).", logs=log)
    u = (url or "").strip()
    if st == "api":
        if not u:
            raise SpikeUserError(
                "API base URL is required (e.g. https://api.example.com).", logs=log
            )
        if not re.match(r"^https?://", u, re.I):
            raise SpikeUserError(
                "API base URL must start with http:// or https://", logs=log
            )
        _raise_if_spike_cancelled(log)
        if not _llm_base_ok():
            raise SpikeUserError(
                "LLM_TEXT_URL is not set; cannot run API BDD (LLM plans each step).", logs=log
            )
        fp = compute_fingerprint(title, bdd, u, "api")
        _l(log, f"API fingerprint: {fp[:16]}…")
        from . import api_spike

        _l(log, "Running API BDD: LLM plan + HTTP client.")
        final = api_spike.run_api_bdd(run_id, title, bdd, u, log)
        return _execute_spike_finalize(
            run_id,
            title,
            bdd,
            u,
            final,
            log,
            jira_id,
            tag,
            requirement_ticket_id,
            write_run_html,
            used_cache=False,
            fp=fp,
            upsert_cache_on_ok=False,
        )
    if not u:
        raise SpikeUserError(
            "Page URL is required. The service loads the page and uses its DOM for selector generation.",
            logs=log,
        )
    _raise_if_spike_cancelled(log)
    extra = _dom_fingerprint_snip(html_dom)
    fp = compute_fingerprint(title, bdd, u, extra)
    _l(log, f"Fingerprint: {fp[:16]}…")
    used_cache = False
    spec_from_cache: list[dict[str, Any]] | None = None
    cached = load_selector_cache(fp, len(bdd_lines))
    if cached is not None:
        cspec = _from_cache(bdd_lines, cached)
        if cspec is not None:
            spec_from_cache = cspec
            used_cache = True
            _l(log, "Selector cache hit.")
    if spec_from_cache is None and not _llm_base_ok():
        raise SpikeUserError(
            "LLM_TEXT_URL is not set; cannot build selectors on first run for this fingerprint.",
            logs=log,
        )
    _raise_if_spike_cancelled(log)
    final = _run_spike_one_browser(
        run_id,
        title,
        bdd_lines,
        u,
        spec_from_cache=spec_from_cache,
        log=log,
        html_dom=html_dom,
    )
    return _execute_spike_finalize(
        run_id,
        title,
        bdd,
        u,
        final,
        log,
        jira_id,
        tag,
        requirement_ticket_id,
        write_run_html,
        used_cache=used_cache,
        fp=fp,
        upsert_cache_on_ok=True,
    )


def run_automation_spike(
    title: str,
    bdd: str,
    url: str,
    html_dom: str | None = None,
    jira_id: str = "",
    tag: str = "",
    *,
    requirement_ticket_id: str = "",
    write_run_html: bool = True,
    spike_type: str = "ui",
) -> dict[str, Any]:
    log: list[str] = []
    u = (url or "").strip()
    run_id = str(uuid.uuid4())
    st = _normalize_spike_type(spike_type)
    _l(
        log,
        f"run_id={run_id} title={title!r} url={u!r} spike_type={st!r}",
    )
    begin_run(
        run_id,
        (title or "").strip() or "Untitled",
        compute_fingerprint(title, bdd, u, _fingerprint_extras(st, html_dom)),
    )
    try:
        return _execute_spike_sync(
            run_id,
            title,
            bdd,
            u,
            log,
            html_dom=html_dom,
            jira_id=jira_id,
            tag=tag,
            requirement_ticket_id=requirement_ticket_id,
            write_run_html=write_run_html,
            spike_type=st,
        )
    except SpikeUserError as e:
        setattr(e, "run_id", run_id)
        _l(e.logs, f"SpikeUserError: {e}")
        update_run(
            run_id,
            status="failed",
            error=str(e),
            trace_path=None,
            summary={"err": str(e), "debug_logs": list(e.logs)},
            used_cache=False,
        )
        raise
    except Exception as e:  # noqa: BLE001
        _l(log, f"Exception: {e!r}")
        update_run(
            run_id,
            status="failed",
            error=str(e),
            trace_path=None,
            summary={"err": str(e), "debug_logs": list(log)},
            used_cache=False,
        )
        raise SpikeUserError(str(e), logs=log) from e
    finally:
        from . import cancel

        cancel.clear_stop_one_spike()


async def run_automation_spike_async(
    title: str,
    bdd: str,
    url: str,
    html_dom: str | None = None,
    jira_id: str = "",
    tag: str = "",
    *,
    requirement_ticket_id: str = "",
    write_run_html: bool = True,
    spike_type: str = "ui",
) -> dict[str, Any]:
    return await asyncio.to_thread(
        run_automation_spike,
        title,
        bdd,
        url,
        html_dom,
        jira_id,
        tag,
        requirement_ticket_id=requirement_ticket_id,
        write_run_html=write_run_html,
        spike_type=spike_type,
    )
