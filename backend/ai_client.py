from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from difflib import SequenceMatcher

import requests
from typing import Any

from key_norm import norm_issue_key
from prompts import (
    BDD_TEST_CASES_BATCH_SCORING_SYSTEM_PROMPT,
    BDD_TEST_CASE_GENERATION_SYSTEM_PROMPT,
    BDD_TEST_GENERATION_WITH_ATTACHMENTS_SUPPLEMENT_PROMPT,
    SKELETON_TEST_CODE_GENERATION_SYSTEM_PROMPT,
    UI_SPIKE_TEST_RUN_SUMMARY_SYSTEM_PROMPT,
)
from settings import settings


def _paste_priority_list() -> list[str]:
    raw = (settings.paste_mode_priorities or "").strip()
    if not raw:
        return ["Highest", "High", "Medium", "Low", "Lowest"]
    return [x.strip() for x in raw.split(",") if x.strip()]


def resolve_priority_allowed_for_generation(
    paste_mode: bool,
    jira_fetched_names: list[str] | None,
) -> list[str]:
    if paste_mode:
        return _paste_priority_list()
    if jira_fetched_names and any(str(x).strip() for x in jira_fetched_names):
        return [str(x).strip() for x in jira_fetched_names if str(x).strip()]
    return _paste_priority_list()


def _norm_priority(raw: object | None, allowed: list[str]) -> str:
    if not allowed:
        return "Medium"
    mid = allowed[len(allowed) // 2]
    s = str(raw or "").strip()
    if not s:
        return mid
    low = s.lower()
    for a in allowed:
        if a.lower() == low:
            return a
    for a in allowed:
        if low in a.lower() or a.lower() in low:
            return a
    return mid


_GH_PREFIX = re.compile(r"^(Given|When|Then|And)\s+(.*)$", re.IGNORECASE | re.DOTALL)
_GH_KEYWORD = {"given": "Given", "when": "When", "then": "Then", "and": "And"}
_WS_NORM = re.compile(r"\s+")
_AND_SPLIT = re.compile(r"\s+and\s+", re.IGNORECASE)
_GH_ALLOWED_PREFIXES = ("Given ", "When ", "Then ", "And ")
_ASSERTION_OBSERVABLE_RE = re.compile(
    r"\b("
    r"visible|displayed|shown|appears?|message|error|warning|toast|alert|notification|"
    r"page|screen|dialog|modal|button|field|input|link|tab|row|table|list|card|"
    r"status|value|enabled|disabled|checked|unchecked|selected|redirected|navigated|"
    r"created|updated|deleted|removed|saved|downloaded|uploaded"
    r")\b",
    re.IGNORECASE,
)
_VAGUE_ASSERTION_RE = re.compile(
    r"\b("
    r"it works|works correctly|loads correctly|validation works|behaves correctly|"
    r"displayed correctly|shown correctly|handled correctly|processed successfully|"
    r"successful(?:ly)?"
    r")\b",
    re.IGNORECASE,
)
_STEP_DRAFT_MARKERS_RE = re.compile(
    r"----|\bche?ck\s+this\b|\bchekc\b|\bcheck\s+this\b|\bverify\s+this\b|\bTODO\b|\bFIXME\b|\bTBD\b|\bplaceholder\b",
    re.IGNORECASE,
)


def _cap_first_line(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    return s[0].upper() + s[1:]


def _gh_kw_and_rest_raw(s: str) -> tuple[str, str] | None:
    m = _GH_PREFIX.match(s.strip())
    if not m:
        return None
    kw_raw, rest = m.group(1), m.group(2)
    kw = _GH_KEYWORD.get(kw_raw.lower(), kw_raw[0].upper() + kw_raw[1:].lower())
    return kw, rest


def _cap_gherkin_line(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    gr = _gh_kw_and_rest_raw(s)
    if not gr:
        return s
    kw, rest = gr
    rest = rest.lstrip()
    if not rest:
        return kw
    return f"{kw} {rest}"


def _cap_lines(s: str) -> str:
    return "\n".join(_cap_first_line(line) for line in s.split("\n"))


def _steps_list(raw: object) -> list[str]:
    if isinstance(raw, str):
        return [x.strip() for x in raw.split("\n") if x.strip()]
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def _expand_keyword_and_chains(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        for kw in ("Given ", "When ", "Then "):
            if s.startswith(kw):
                body = s[len(kw) :]
                if " And " not in body:
                    out.append(s)
                    break
                parts = [p.strip() for p in body.split(" And ")]
                out.append(kw + parts[0])
                for p in parts[1:]:
                    out.append("And " + p)
                break
        else:
            out.append(s)
    return out


def _split_natural_and_in_line(line: str) -> list[str]:
    s = line.strip()
    if not s:
        return []
    gr = _gh_kw_and_rest_raw(s)
    if not gr:
        return [line]
    kw, rest = gr
    rest = rest.strip()
    if not rest:
        return [line]
    parts = _split_unquoted_natural_and(rest)
    if len(parts) <= 1:
        return [line]
    if any(len(p.split()) < 2 for p in parts):
        return [line]
    out: list[str] = [f"{kw} {parts[0].strip()}"]
    for p in parts[1:]:
        p = p.strip()
        if p:
            out.append(f"And {p}")
    return out


def _inside_double_quotes(text: str, idx: int) -> bool:
    quoted = False
    escaped = False
    for ch in text[:idx]:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            quoted = not quoted
    return quoted


def _split_unquoted_natural_and(rest: str) -> list[str]:
    parts: list[str] = []
    last = 0
    split = False
    for m in _AND_SPLIT.finditer(rest):
        if _inside_double_quotes(rest, m.start()):
            continue
        parts.append(rest[last : m.start()].strip())
        last = m.end()
        split = True
    if not split:
        return [rest]
    parts.append(rest[last:].strip())
    return parts


def _split_natural_and_in_steps(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        out.extend(_split_natural_and_in_line(raw))
    return out


_ORPHAN_AND = re.compile(r"^And\s+(\S+)\s*$", re.I)


def _merge_orphan_and_words(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        s = line.strip()
        m = _ORPHAN_AND.match(s)
        if m and out:
            out[-1] = f"{out[-1]} and {m.group(1).lower()}"
            continue
        out.append(s)
    return out


def _json(s: str) -> dict:
    s = (s or "").strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", s, re.I)
    if m:
        s = m.group(1).strip()
    if not s:
        raise ValueError(
            "The model returned an empty response. Try again, or check LLM_TEXT_URL and server logs."
        )
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        a, b = s.find("{"), s.rfind("}")
        if 0 <= a < b:
            try:
                return json.loads(s[a : b + 1])
            except json.JSONDecodeError:
                pass
        head = s[:200].replace("\n", " ")
        if len(s) > 200:
            head += "…"
        raise ValueError(
            "The model did not return valid JSON. Try again or use a model that follows JSON-only instructions. "
            f"Start of response: {head!r}"
        ) from e


def _pick_jira_issue_key(*vals: object) -> str | None:
    for v in vals:
        s = norm_issue_key(str(v or ""))
        if s:
            return s
    return None


def _merge_jira_row_meta(row: dict, n: dict) -> None:
    if n.get("jira_existing"):
        row["jira_existing"] = True
    for k in ("jira_status", "jira_browse_url", "priority_icon_url"):
        v = n.get(k)
        if isinstance(v, str) and v.strip():
            row[k] = v.strip()


def _collapse_multiline(s: str) -> str:
    return "\n".join(_WS_NORM.sub(" ", ln).strip() for ln in s.split("\n"))


def _clamp_score_0_10(sc: object) -> float | None:
    if not isinstance(sc, (int, float)) or isinstance(sc, bool):
        return None
    return round(max(0.0, min(10.0, float(sc))), 1)


def _norm(c: dict, *, default_change_status: str = "new", allowed_priorities: list[str]) -> dict:
    st = _steps_list(c.get("steps"))
    pre = str(c.get("preconditions") or "").strip()
    exp = str(c.get("expected_result") or "").strip()
    if st and st[0].strip().startswith("Given "):
        st = _expand_keyword_and_chains(st)
        st = _split_natural_and_in_steps(st)
        st = _merge_orphan_and_words(st)
        pre, exp = "", ""
    raw = c.get("change_status")
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        cs = default_change_status
    else:
        low = str(raw).lower().strip()
        cs = low if low in ("new", "updated", "unchanged") else default_change_status
    st = [_WS_NORM.sub(" ", _cap_gherkin_line(x)).strip() for x in st]

    if c.get("jira_existing"):
        pr = str(c.get("priority") or "").strip()
        prio = pr if pr else _norm_priority(None, allowed_priorities)
    else:
        prio = _norm_priority(c.get("priority"), allowed_priorities)
    out = {
        "description": _collapse_multiline(_cap_lines(str(c.get("description") or ""))),
        "preconditions": _collapse_multiline(_cap_lines(pre)),
        "steps": st,
        "expected_result": _collapse_multiline(_cap_lines(exp)),
        "change_status": cs,
        "priority": prio,
    }
    if c.get("jira_existing"):
        out["jira_existing"] = True
    js = str(c.get("jira_status") or "").strip()
    if js:
        out["jira_status"] = js
    jb = str(c.get("jira_browse_url") or "").strip()
    if jb:
        out["jira_browse_url"] = jb
    pi = str(c.get("priority_icon_url") or "").strip()
    if pi:
        out["priority_icon_url"] = pi
    jk = _pick_jira_issue_key(c.get("jira_issue_key"))
    if jk:
        out["jira_issue_key"] = jk
    sc = _clamp_score_0_10(c.get("score"))
    if sc is not None:
        out["score"] = sc
    return out


def _steps_norm_tuple(raw_steps: object) -> tuple[str, ...]:
    steps = raw_steps if isinstance(raw_steps, list) else []
    return tuple(_WS_NORM.sub(" ", str(x).strip()).casefold() for x in steps)


def _desc_fold(tc: dict) -> str:
    return _WS_NORM.sub(" ", str(tc.get("description") or "").strip()).casefold()


def _tc_fingerprint(n: dict) -> tuple:
    return (_desc_fold(n), _steps_norm_tuple(n.get("steps")))


def _tc_signature_norm(tc: dict) -> str:
    lines = list(_steps_norm_tuple(tc.get("steps")))
    return _desc_fold(tc) + "\n" + "\n".join(lines)


_SIMILAR_THRESHOLD = 0.92
_JIRA_EXISTING_MATCH_THRESHOLD = 0.88


def _jira_row_from_entry(je: dict, allowed_priorities: list[str]) -> dict:
    base_tc = je.get("test_case")
    if not isinstance(base_tc, dict):
        base_tc = {}
    row = _norm(base_tc, default_change_status="unchanged", allowed_priorities=allowed_priorities)
    row["change_status"] = "unchanged"
    row["jira_issue_key"] = je["issue_key"]
    row["jira_status"] = str(je.get("status_name") or "")
    row["jira_browse_url"] = str(je.get("browse_url") or "")
    row["jira_existing"] = True
    jp = str(je.get("jira_priority_name") or "").strip()
    if jp:
        row["priority"] = jp
    ji = str(je.get("jira_priority_icon_url") or "").strip()
    if ji:
        row["priority_icon_url"] = ji
    return row


def merge_ai_cases_with_jira_existing(
    ai_cases: list[dict],
    jira_entries: list[dict],
    *,
    allowed_priorities: list[str],
) -> list[dict]:
    if not jira_entries:
        return ai_cases
    pairs: list[tuple[float, int, int]] = []
    for i, ai in enumerate(ai_cases):
        if not isinstance(ai, dict):
            continue
        na = _norm(ai, default_change_status="new", allowed_priorities=allowed_priorities)
        for j, je in enumerate(jira_entries):
            tc = je.get("test_case") if isinstance(je, dict) else None
            if not isinstance(tc, dict):
                continue
            nj = _norm(tc, default_change_status="unchanged", allowed_priorities=allowed_priorities)
            sim = _tc_similarity_for_merge(na, nj)
            if sim >= _JIRA_EXISTING_MATCH_THRESHOLD:
                pairs.append((sim, i, j))
    pairs.sort(key=lambda x: -x[0])
    matched_ai: set[int] = set()
    matched_jira: set[int] = set()
    ai_to_jira: dict[int, int] = {}
    for _sim, i, j in pairs:
        if i in matched_ai or j in matched_jira:
            continue
        matched_ai.add(i)
        matched_jira.add(j)
        ai_to_jira[i] = j
    out: list[dict] = []
    for i, ai in enumerate(ai_cases):
        if not isinstance(ai, dict):
            continue
        if i in ai_to_jira:
            je = jira_entries[ai_to_jira[i]]
            out.append(_jira_row_from_entry(je, allowed_priorities))
        else:
            out.append(ai)
    for j, je in enumerate(jira_entries):
        if j in matched_jira:
            continue
        if not isinstance(je, dict):
            continue
        out.append(_jira_row_from_entry(je, allowed_priorities))
    return out


def _tc_similarity(a: dict, b: dict) -> float:
    return SequenceMatcher(None, _tc_signature_norm(a), _tc_signature_norm(b)).ratio()


def _signature_digits_collapsed(tc: dict) -> str:
    return re.sub(r"\d+", "#", _tc_signature_norm(tc))


def _tc_similarity_digit_norm(a: dict, b: dict) -> float:
    return SequenceMatcher(None, _signature_digits_collapsed(a), _signature_digits_collapsed(b)).ratio()


def _tc_similarity_for_merge(a: dict, b: dict) -> float:
    return max(_tc_similarity(a, b), _tc_similarity_digit_norm(a, b))


_SNAPSHOT_SIM_MIN = 0.5


def _best_prior_by_similarity(
    n: dict,
    prev_list: list,
    *,
    allowed_priorities: list[str],
    min_sim: float,
) -> dict | None:
    best = None
    best_sim = 0.0
    for tc in prev_list:
        if not isinstance(tc, dict):
            continue
        p = _norm(tc, default_change_status="unchanged", allowed_priorities=allowed_priorities)
        sim = _tc_similarity_for_merge(n, p)
        if sim > best_sim:
            best_sim = sim
            best = p
    return best if best_sim >= min_sim else None


def _dedupe_similar_test_cases(cases: list[dict]) -> list[dict]:
    out: list[dict] = []
    for tc in cases:
        merged = False
        for i, existing in enumerate(out):
            if _tc_similarity_for_merge(tc, existing) >= _SIMILAR_THRESHOLD:
                out[i]["change_status"] = _merge_change_status(
                    str(out[i].get("change_status") or "unchanged"),
                    str(tc.get("change_status") or "new"),
                )
                out[i]["priority"] = tc.get("priority") or out[i].get("priority")
                jk = _pick_jira_issue_key(tc.get("jira_issue_key"), out[i].get("jira_issue_key"))
                if jk:
                    out[i]["jira_issue_key"] = jk
                sc = _clamp_score_0_10(tc.get("score"))
                if sc is not None:
                    out[i]["score"] = sc
                merged = True
                break
        if not merged:
            out.append(tc)
    return out


_CS_ORDER = ("unchanged", "new", "updated")


def _merge_change_status(a: str, b: str) -> str:
    x = a if a in _CS_ORDER else "unchanged"
    y = b if b in _CS_ORDER else "new"
    return _CS_ORDER[max(_CS_ORDER.index(x), _CS_ORDER.index(y))]


def _dedupe_unchanged_shadowed_by_updated(rows: list[dict]) -> list[dict]:
    if len(rows) < 2:
        return rows
    remove: set[int] = set()
    for i, u in enumerate(rows):
        if str(u.get("change_status") or "") != "updated":
            continue
        ps = u.get("previous_steps")
        if not isinstance(ps, list):
            continue
        pd = str(u.get("description") or "").strip()
        ppt = _steps_norm_tuple(ps)
        for j, st in enumerate(rows):
            if j == i or j in remove:
                continue
            if str(st.get("change_status") or "") != "unchanged":
                continue
            if str(st.get("description") or "").strip() != pd:
                continue
            ss = st.get("steps")
            if not isinstance(ss, list):
                continue
            if _steps_norm_tuple(ss) == ppt:
                remove.add(j)
    if not remove:
        return rows
    return [r for k, r in enumerate(rows) if k not in remove]


def _prior_field(pm: dict, fld: str) -> object:
    return pm.get("preconditions", "") if fld == "preconditions" else pm.get(fld)


def merge_test_cases_with_previous(
    previous: list | None,
    incoming: list,
    *,
    allowed_priorities: list[str],
) -> list:
    prev_list = previous if isinstance(previous, list) else []
    inc_list = incoming if isinstance(incoming, list) else []

    prior_fps: set[tuple] = set()
    for tc in prev_list:
        if isinstance(tc, dict):
            prior_fps.add(
                _tc_fingerprint(_norm(tc, default_change_status="unchanged", allowed_priorities=allowed_priorities)),
            )

    def _has_diff_snap(row: dict) -> bool:
        for k in ("description", "preconditions", "steps", "expected_result"):
            pk = f"previous_{k}"
            if pk not in row:
                continue
            prv = row.get(pk)
            if k == "steps":
                cur = row.get("steps")
                if prv is None or cur is None:
                    continue
                if _steps_norm_tuple(prv) != _steps_norm_tuple(cur):
                    return True
                continue
            cur = row.get(k) if k != "preconditions" else row.get("preconditions", "")
            if prv is None or cur is None:
                continue
            if str(prv).strip() != str(cur).strip():
                return True
        return False

    order: list[tuple] = []
    by_fp: dict[tuple, dict] = {}
    for from_prior, tc in [(True, x) for x in prev_list] + [(False, x) for x in inc_list]:
        if not isinstance(tc, dict):
            continue
        default_cs = "unchanged" if from_prior else "new"
        n = _norm(tc, default_change_status=default_cs, allowed_priorities=allowed_priorities)
        fp = _tc_fingerprint(n)
        if fp not in by_fp:
            merged_sim = False
            for fp2 in order:
                if _tc_similarity_for_merge(n, by_fp[fp2]) >= _SIMILAR_THRESHOLD:
                    prev_cs = str(by_fp[fp2].get("change_status") or "unchanged")
                    inc_cs = str(n.get("change_status") or "new")
                    merged_cs = _merge_change_status(prev_cs, inc_cs)
                    old_row = by_fp.pop(fp2)
                    row = old_row
                    idx = order.index(fp2)
                    order[idx] = fp
                    for fld in ("description", "preconditions", "steps", "expected_result"):
                        old_val = old_row.get(fld) if fld != "preconditions" else old_row.get("preconditions", "")
                        row[f"previous_{fld}"] = old_val
                    row["description"] = n["description"]
                    row["preconditions"] = n.get("preconditions", "")
                    row["steps"] = n["steps"]
                    row["expected_result"] = n.get("expected_result", "")
                    row["priority"] = n.get("priority") or row.get("priority")
                    _merge_jira_row_meta(row, n)
                    jk = _pick_jira_issue_key(n.get("jira_issue_key"), row.get("jira_issue_key"))
                    if jk:
                        row["jira_issue_key"] = jk
                    else:
                        row.pop("jira_issue_key", None)
                    if fp != fp2:
                        row["change_status"] = _merge_change_status(merged_cs, "updated")
                    else:
                        row["change_status"] = merged_cs
                    if "score" in n:
                        row["score"] = n["score"]
                    by_fp[fp] = row
                    merged_sim = True
                    break
            if merged_sim:
                continue
            by_fp[fp] = n
            order.append(fp)
            continue
        prev_cs = str(by_fp[fp].get("change_status") or "unchanged")
        inc_cs = str(n.get("change_status") or "new")
        by_fp[fp]["change_status"] = _merge_change_status(prev_cs, inc_cs)
        by_fp[fp]["priority"] = n.get("priority") or by_fp[fp].get("priority")
        if "score" in n:
            by_fp[fp]["score"] = n["score"]
        _merge_jira_row_meta(by_fp[fp], n)
        jk = _pick_jira_issue_key(n.get("jira_issue_key"), by_fp[fp].get("jira_issue_key"))
        if jk:
            by_fp[fp]["jira_issue_key"] = jk
        else:
            by_fp[fp].pop("jira_issue_key", None)
    for fp in order:
        if fp in prior_fps and by_fp[fp].get("change_status") == "new":
            by_fp[fp]["change_status"] = "unchanged"
    for fp in order:
        if fp not in prior_fps:
            n = by_fp[fp]
            pm = _best_prior_by_similarity(
                n, prev_list, allowed_priorities=allowed_priorities, min_sim=_SIMILAR_THRESHOLD
            )
            cur = str(n.get("change_status") or "new")
            if pm:
                n["change_status"] = _merge_change_status(cur, "updated")
                if not _has_diff_snap(n):
                    for fld in ("description", "preconditions", "steps", "expected_result"):
                        n[f"previous_{fld}"] = _prior_field(pm, fld)
            else:
                if str(cur).lower() == "updated":
                    n["change_status"] = "new"
                else:
                    n["change_status"] = _merge_change_status(cur, "new")
    out_rows = [by_fp[fp] for fp in order]
    for n in out_rows:
        if str(n.get("change_status") or "") == "updated" and not _has_diff_snap(n):
            pm = _best_prior_by_similarity(
                n, prev_list, allowed_priorities=allowed_priorities, min_sim=_SNAPSHOT_SIM_MIN
            )
            if pm:
                for fld in ("description", "preconditions", "steps", "expected_result"):
                    if f"previous_{fld}" in n:
                        continue
                    n[f"previous_{fld}"] = _prior_field(pm, fld)
    for n in out_rows:
        if str(n.get("change_status") or "") == "updated" and not _has_diff_snap(n):
            n["change_status"] = "new"
    out_rows = _dedupe_unchanged_shadowed_by_updated(out_rows)
    return out_rows


def _llm_text_bearer() -> str:
    t = (settings.llm_text_access_token or "").strip()
    return t if t else "lm-studio"


def _llm_vision_bearer() -> str:
    t = (settings.llm_vision_access_token or "").strip()
    return t if t else _llm_text_bearer()


def _llm_base() -> str:
    return (settings.llm_text_url or "").strip().rstrip("/")


def _llm_model() -> str:
    return (settings.llm_text_model or "").strip() or "local-model"


def _llm_target_for_images(
    imgs: list[tuple[str, str, bytes]],
) -> tuple[str, str, str | None]:
    if imgs and (settings.llm_vision_url or "").strip():
        v = (settings.llm_vision_url or "").strip().rstrip("/")
        m = (settings.llm_vision_model or "").strip() or "local-model"
        return v, m, _llm_vision_bearer()
    return _llm_base(), _llm_model(), None


def _json_mode_response() -> dict | None:
    if (os.environ.get("LLM_JSON_MODE") or "").strip().lower() in ("1", "true", "yes", "on"):
        return {"type": "json_object"}
    return None


def _chat(
    base: str,
    model: str,
    messages: list[dict],
    temperature: float,
    *,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    bearer: str | None = None,
) -> str:
    url = f"{base.rstrip('/')}/chat/completions"
    payload: dict = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if response_format is not None:
        payload["response_format"] = response_format
    token = (bearer if bearer is not None else _llm_text_bearer())
    r = requests.post(
        url,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        json=payload,
        timeout=600,
    )
    r.raise_for_status()
    return (r.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""


def strip_test_case_diff_meta(tc: dict) -> dict:
    if not isinstance(tc, dict):
        return tc
    return {k: v for k, v in tc.items() if not str(k).startswith("previous_")}


def _fit_case_scores_0_10(arr: object, n: int) -> list[float] | None:
    if not isinstance(arr, list) or n <= 0:
        return None
    try:
        out = [max(0.0, min(10.0, float(x))) for x in arr[:n]]
    except (TypeError, ValueError):
        return None
    while len(out) < n:
        out.append(5.0)
    return out[:n]


def score_test_cases_0_10(req: dict, cases: list[dict]) -> None:
    if not cases or settings.mock:
        return
    base = _llm_base()
    if not base:
        return
    rq = json.dumps(req, ensure_ascii=False, indent=2)
    clean = [strip_test_case_diff_meta(c) if isinstance(c, dict) else c for c in cases]
    body = json.dumps({"test_cases": clean}, ensure_ascii=False, indent=2)
    user = f"Requirements:\n{rq}\n\nTest cases:\n{body}"
    msgs = [
        {"role": "system", "content": BDD_TEST_CASES_BATCH_SCORING_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    model = _llm_model()
    try:
        raw = _chat(base, model, msgs, 0.05, max_tokens=1024, response_format=_json_mode_response())
        data = _json(raw)
        fitted = _fit_case_scores_0_10(data.get("scores"), len(cases))
        if not fitted:
            return
        for i, c in enumerate(cases):
            c["score"] = round(fitted[i], 1)
    except Exception:
        return


def score_merged_test_cases(req: dict, cases: list[dict]) -> None:
    for c in cases:
        if isinstance(c, dict):
            c.pop("score", None)
    score_test_cases_0_10(req, cases)


def _normalize_generated_case_list(data: dict, allowed_priorities: list[str]) -> list[dict]:
    cases = data.get("test_cases")
    cases = cases if isinstance(cases, list) else []
    out = [_norm(c, allowed_priorities=allowed_priorities) for c in cases if isinstance(c, dict)]
    return _dedupe_similar_test_cases(out)


def _step_keyword(step: str) -> str:
    for prefix in _GH_ALLOWED_PREFIXES:
        if step.startswith(prefix):
            return prefix.strip()
    return ""


def _assertion_is_observable(step: str) -> bool:
    body = re.sub(r"^(Then|And)\s+", "", step, flags=re.I).strip()
    if '"' in body:
        return True
    return bool(_ASSERTION_OBSERVABLE_RE.search(body))


def _generated_case_quality_issues(
    cases: list[dict],
    *,
    min_test_cases: int,
    max_test_cases: int,
    allowed_priorities: list[str],
) -> list[str]:
    issues: list[str] = []
    if len(cases) < min_test_cases:
        issues.append(f"Only {len(cases)} test case(s) remain after normalization; at least {min_test_cases} required.")
    if max_test_cases and len(cases) > max_test_cases:
        issues.append(f"{len(cases)} test case(s) returned; at most {max_test_cases} allowed.")

    seen_desc: set[str] = set()
    seen_sig: set[str] = set()
    allowed_cf = {str(x).casefold() for x in allowed_priorities}
    for idx, tc in enumerate(cases, start=1):
        desc = str(tc.get("description") or "").strip()
        if not desc:
            issues.append(f"Case {idx} has an empty description.")
        desc_key = _WS_NORM.sub(" ", desc).casefold()
        if desc_key and desc_key in seen_desc:
            issues.append(f"Case {idx} duplicates an earlier scenario description.")
        if desc_key:
            seen_desc.add(desc_key)

        pr = str(tc.get("priority") or "").strip()
        if allowed_cf and pr.casefold() not in allowed_cf:
            issues.append(f"Case {idx} priority {pr!r} is not one of the allowed labels.")

        steps = tc.get("steps") if isinstance(tc.get("steps"), list) else []
        steps = [str(x).strip() for x in steps if str(x).strip()]
        if not steps:
            issues.append(f"Case {idx} has no steps.")
            continue
        sig = _tc_signature_norm({"description": desc, "steps": steps})
        if sig in seen_sig:
            issues.append(f"Case {idx} duplicates an earlier scenario's steps.")
        seen_sig.add(sig)

        if not steps[0].startswith("Given "):
            issues.append(f"Case {idx} must start with a Given step.")
        seen_when = False
        seen_then = False
        prev_kw = ""
        for step_no, step in enumerate(steps, start=1):
            kw = _step_keyword(step)
            if not kw:
                issues.append(f"Case {idx} step {step_no} has an invalid Gherkin prefix.")
                continue
            if _STEP_DRAFT_MARKERS_RE.search(step):
                issues.append(
                    f"Case {idx} step {step_no} contains a draft/placeholder or marker; remove it and use a final assertion."
                )
            if kw == "Given" and (seen_when or seen_then):
                issues.append(f"Case {idx} step {step_no} has Given after When/Then.")
            elif kw == "When":
                if seen_then:
                    issues.append(f"Case {idx} step {step_no} has When after Then.")
                seen_when = True
            elif kw == "Then":
                if not seen_when:
                    issues.append(f"Case {idx} step {step_no} has Then before When.")
                seen_then = True
            elif kw == "And" and not prev_kw:
                issues.append(f"Case {idx} step {step_no} starts with And without a prior phase.")

            if seen_then and kw in ("Then", "And"):
                if _VAGUE_ASSERTION_RE.search(step) and not _assertion_is_observable(step):
                    issues.append(f"Case {idx} step {step_no} has a vague assertion without an observable outcome.")
                elif kw == "Then" and not _assertion_is_observable(step):
                    issues.append(f"Case {idx} step {step_no} assertion is not clearly observable.")
            prev_kw = kw or prev_kw
        if not seen_when:
            issues.append(f"Case {idx} is missing a When step.")
        if not seen_then:
            issues.append(f"Case {idx} is missing a Then step.")
        if len(issues) >= 16:
            return issues[:16]
    return issues[:16]


def _quality_retry_user_prompt(
    original_user_prompt: str,
    draft_cases: list[dict],
    issues: list[str],
    *,
    min_test_cases: int,
    max_test_cases: int,
) -> str:
    max_note = "no upper limit" if max_test_cases == 0 else f"at most {max_test_cases}"
    issue_text = "\n".join(f"- {x}" for x in issues[:12])
    draft = json.dumps({"test_cases": draft_cases}, ensure_ascii=False, indent=2)
    return (
        f"{original_user_prompt}\n\n"
        "Quality review found blocking issues in the draft below. Regenerate the full JSON object, fixing these issues "
        "without adding unsupported behavior.\n\n"
        f"Required count: at least {min_test_cases}, {max_note}.\n"
        f"Issues:\n{issue_text}\n\n"
        f"Draft to improve:\n{draft}\n\n"
        "Return only the corrected JSON object."
    )


def _priority_guidance(allowed: list[str], paste_mode: bool) -> str:
    plist = ", ".join(allowed)
    if paste_mode:
        return (
            f'Each test case MUST include "priority" as exactly one of: {plist}. '
            "Pick Highest for must-have paths and critical risk; High for important paths; Medium for typical coverage; "
            "Low/Lowest for nice-to-have or edge-only. "
            "Paste mode: use only these exact priority strings (no synonyms)."
        )
    if len(allowed) >= 2:
        return (
            f'Each test case MUST include "priority" as exactly one of: {plist}. '
            f'Use "{allowed[0]}" for must-have and critical risk; "{allowed[-1]}" for nice-to-have or edge-only; '
            "intermediate labels for medium severity. Use only these exact strings (no synonyms)."
        )
    if len(allowed) == 1:
        return f'Each test case MUST set "priority" to "{allowed[0]}".'
    return f'Each test case MUST include "priority" as exactly one of: {plist}.'


def build_generation_user_prompt(
    req: dict,
    prev: dict | None,
    *,
    paste_mode: bool,
    existing_jira_tests: list[dict] | None,
    allowed_priorities: list[str],
    min_test_cases: int,
    max_test_cases: int,
) -> str:
    prior = (
        "Prior:\n"
        + json.dumps(
            {"requirements": prev.get("requirements"), "test_cases": prev.get("test_cases")},
            ensure_ascii=False,
            indent=2,
        )
        if prev
        else "No prior memory."
    )
    ej = [x for x in (existing_jira_tests or []) if isinstance(x, dict)]
    linked_block = ""
    if ej:
        linked_block = (
            "Linked JIRA tests already on this requirement (reference only—fill gaps, improve clarity, avoid redundant "
            "duplicate scenarios where the idea is already covered):\n"
            + json.dumps(
                [
                    {
                        "issue_key": x.get("issue_key"),
                        "summary": x.get("summary"),
                        "steps": (x.get("test_case") or {}).get("steps")
                        if isinstance(x.get("test_case"), dict)
                        else [],
                    }
                    for x in ej
                ],
                ensure_ascii=False,
                indent=2,
            )
            + "\n\n"
        )
    max_note = "no upper limit" if max_test_cases == 0 else f"at most {max_test_cases}"
    pri_line = _priority_guidance(allowed_priorities, paste_mode)
    parts = [
        f"Requirements:\n{json.dumps(req, ensure_ascii=False, indent=2)}",
        linked_block + prior,
        f"Task: Build test_cases per system rules from Requirements and Prior / linked tests when present. {pri_line}"
        f"Aim for strong BDD coverage: mix happy path with edge, negative, and alternative scenarios where the text supports them (not only trivial happy cases). "
        f"Return at least {min_test_cases} test case(s) and {max_note} total in test_cases. "
        "Use correct English grammar in every description and step line. "
        "Return only the JSON object.",
    ]
    return "\n\n".join(parts)


def build_multimodal_user_content(text: str, images: list[tuple[str, str, bytes]]) -> str | list:
    if not images:
        return text
    parts: list[dict] = [{"type": "text", "text": text}]
    for fn, mime, data in images:
        b64 = base64.b64encode(data).decode("ascii")
        if mime == "application/pdf":
            name = (fn or "document.pdf").strip() or "document.pdf"
            if "/" in name:
                name = name.rsplit("/", 1)[-1]
            parts.append(
                {
                    "type": "file",
                    "file": {
                        "filename": name,
                        "file_data": f"data:application/pdf;base64,{b64}",
                    },
                }
            )
        else:
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return parts


async def generate_test_cases(
    req: dict[str, str],
    prev: dict | None,
    *,
    allowed_priorities: list[str],
    min_test_cases: int = 1,
    max_test_cases: int = 10,
    paste_mode: bool = False,
    existing_jira_tests: list[dict] | None = None,
    requirement_images: list[tuple[str, str, bytes]] | None = None,
) -> list[dict]:
    user = build_generation_user_prompt(
        req,
        prev,
        paste_mode=paste_mode,
        existing_jira_tests=existing_jira_tests,
        allowed_priorities=allowed_priorities,
        min_test_cases=min_test_cases,
        max_test_cases=max_test_cases,
    )
    imgs = requirement_images or []
    if imgs:
        user += (
            "\n\n### Images and PDFs (same message, after this text)\n"
            "One or more images and/or PDFs follow as separate content parts. Generate test cases from the **Requirements/Prior/linked** text **together** with those attachments: "
            "cover UI flows, labels, and states shown in images or PDFs when they match the requirement scope. "
            "If there were no attachments, this paragraph would not apply—text-only runs use only the sections above."
        )
    base, model, bear = _llm_target_for_images(imgs)
    if not base:
        raise ValueError("LLM_TEXT_URL is not set in .env")
    user_content = build_multimodal_user_content(user, imgs)
    system_content = (
        BDD_TEST_CASE_GENERATION_SYSTEM_PROMPT
        if not imgs
        else f"{BDD_TEST_CASE_GENERATION_SYSTEM_PROMPT}\n\n{BDD_TEST_GENERATION_WITH_ATTACHMENTS_SUPPLEMENT_PROMPT}"
    )
    msgs = [{"role": "system", "content": system_content}, {"role": "user", "content": user_content}]
    response_format = None if imgs else _json_mode_response()
    raw = await asyncio.to_thread(
        _chat, base, model, msgs, 0.15, response_format=response_format, bearer=bear
    )
    data = _json(raw)
    out = _normalize_generated_case_list(data, allowed_priorities)
    issues = _generated_case_quality_issues(
        out,
        min_test_cases=min_test_cases,
        max_test_cases=max_test_cases,
        allowed_priorities=allowed_priorities,
    )
    if issues:
        retry_user = _quality_retry_user_prompt(
            user,
            out,
            issues,
            min_test_cases=min_test_cases,
            max_test_cases=max_test_cases,
        )
        retry_content = build_multimodal_user_content(retry_user, imgs)
        retry_msgs = [{"role": "system", "content": system_content}, {"role": "user", "content": retry_content}]
        try:
            retry_raw = await asyncio.to_thread(
                _chat,
                base,
                model,
                retry_msgs,
                0.08,
                response_format=response_format,
                bearer=bear,
            )
            retry_out = _normalize_generated_case_list(_json(retry_raw), allowed_priorities)
            retry_issues = _generated_case_quality_issues(
                retry_out,
                min_test_cases=min_test_cases,
                max_test_cases=max_test_cases,
                allowed_priorities=allowed_priorities,
            )
            if retry_out and len(retry_issues) < len(issues):
                out = retry_out
        except Exception:
            pass
    return out[:max_test_cases] if max_test_cases else out


def _strip_code_fence(s: str) -> str:
    t = (s or "").strip()
    m = re.match(r"^```(?:\w+)?\s*\n?([\s\S]*?)```\s*$", t)
    return m.group(1).rstrip() if m else t


async def generate_automation_skeleton(test_case: dict, language: str, framework: str) -> str:
    if settings.mock:
        desc = str((test_case or {}).get("description") or "scenario").strip() or "scenario"
        return (
            f"# Automation skeleton (mock mode — no LLM)\n"
            f"# Stack: {language} + {framework}\n"
            f"# Scenario: {desc[:200]}\n"
            f"def test_placeholder():\n    raise NotImplementedError('TODO')\n"
        )
    base = _llm_base()
    if not base:
        raise ValueError("LLM_TEXT_URL is not set in .env")
    tc_in = test_case if isinstance(test_case, dict) else {}
    payload = json.dumps(tc_in, ensure_ascii=False, indent=2)
    user = (
        f"Programming language (lowercase id): {language}\n"
        f"Test framework (lowercase id): {framework}\n\n"
        f"Test case JSON:\n{payload}"
    )
    model = _llm_model()
    msgs = [
        {"role": "system", "content": SKELETON_TEST_CODE_GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    raw = await asyncio.to_thread(_chat, base, model, msgs, 0.2)
    return _strip_code_fence(raw.strip())


def llm_chat_completion(
    system: str, user: str, *, temperature: float = 0.1, max_tokens: int = 12_000
) -> str:
    b = _llm_base()
    if not b:
        return ""
    m = _llm_model()
    return _chat(
        b,
        m,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature,
        max_tokens=max_tokens,
    )


def parse_llm_json_object(raw: str) -> Any:
    s = (raw or "").strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", s, re.I)
    if m:
        s = m.group(1).strip()
    if not s:
        raise ValueError("empty")
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    a, b = s.find("{"), s.rfind("}")
    if 0 <= a < b:
        return json.loads(s[a : b + 1])
    a2, b2 = s.find("["), s.rfind("]")
    if 0 <= a2 < b2:
        return json.loads(s[a2 : b2 + 1])
    raise ValueError("not valid json")


def spike_post_run_analysis(
    title: str, url: str, ok: bool, steps: list[dict], log_tail: str
) -> str:
    if settings.mock or not _llm_base():
        return ""
    try:
        body = json.dumps(
            {
                "title": title,
                "url": url,
                "pass": ok,
                "steps": steps[:200],
            },
            ensure_ascii=False,
        )[:24_000]
        u = f"Data:\n{body}\n\nLog tail:\n{log_tail[:8000]}"
        return _chat(
            _llm_base(),
            _llm_model(),
            [
                {"role": "system", "content": UI_SPIKE_TEST_RUN_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": u},
            ],
            0.15,
            max_tokens=1200,
        ).strip()
    except Exception:  # noqa: BLE001
        return ""
