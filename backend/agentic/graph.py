from __future__ import annotations

import json
import os
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ai_client import (
    _chat,
    _json as parse_llm_json,
    _norm,
    build_generation_user_prompt,
    score_test_cases_0_10,
)
from settings import settings

from .models import GenerationEnvelope, TestCaseItem, ValidatorResult

AGG_MIN = 3.5
DIM_MIN = 2
STRONG_AGG = 4.25
STRONG_DIM = 4

GEN_SYS = """Senior QA. Output JSON only: {"test_cases":[...]}. Each case: description, preconditions "", steps (Given/When/Then/And lines per app rules), expected_result "", change_status, priority. Trace every scenario to the requirement. No invented behavior. English, concrete steps."""

VAL_SYS = """You score BDD test cases vs requirements. Reply JSON only:
{"dimensions":{"traceability":0-5,"coverage":0-5,"gherkin_structure":0-5,"concreteness":0-5,"non_redundancy":0-5},"issues":[],"must_fix":[],"suggestions":[]}
- dimensions: 0-5 each.
- issues / must_fix: ONLY blocking defects (wrong trace to requirement, broken Gherkin, missing required coverage, misleading steps). These trigger revision.
- suggestions: optional polish (wording, extra scenarios, Remember Me); never blocking. Put nitpicks here, NOT in issues/must_fix, if the suite is already acceptable.
- If every dimension is >= 4 and the suite is broadly correct, prefer empty issues and must_fix; use suggestions for minor improvements."""

SUG_GEN_SYS = """Output JSON only: {"test_cases":[...]}. Each item: description, preconditions "", expected_result "", change_status "new", priority.
steps MUST be a JSON array of strings, one string per line, e.g. ["Given ...","When ...","Then ..."]. Never put all steps in one string. One scenario per suggestion; trace only to requirements."""

RANK_SYS = """Reply JSON only: {"base_scores":[number,...],"candidate_scores":[number,...]}
Each value is 0-5 overall quality (traceability, Gherkin, clarity).
CRITICAL: base_scores must contain EXACTLY as many numbers as BASE_SCENARIOS (same count). candidate_scores must contain EXACTLY as many numbers as CANDIDATE_SCENARIOS. Count carefully."""


def _json_mode_response() -> dict | None:
    if (os.environ.get("LLM_JSON_MODE") or "").strip().lower() in ("1", "true", "yes"):
        return {"type": "json_object"}
    return None


def _llm_chat(
    messages: list[dict],
    *,
    temperature: float,
    max_tokens: int,
    json_response_format: bool = False,
) -> str:
    base = settings.llm_url.rstrip("/")
    if not base:
        raise ValueError("LLM_URL is not set in .env")
    model = (settings.llm_model or "").strip() or "local-model"
    fmt = _json_mode_response() if json_response_format else None
    return _chat(base, model, messages, temperature, max_tokens=max_tokens, response_format=fmt)


def _coerce_steps_value(steps: object) -> list[str]:
    if isinstance(steps, list):
        return [str(x).strip() for x in steps if str(x).strip()]
    if not isinstance(steps, str):
        return []
    t = steps.strip()
    if not t:
        return []
    lines = [x.strip() for x in re.split(r"\r?\n", t) if x.strip()]
    if len(lines) > 1:
        return lines
    line = lines[0] if lines else t
    pat = re.compile(r"\b(Given|When|Then|And)\s+", re.IGNORECASE)
    ms = list(pat.finditer(line))
    if len(ms) <= 1:
        return [line]
    out: list[str] = []
    for i, m in enumerate(ms):
        start = m.start()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
        chunk = line[start:end].strip()
        if chunk:
            out.append(chunk)
    return out if out else [line]


def _coerce_raw_case(c: object) -> dict:
    if not isinstance(c, dict):
        return {}
    d = {k: v for k, v in c.items()}
    d["steps"] = _coerce_steps_value(d.get("steps"))
    for k in ("description", "preconditions", "expected_result", "change_status", "priority"):
        if k in d and d[k] is not None and not isinstance(d[k], str):
            d[k] = str(d[k])
    return d


def _fit_scores(arr: object, n: int) -> list[float] | None:
    if n <= 0 or not isinstance(arr, list):
        return None
    try:
        out = [float(x) for x in arr[:n]]
    except (TypeError, ValueError):
        return None
    while len(out) < n:
        out.append(3.0)
    return out[:n]


class AgentState(TypedDict, total=False):
    requirements: dict
    generation_prompt: str
    allowed_priorities: list[str]
    min_test_cases: int
    max_test_cases: int
    max_rounds: int
    generation: int
    feedback: str
    raw: str
    envelope: GenerationEnvelope | None
    parse_error: str | None
    error: str | None
    validator: ValidatorResult | None
    validation_passed: bool | None
    suggestion_swap: dict | None
    final_cases: list[dict]


def _max_rounds_cap(state: AgentState) -> int:
    return int(state.get("max_rounds") or 3)


def _passed(vr: ValidatorResult) -> bool:
    if vr.aggregate < AGG_MIN or vr.min_dimension() < DIM_MIN:
        return False
    if vr.aggregate >= STRONG_AGG and vr.min_dimension() >= STRONG_DIM:
        return True
    if any((x or "").strip() for x in vr.issues):
        return False
    if any((x or "").strip() for x in vr.must_fix):
        return False
    return True


def _bounds_ok(n: int, state: AgentState) -> bool:
    lo = int(state.get("min_test_cases") or 1)
    hi = int(state.get("max_test_cases") or 10)
    if n < lo:
        return False
    if hi and n > hi:
        return False
    return True


def generate_node(state: AgentState) -> dict:
    gp = (state.get("generation_prompt") or "").strip()
    fb = (state.get("feedback") or "").strip()
    if not gp:
        req = json.dumps(state["requirements"], ensure_ascii=False, indent=2)
        lo = int(state.get("min_test_cases") or 1)
        hi = int(state.get("max_test_cases") or 10)
        hi_note = "no upper limit" if not hi else f"at most {hi}"
        user = (
            f"Requirements:\n{req}\n\n"
            f"Task: at least {lo} test case(s), {hi_note} total. "
            f"Priorities exactly one of: {', '.join(state['allowed_priorities'])}.\n"
        )
    else:
        user = gp
    if fb:
        user += f"\n\nRevise using this feedback (do not repeat the same mistakes):\n{fb}\n"
    msgs = [{"role": "system", "content": GEN_SYS}, {"role": "user", "content": user}]
    raw = _llm_chat(msgs, temperature=0.12, max_tokens=4096)
    g = (state.get("generation") or 0) + 1
    return {"raw": raw, "generation": g}


def parse_node(state: AgentState) -> dict:
    raw = (state.get("raw") or "").strip()
    mx = _max_rounds_cap(state)
    gen = int(state.get("generation") or 0)
    try:
        data = parse_llm_json(raw)
        tc = data.get("test_cases")
        if not isinstance(tc, list):
            raise ValueError("test_cases must be a list")
        fixed = [_coerce_raw_case(x) for x in tc if isinstance(x, dict)]
        env = GenerationEnvelope.model_validate({"test_cases": fixed})
        if not _bounds_ok(len(env.test_cases), state):
            raise ValueError("test_cases count outside min/max")
        return {"envelope": env, "parse_error": None, "error": None}
    except Exception as e:
        err = str(e)
        if gen >= mx:
            return {"envelope": None, "parse_error": err, "error": err}
        return {
            "envelope": None,
            "parse_error": err,
            "feedback": f"Invalid output: {err}. Return valid JSON with test_cases only.",
        }


def score_node(state: AgentState) -> dict:
    env = state["envelope"]
    assert env is not None
    req = json.dumps(state["requirements"], ensure_ascii=False, indent=2)
    body = json.dumps({"test_cases": [c.model_dump() for c in env.test_cases]}, ensure_ascii=False, indent=2)
    user = f"Requirements:\n{req}\n\nGenerated:\n{body}\n\nReturn only the scoring JSON."
    msgs = [{"role": "system", "content": VAL_SYS}, {"role": "user", "content": user}]
    raw = _llm_chat(msgs, temperature=0.08, max_tokens=1024, json_response_format=True)
    data = parse_llm_json(raw)
    vr = ValidatorResult.model_validate(data)
    mx = _max_rounds_cap(state)
    gen = int(state.get("generation") or 0)
    ok = _passed(vr)
    if ok:
        return {"validator": vr, "validation_passed": True}
    if gen >= mx:
        return {"validator": vr, "validation_passed": False}
    fb_parts: list[str] = []
    fb_parts.extend(vr.must_fix[:8])
    fb_parts.extend(vr.issues[:6])
    fb_parts.append(
        f"Scores: aggregate={vr.aggregate:.2f} (need >={AGG_MIN}), min_dim={vr.min_dimension()} (need >={DIM_MIN}). "
        "Fix all items above; output must have no remaining issues."
    )
    return {"validator": vr, "validation_passed": False, "feedback": "\n".join(fb_parts)}


def merge_suggestions_node(state: AgentState) -> dict:
    def fail(reason: str) -> dict:
        return {"suggestion_swap": {"done": False, "reason": reason}}

    vr = state.get("validator")
    env = state.get("envelope")
    if not vr or not env or not _passed(vr):
        return fail("skipped")
    sugs = [s for s in (vr.suggestions or []) if (s or "").strip()]
    if not sugs:
        return fail("no_suggestions")
    allowed = state.get("allowed_priorities") or ["Medium"]
    req = json.dumps(state["requirements"], ensure_ascii=False, indent=2)
    sug_block = "\n".join(f"- {s}" for s in sugs)
    pri = ", ".join(allowed)
    user = (
        f"Requirements:\n{req}\n\n"
        f"Create exactly {len(sugs)} test case(s), one per suggestion:\n{sug_block}\n"
        f"Priorities exactly one of: {pri}.\nReturn only JSON with key test_cases."
    )
    msgs = [{"role": "system", "content": SUG_GEN_SYS}, {"role": "user", "content": user}]
    try:
        raw = _llm_chat(msgs, temperature=0.12, max_tokens=4096)
        data = parse_llm_json(raw)
        tc = data.get("test_cases")
        if not isinstance(tc, list) or not tc:
            return fail("candidate_generation_empty")
        raw_cases = [_coerce_raw_case(x) for x in tc[: len(sugs)]]
        env_c = GenerationEnvelope.model_validate({"test_cases": raw_cases})
    except Exception as e:
        return fail(f"candidate_generation_failed: {e!s}"[:200])
    candidates_norm = [_norm(c.model_dump(), allowed_priorities=allowed) for c in env_c.test_cases]
    base_norm = [_norm(c.model_dump(), allowed_priorities=allowed) for c in env.test_cases]
    hi = int(state.get("max_test_cases") or 0)
    if hi:
        base_norm = base_norm[:hi]
    if not base_norm or not candidates_norm:
        return fail("empty_base_or_candidates")
    nb, nc = len(base_norm), len(candidates_norm)
    user2 = (
        f"Requirements:\n{req}\n\n"
        f"BASE_SCENARIOS ({nb} items, indices 0..{nb - 1}):\n{json.dumps(base_norm, ensure_ascii=False, indent=2)}\n\n"
        f"CANDIDATE_SCENARIOS ({nc} items, indices 0..{nc - 1}):\n{json.dumps(candidates_norm, ensure_ascii=False, indent=2)}\n\n"
        f"Return only JSON with base_scores: array of exactly {nb} numbers, candidate_scores: array of exactly {nc} numbers."
    )
    msgs2 = [{"role": "system", "content": RANK_SYS}, {"role": "user", "content": user2}]
    try:
        raw2 = _llm_chat(msgs2, temperature=0.05, max_tokens=1024, json_response_format=True)
        rank = parse_llm_json(raw2)
        bs = rank.get("base_scores")
        cs = rank.get("candidate_scores")
        bs_f = _fit_scores(bs, nb)
        cs_f = _fit_scores(cs, nc)
        if bs_f is None or cs_f is None:
            return fail("ranking_parse_failed")
    except Exception as e:
        return fail(f"ranking_failed: {e!s}"[:200])
    wi = min(range(nb), key=lambda i: bs_f[i])
    ci = max(range(nc), key=lambda i: cs_f[i])
    if cs_f[ci] <= bs_f[wi]:
        return {
            "suggestion_swap": {
                "done": False,
                "reason": "best candidate did not beat weakest base",
                "weakest_base_index": wi,
                "best_candidate_index": ci,
                "base_score": bs_f[wi],
                "candidate_score": cs_f[ci],
            }
        }
    merged = list(base_norm)
    merged[wi] = candidates_norm[ci]
    items = [TestCaseItem.model_validate(x) for x in merged]
    return {
        "envelope": GenerationEnvelope(test_cases=items),
        "suggestion_swap": {
            "done": True,
            "replaced_base_index": wi,
            "used_candidate_index": ci,
            "base_score": bs_f[wi],
            "candidate_score": cs_f[ci],
        },
    }


def _final_cases_from_env(env: GenerationEnvelope, allowed: list[str], max_hi: int) -> list[dict]:
    out = [_norm(c.model_dump(), allowed_priorities=allowed) for c in env.test_cases]
    if max_hi:
        out = out[:max_hi]
    return out


def finalize_node(state: AgentState) -> dict:
    env = state.get("envelope")
    allowed = state.get("allowed_priorities") or ["Medium"]
    vp = state.get("validation_passed")
    hi = int(state.get("max_test_cases") or 0)
    if env and vp is True:
        return {"final_cases": _final_cases_from_env(env, allowed, hi), "error": None}
    if env and vp is False:
        out = _final_cases_from_env(env, allowed, hi)
        vr = state.get("validator")
        parts: list[str] = ["validation did not fully pass; returning best attempt"]
        if vr:
            parts.extend([x for x in vr.must_fix if (x or "").strip()])
            parts.extend([x for x in vr.issues if (x or "").strip()])
        return {"final_cases": out, "error": "; ".join(parts)}
    err = state.get("error") or state.get("parse_error") or "failed"
    return {"final_cases": [], "error": err}


def route_parse(state: AgentState) -> str:
    if state.get("envelope"):
        return "score"
    if int(state.get("generation") or 0) >= _max_rounds_cap(state):
        return "finalize"
    return "generate"


def route_score(state: AgentState) -> str:
    vr = state.get("validator")
    if not vr:
        return "finalize"
    if _passed(vr):
        sugs = [s for s in (vr.suggestions or []) if (s or "").strip()]
        if sugs:
            return "merge_suggestions"
        return "finalize"
    if int(state.get("generation") or 0) >= _max_rounds_cap(state):
        return "finalize"
    return "generate"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("generate", generate_node)
    g.add_node("parse", parse_node)
    g.add_node("score", score_node)
    g.add_node("merge_suggestions", merge_suggestions_node)
    g.add_node("finalize", finalize_node)
    g.set_entry_point("generate")
    g.add_edge("generate", "parse")
    g.add_conditional_edges(
        "parse",
        route_parse,
        {"score": "score", "generate": "generate", "finalize": "finalize"},
    )
    g.add_conditional_edges(
        "score",
        route_score,
        {"finalize": "finalize", "generate": "generate", "merge_suggestions": "merge_suggestions"},
    )
    g.add_edge("merge_suggestions", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def run_pipeline(
    requirements: dict,
    *,
    allowed_priorities: list[str] | None = None,
    min_test_cases: int = 1,
    max_test_cases: int = 10,
    max_rounds: int = 3,
    prev: dict | None = None,
    paste_mode: bool = False,
    existing_jira_tests: list[dict] | None = None,
) -> dict:
    pri = allowed_priorities or ["Highest", "High", "Medium", "Low", "Lowest"]
    gp = build_generation_user_prompt(
        requirements,
        prev,
        paste_mode=paste_mode,
        existing_jira_tests=existing_jira_tests,
        allowed_priorities=pri,
        min_test_cases=min_test_cases,
        max_test_cases=max_test_cases,
    )
    app = build_graph()
    init: AgentState = {
        "requirements": requirements,
        "generation_prompt": gp,
        "allowed_priorities": pri,
        "min_test_cases": min_test_cases,
        "max_test_cases": max_test_cases,
        "max_rounds": max_rounds,
        "feedback": "",
    }
    out = app.invoke(init)
    cases = out.get("final_cases") or []
    score_test_cases_0_10(requirements, cases)
    vr = out.get("validator")
    if hasattr(vr, "model_dump"):
        vr = vr.model_dump(mode="json")
    swap = out.get("suggestion_swap")
    if isinstance(swap, dict):
        swap = dict(swap)
    return {
        "test_cases": cases,
        "validator": vr,
        "validation_passed": out.get("validation_passed"),
        "error": out.get("error"),
        "generations": out.get("generation"),
        "suggestion_swap": swap,
    }
