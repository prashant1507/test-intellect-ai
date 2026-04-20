from __future__ import annotations

import asyncio
import json
import re
from difflib import SequenceMatcher

import requests

from settings import settings


def _paste_priority_list() -> list[str]:
    """Labels from PASTE_MODE_PRIORITIES (and default five if unset). Used for Paste mode, and for JIRA mode when no Test Project / JIRA fetch."""
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

SYS = """
You are a senior QA engineer. Derive test cases from the **Requirements** (title + description) and from **Prior** and **Linked JIRA tests** when those sections appear in the user message.

Do not invent behavior, integrations, or concrete values that appear nowhere in the sections that are actually present.

Traceability: Every scenario must tie to the Requirements **or** to Prior / linked tests when present. Prefer wording from the requirement or from included sections.

Depth and variety (within the budget of min/max test cases from the Task):
- Include a primary happy path when the requirement describes success.
- Add focused scenarios for: alternative paths or branches named in the text; state/setup differences (e.g. role, flag, mode) if mentioned; validation and "must not" behavior; empty, missing, or invalid input when the requirement implies rejection or guarding; boundary or edge behavior when min/max, optional/required, or "at least one" style rules appear; recovery or idempotency only if described.
- Prefer distinct scenarios over repeating the same flow with tiny wording changes. Do not emit two test cases that differ only by one word in the title or by trivial synonym when the steps are the same or nearly the same. When space is tight, prioritize one strong edge or negative case over duplicate happy paths.

Gherkin (strict): The scenario lives ONLY in "steps" — an array of single lines in order: Given, then And*, then When, then And*, then Then, then And*. Allowed prefixes only: "Given ", "And ", "When ", "Then " (case-sensitive). "preconditions" and "expected_result" must be "".

Atomic steps: Each line is ONE condition, ONE action, or ONE outcome. Never join two with natural-language "and" or commas inside the same line (wrong: "Given The user is logged in and on a protected page"). Use separate lines: "Given The user is logged in" then "And The user is on a protected dashboard page". Same for When/Then: split multiple actions or assertions onto extra "And" lines.

Quality: One clause per array element (never "Then A And B" in one string — split to two lines). Steps must be concrete and testable (who/what/where in Given/When; observable outcome in Then). Use "And" only to continue the same phase (more context, more actions, or more assertions), not to smuggle unrelated checks.

JSON only, no markdown. Top-level key "test_cases" only. Each item: description, preconditions "", steps, expected_result "", change_status, priority — do not include an "id" field. change_status: new if no prior; else new/updated/unchanged vs Prior. If Prior already has a scenario for the same test idea and Requirements only changed concrete values (limits, counts, durations, labels), treat it as the same scenario: set change_status to **updated**, align description and steps with the new values, and do not add a duplicate "new" scenario for the same idea. priority: business importance for triage (exact label will be given in the Task).

Example steps: ["Given …", "When …", "Then …", "And …"]

Grammar and style (English):
- Use correct grammar: subject–verb agreement, proper articles (a/an/the), and standard word order in every description and step.
- Scenario "description": a short, clear title (not a Gherkin line). Capitalize the first word; no typos; optional ending period only if it is a full sentence.
- Steps: present tense. Prefer "The user <verb>s …" or "The system <verb>s …" for clarity; be consistent within one scenario. After "Given "/"When "/"Then "/"And ", write a complete clause (not a bare noun phrase unless the requirement uses that form).
- Avoid run-ons; one idea per line. Use commas only where they follow normal English punctuation rules.
"""


def _cap_first_line(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    return s[0].upper() + s[1:]


def _cap_gherkin_line(s: str) -> str:
    """Given/When/Then/And + capitalize first letter of the first word after the keyword."""
    s = s.strip()
    if not s:
        return s
    m = _GH_PREFIX.match(s)
    if not m:
        return _cap_first_line(s)
    kw_raw, rest = m.group(1), m.group(2)
    kw = _GH_KEYWORD.get(kw_raw.lower(), kw_raw[0].upper() + kw_raw[1:].lower())
    rest = rest.lstrip()
    if not rest:
        return kw
    j = 0
    while j < len(rest) and not rest[j].isspace():
        j += 1
    first_word, after = rest[:j], rest[j:]
    if first_word and first_word[0].isalpha():
        first_word = first_word[0].upper() + first_word[1:]
    return f"{kw} {first_word}{after}"


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
    """Split prose like 'Given A and B' into Given + And lines (no 'and' inside one step)."""
    s = line.strip()
    if not s:
        return []
    m = _GH_PREFIX.match(s)
    if not m:
        return [line]
    kw_raw, rest = m.group(1), m.group(2)
    kw = _GH_KEYWORD.get(kw_raw.lower(), kw_raw[0].upper() + kw_raw[1:].lower())
    rest = rest.strip()
    if not rest:
        return [line]
    parts = _AND_SPLIT.split(rest)
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


def _split_natural_and_in_steps(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        out.extend(_split_natural_and_in_line(raw))
    return out


_ORPHAN_AND = re.compile(r"^And\s+(\S+)\s*$", re.I)


def _merge_orphan_and_words(lines: list[str]) -> list[str]:
    """Join 'And Password'-style fragments left after bad splits (e.g. 'email and password')."""
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
    s = s.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", s, re.I)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        a, b = s.find("{"), s.rfind("}")
        if 0 <= a < b:
            return json.loads(s[a : b + 1])
        raise


def _pick_jira_issue_key(*vals: object) -> str | None:
    for v in vals:
        s = str(v or "").strip().upper()
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

    def _collapse_lines(s: str) -> str:
        return "\n".join(_WS_NORM.sub(" ", ln).strip() for ln in s.split("\n"))

    if c.get("jira_existing"):
        pr = str(c.get("priority") or "").strip()
        prio = pr if pr else _norm_priority(None, allowed_priorities)
    else:
        prio = _norm_priority(c.get("priority"), allowed_priorities)
    out = {
        "description": _collapse_lines(_cap_lines(str(c.get("description") or ""))),
        "preconditions": _collapse_lines(_cap_lines(pre)),
        "steps": st,
        "expected_result": _collapse_lines(_cap_lines(exp)),
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
    sc = c.get("score")
    if isinstance(sc, (int, float)) and not isinstance(sc, bool):
        out["score"] = round(max(0.0, min(10.0, float(sc))), 1)
    return out


def _steps_norm_tuple(raw_steps: object) -> tuple[str, ...]:
    steps = raw_steps if isinstance(raw_steps, list) else []
    return tuple(_WS_NORM.sub(" ", str(x).strip()).casefold() for x in steps)


def _tc_fingerprint(n: dict) -> tuple:
    d = _WS_NORM.sub(" ", str(n.get("description") or "").strip()).casefold()
    return (d, _steps_norm_tuple(n.get("steps")))


def _tc_signature_norm(tc: dict) -> str:
    d = _WS_NORM.sub(" ", str(tc.get("description") or "").strip()).casefold()
    lines = list(_steps_norm_tuple(tc.get("steps")))
    return d + "\n" + "\n".join(lines)


_SIMILAR_THRESHOLD = 0.92
_JIRA_EXISTING_MATCH_THRESHOLD = 0.88


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
            out.append(row)
        else:
            out.append(ai)
    for j, je in enumerate(jira_entries):
        if j in matched_jira:
            continue
        if not isinstance(je, dict):
            continue
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
        out.append(row)
    return out


def _tc_similarity(a: dict, b: dict) -> float:
    return SequenceMatcher(None, _tc_signature_norm(a), _tc_signature_norm(b)).ratio()


def _signature_digits_collapsed(tc: dict) -> str:
    d = _WS_NORM.sub(" ", str(tc.get("description") or "").strip()).casefold()
    lines = list(_steps_norm_tuple(tc.get("steps")))
    raw = d + "\n" + "\n".join(lines)
    return re.sub(r"\d+", "#", raw)


def _tc_similarity_digit_norm(a: dict, b: dict) -> float:
    return SequenceMatcher(None, _signature_digits_collapsed(a), _signature_digits_collapsed(b)).ratio()


def _tc_similarity_for_merge(a: dict, b: dict) -> float:
    return max(_tc_similarity(a, b), _tc_similarity_digit_norm(a, b))


def _best_prior_similarity(
    n: dict,
    prev_list: list,
    *,
    allowed_priorities: list[str],
) -> float:
    """Max similarity of `n` to any normalized prior test case (0 if no priors)."""
    best = 0.0
    for tc in prev_list:
        if not isinstance(tc, dict):
            continue
        p = _norm(tc, default_change_status="unchanged", allowed_priorities=allowed_priorities)
        sim = _tc_similarity_for_merge(n, p)
        if sim > best:
            best = sim
    return best


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
                sc = tc.get("score")
                if isinstance(sc, (int, float)) and not isinstance(sc, bool):
                    out[i]["score"] = round(max(0.0, min(10.0, float(sc))), 1)
                merged = True
                break
        if not merged:
            out.append(tc)
    return out


_CS_ORDER = ("unchanged", "new", "updated")


def _merge_change_status(a: str, b: str) -> str:
    """Pick the stronger label when the same scenario appears twice (updated > new > unchanged)."""
    x = a if a in _CS_ORDER else "unchanged"
    y = b if b in _CS_ORDER else "new"
    return _CS_ORDER[max(_CS_ORDER.index(x), _CS_ORDER.index(y))]


def merge_test_cases_with_previous(
    previous: list | None,
    incoming: list,
    *,
    allowed_priorities: list[str],
) -> list:
    """
    Append newly generated cases to prior memory without losing old ones.
    Order: previous first, then incoming; same description+steps merge into one row with a combined change_status.
    Stored rows without change_status are treated as unchanged; the LLM wrongly tagging an existing scenario as new is demoted.
    If an incoming scenario differs from prior fingerprints but is still highly similar (>= threshold) to a prior
    scenario — including when only numbers changed (digit-collapsed signature) — label it as updated instead of new.
    """
    prev_list = previous if isinstance(previous, list) else []
    inc_list = incoming if isinstance(incoming, list) else []

    prior_fps: set[tuple] = set()
    for tc in prev_list:
        if isinstance(tc, dict):
            prior_fps.add(
                _tc_fingerprint(_norm(tc, default_change_status="unchanged", allowed_priorities=allowed_priorities)),
            )

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
                    row = by_fp.pop(fp2)
                    idx = order.index(fp2)
                    order[idx] = fp
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
            sim = _best_prior_similarity(n, prev_list, allowed_priorities=allowed_priorities)
            cur = str(n.get("change_status") or "new")
            if prev_list and sim >= _SIMILAR_THRESHOLD:
                n["change_status"] = _merge_change_status(cur, "updated")
            else:
                n["change_status"] = _merge_change_status(cur, "new")
    return [by_fp[fp] for fp in order]


def _llm_bearer() -> str:
    t = (settings.llm_access_token or "").strip()
    return t if t else "lm-studio"


def _chat(
    base: str,
    model: str,
    messages: list[dict],
    temperature: float,
    *,
    max_tokens: int | None = None,
    response_format: dict | None = None,
) -> str:
    url = f"{base.rstrip('/')}/chat/completions"
    payload: dict = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if response_format is not None:
        payload["response_format"] = response_format
    r = requests.post(
        url,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_llm_bearer()}"},
        json=payload,
        timeout=600,
    )
    r.raise_for_status()
    return (r.json().get("choices") or [{}])[0].get("message", {}).get("content") or ""


_SCORE_EACH_SYS = """Reply JSON only: {"scores":[number,...]}. Exactly as many numbers as test cases in the user message, same order. Each 0-10 (decimals allowed). Judge traceability to requirements, Gherkin structure, and clarity."""

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
    base = settings.llm_url.rstrip("/")
    if not base:
        return
    rq = json.dumps(req, ensure_ascii=False, indent=2)
    body = json.dumps({"test_cases": cases}, ensure_ascii=False, indent=2)
    user = f"Requirements:\n{rq}\n\nTest cases:\n{body}"
    msgs = [{"role": "system", "content": _SCORE_EACH_SYS}, {"role": "user", "content": user}]
    model = (settings.llm_model or "").strip() or "local-model"
    try:
        raw = _chat(base, model, msgs, 0.05, max_tokens=1024)
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


async def generate_test_cases(
    req: dict[str, str],
    prev: dict | None,
    *,
    allowed_priorities: list[str],
    min_test_cases: int = 1,
    max_test_cases: int = 10,
    paste_mode: bool = False,
    existing_jira_tests: list[dict] | None = None,
) -> list[dict]:
    base = settings.llm_url.rstrip("/")
    if not base:
        raise ValueError("LLM_URL is not set in .env")
    user = build_generation_user_prompt(
        req,
        prev,
        paste_mode=paste_mode,
        existing_jira_tests=existing_jira_tests,
        allowed_priorities=allowed_priorities,
        min_test_cases=min_test_cases,
        max_test_cases=max_test_cases,
    )
    model = (settings.llm_model or "").strip() or "local-model"
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": user}]
    raw = await asyncio.to_thread(_chat, base, model, msgs, 0.15)
    data = _json(raw)
    cases = data.get("test_cases")
    cases = cases if isinstance(cases, list) else []
    out = [_norm(c, allowed_priorities=allowed_priorities) for c in cases if isinstance(c, dict)]
    out = _dedupe_similar_test_cases(out)
    return out[:max_test_cases] if max_test_cases else out


_AUTOMATION_SKELETON_SYS = """
You are an expert test automation engineer. You receive one JSON test case (BDD-style steps or classic steps).

Task: Output a single **skeleton** test file for the requested programming language and test framework.
- Map Given/When/Then steps into comments or structured placeholders; use TODO comments for unknown URLs, selectors, or credentials.
- Do not invent product-specific URLs or selectors; use example.com or obvious placeholders where needed.
- No explanation prose before or after the code. No markdown fences wrapping the answer unless the language convention requires nothing else (prefer raw source only).
- Imports and project structure should match common conventions for that stack (e.g. pytest-playwright for Python+Playwright if typical).
""".strip()


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
    base = settings.llm_url.rstrip("/")
    if not base:
        raise ValueError("LLM_URL is not set in .env")
    tc_in = test_case if isinstance(test_case, dict) else {}
    payload = json.dumps(tc_in, ensure_ascii=False, indent=2)
    user = (
        f"Programming language (lowercase id): {language}\n"
        f"Test framework (lowercase id): {framework}\n\n"
        f"Test case JSON:\n{payload}"
    )
    model = (settings.llm_model or "").strip() or "local-model"
    msgs = [{"role": "system", "content": _AUTOMATION_SKELETON_SYS}, {"role": "user", "content": user}]
    raw = await asyncio.to_thread(_chat, base, model, msgs, 0.2)
    return _strip_code_fence(raw.strip())
