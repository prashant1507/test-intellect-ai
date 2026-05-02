from __future__ import annotations

import json
import logging
import os
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ai_client import (
    _chat,
    _generated_case_quality_issues,
    _json as parse_llm_json,
    _llm_text_bearer,
    _llm_vision_bearer,
    _norm,
    build_generation_user_prompt,
    build_multimodal_user_content,
    disambiguate_duplicate_test_case_descriptions,
    resolve_severity_allowed_for_generation,
    score_test_cases_0_10,
)
from prompts import (
    AGENT_CANDIDATE_TEST_SUITE_GENERATION_SYSTEM_PROMPT,
    AGENT_COVERAGE_PLANNER_SYSTEM_PROMPT,
    AGENT_SCENARIOS_QUALITY_RANKING_SYSTEM_PROMPT,
    AGENT_SUGGESTED_SCENARIOS_GENERATION_SYSTEM_PROMPT,
    AGENT_TEST_SUITE_VALIDATION_RUBRIC_SYSTEM_PROMPT,
    BDD_TEST_GENERATION_WITH_ATTACHMENTS_SUPPLEMENT_PROMPT,
)
from requirement_images import images_to_state_payload, state_payload_to_images
from settings import settings

from .models import CoveragePlan, GenerationEnvelope, TestCaseItem, ValidatorResult

_LOG = logging.getLogger(__name__)

AGG_MIN = 3.5
DIM_MIN = 2
STRONG_AGG = 4.25
STRONG_DIM = 4


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
    skip_json_for_vision: bool = False,
    for_multimodal_with_images: bool = False,
) -> str:
    v_url = (settings.llm_vision_url or "").strip()
    if for_multimodal_with_images and v_url:
        base = v_url.rstrip("/")
        model = (settings.llm_vision_model or "").strip() or "local-model"
        b = _llm_vision_bearer()
    else:
        base = (settings.llm_text_url or "").strip().rstrip("/")
        if not base:
            raise ValueError("LLM_TEXT_URL is not set in .env")
        model = (settings.llm_text_model or "").strip() or "local-model"
        b = _llm_text_bearer()
    use_json = json_response_format and not skip_json_for_vision
    fmt = _json_mode_response() if use_json else None
    return _chat(
        base, model, messages, temperature, max_tokens=max_tokens, response_format=fmt, bearer=b
    )


def _msgs_with_images(
    system: str,
    user_text: str,
    imgs: list[tuple[str, str, bytes]],
) -> tuple[list[dict], bool]:
    uc = build_multimodal_user_content(user_text, imgs)
    has = bool(imgs)
    ss = (
        system
        if not has
        else f"{system}\n\n{BDD_TEST_GENERATION_WITH_ATTACHMENTS_SUPPLEMENT_PROMPT}"
    )
    return [{"role": "system", "content": ss}, {"role": "user", "content": uc}], has


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
    for k in ("description", "preconditions", "expected_result", "change_status", "priority", "severity"):
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
    allowed_severities: list[str]
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
    quality_issues: list[str]
    final_cases: list[dict]
    requirement_images: list[dict]
    coverage_plan: dict | None
    rounds_extension: int
    auto_extend_remaining: int
    agent_trace: list[dict]


def _trace_append(state: AgentState, agent: str, detail: str, **extra: object) -> list[dict]:
    rows = list(state.get("agent_trace") or [])
    row: dict = {"agent": agent, "detail": detail}
    for k, v in extra.items():
        if v is not None:
            row[k] = v
    rows.append(row)
    return rows


def _auto_extend_phases_cap() -> int:
    try:
        n = int((os.environ.get("AGENTIC_AUTO_EXTEND_PHASES") or "1").strip())
    except ValueError:
        n = 1
    return max(0, min(n, 5))


def _auto_extend_bump() -> int:
    raw = (
        os.environ.get("AGENTIC_AUTO_EXTEND_ADDITIONAL_GENERATIONS")
        or os.environ.get("AGENTIC_AUTO_EXTEND_ROUNDS")
        or "3"
    )
    try:
        n = int(str(raw).strip())
    except ValueError:
        n = 3
    return max(1, min(n, 8))


def _round_cap_ceiling() -> int:
    try:
        n = int((os.environ.get("AGENTIC_ROUND_CAP_CEILING") or "12").strip())
    except ValueError:
        n = 12
    return max(4, min(n, 24))


def _effective_round_cap(state: AgentState) -> int:
    base = max(1, int(state.get("max_rounds") or 3))
    ext = max(0, int(state.get("rounds_extension") or 0))
    return min(base + ext, _round_cap_ceiling())


def _coverage_item_ids(state: AgentState) -> list[str]:
    p = state.get("coverage_plan")
    if not isinstance(p, dict):
        return []
    items = p.get("items")
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if isinstance(it, dict):
            x = str(it.get("id") or "").strip()
            if x:
                out.append(x)
    return out


def _passed(vr: ValidatorResult, state: AgentState) -> bool:
    if any((x or "").strip() for x in vr.issues):
        return False
    if any((x or "").strip() for x in vr.must_fix):
        return False
    if _coverage_item_ids(state) and any((x or "").strip() for x in (vr.coverage_gaps or [])):
        return False
    if vr.aggregate < AGG_MIN or vr.min_dimension() < DIM_MIN:
        return False
    if vr.aggregate >= STRONG_AGG and vr.min_dimension() >= STRONG_DIM:
        return True
    return True


def _bounds_ok(n: int, state: AgentState) -> bool:
    lo = int(state.get("min_test_cases") or 1)
    hi = int(state.get("max_test_cases") or 10)
    if n < lo:
        return False
    if hi and n > hi:
        return False
    return True


def _cases_from_env(env: GenerationEnvelope, state: AgentState) -> list[dict]:
    pri = state.get("allowed_priorities") or ["Medium"]
    sev = state.get("allowed_severities") or resolve_severity_allowed_for_generation(False, None)
    return [_norm(c.model_dump(), allowed_priorities=pri, allowed_severities=sev) for c in env.test_cases]


def _deterministic_quality_issues(env: GenerationEnvelope, state: AgentState) -> list[str]:
    return _generated_case_quality_issues(
        _cases_from_env(env, state),
        min_test_cases=int(state.get("min_test_cases") or 1),
        max_test_cases=int(state.get("max_test_cases") or 0),
        allowed_priorities=state.get("allowed_priorities") or ["Medium"],
        allowed_severities=state.get("allowed_severities") or resolve_severity_allowed_for_generation(False, None),
    )


def _quality_feedback(issues: list[str]) -> str:
    body = "\n".join(f"- {x}" for x in issues[:12])
    return (
        "Deterministic quality checks failed. Regenerate the full JSON test suite and fix these issues "
        "without adding unsupported behavior:\n"
        f"{body}"
    )


def planner_node(state: AgentState) -> dict:
    req = json.dumps(state["requirements"], ensure_ascii=False, indent=2)
    lo = int(state.get("min_test_cases") or 1)
    hi = int(state.get("max_test_cases") or 10)
    hi_note = "no hard upper cap" if not hi else str(hi)
    user = (
        f"Requirements:\n{req}\n\n"
        f"Target suite size: at least {lo} scenario(s); maximum count for planning: {hi_note}.\n"
        "Return only the coverage plan JSON."
    )
    imgs = state_payload_to_images(state.get("requirement_images"))
    msgs, has_imgs = _msgs_with_images(AGENT_COVERAGE_PLANNER_SYSTEM_PROMPT, user, imgs)
    try:
        raw = _llm_chat(
            msgs,
            temperature=0.1,
            max_tokens=2048,
            json_response_format=True,
            skip_json_for_vision=has_imgs,
            for_multimodal_with_images=has_imgs,
        )
        data = parse_llm_json(raw)
        plan = CoveragePlan.model_validate(data)
        dump = plan.model_dump(mode="json")
        n = len(dump.get("items") or [])
        return {
            "coverage_plan": dump,
            "agent_trace": _trace_append(state, "planner", f"Coverage plan with {n} item(s)."),
        }
    except Exception:
        _LOG.debug("coverage planner node: invalid LLM output or validation failed", exc_info=True)
        fb_plan = {
            "items": [],
            "out_of_scope": [],
            "assumptions": ["Coverage planner could not produce a valid plan; generation uses requirements only."],
        }
        return {
            "coverage_plan": fb_plan,
            "agent_trace": _trace_append(state, "planner", "Planner output invalid; requirements-only fallback."),
        }


def generate_node(state: AgentState) -> dict:
    gp = (state.get("generation_prompt") or "").strip()
    fb = (state.get("feedback") or "").strip()
    if not gp:
        req = json.dumps(state["requirements"], ensure_ascii=False, indent=2)
        lo = int(state.get("min_test_cases") or 1)
        hi = int(state.get("max_test_cases") or 10)
        hi_note = "no upper limit" if not hi else f"at most {hi}"
        sev_list = state.get("allowed_severities") or resolve_severity_allowed_for_generation(False, None)
        user = (
            f"Requirements:\n{req}\n\n"
            f"Task: at least {lo} test case(s), {hi_note} total. "
            f"Priorities exactly one of: {', '.join(state['allowed_priorities'])}.\n"
            f"Severities exactly one of: {', '.join(sev_list)}.\n"
        )
    else:
        user = gp
    if fb:
        user += f"\n\nRevise using this feedback (do not repeat the same mistakes):\n{fb}\n"
    cp = state.get("coverage_plan")
    if isinstance(cp, dict) and cp.get("items"):
        user += (
            "\n\n### Coverage plan (binding)\n"
            "Each item has id and intent. Every id MUST be clearly addressed by at least one test case "
            "(reflect the intent in description and/or steps). Do not drop or merge items unless the suite stays within max count and every id remains traceable.\n"
            f"{json.dumps(cp, ensure_ascii=False, indent=2)}"
        )
    imgs = state_payload_to_images(state.get("requirement_images"))
    if imgs:
        user += (
            "\n\n### Images and PDFs (same message, after this text)\n"
            "Additional image or PDF parts follow. Combine them with the Requirements text and Prior/linked context; "
            "ground scenarios in written and visual (or document) requirement evidence where they agree."
        )
    msgs, has_imgs = _msgs_with_images(
        AGENT_CANDIDATE_TEST_SUITE_GENERATION_SYSTEM_PROMPT, user, imgs
    )
    raw = _llm_chat(
        msgs,
        temperature=0.12,
        max_tokens=4096,
        json_response_format=True,
        skip_json_for_vision=has_imgs,
        for_multimodal_with_images=has_imgs,
    )
    g = (state.get("generation") or 0) + 1
    return {
        "raw": raw,
        "generation": g,
        "envelope": None,
        "validator": None,
        "validation_passed": None,
        "suggestion_swap": None,
        "quality_issues": [],
        "agent_trace": _trace_append(state, "generator", "Generated candidate test suite (LLM).", generation=g),
    }


def parse_node(state: AgentState) -> dict:
    raw = (state.get("raw") or "").strip()
    mx = _effective_round_cap(state)
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
        quality_issues = _deterministic_quality_issues(env, state)
        if quality_issues and gen < mx:
            return {
                "envelope": None,
                "quality_issues": quality_issues,
                "parse_error": "deterministic quality checks failed",
                "feedback": _quality_feedback(quality_issues),
                "agent_trace": _trace_append(
                    state,
                    "parser",
                    f"Deterministic quality failed ({len(quality_issues)} issue(s)); retry scheduled.",
                    generation=gen,
                ),
            }
        err = (
            "deterministic quality checks did not fully pass: "
            + "; ".join(quality_issues)
            if quality_issues
            else None
        )
        n = len(env.test_cases)
        return {
            "envelope": env,
            "quality_issues": quality_issues,
            "parse_error": None,
            "error": err,
            "agent_trace": _trace_append(state, "parser", f"Parsed {n} test case(s).", generation=gen),
        }
    except Exception as e:
        err = str(e)
        if gen >= mx:
            return {
                "envelope": None,
                "parse_error": err,
                "error": err,
                "agent_trace": _trace_append(state, "parser", f"Parse failed after max attempts: {err[:160]}", generation=gen),
            }
        return {
            "envelope": None,
            "parse_error": err,
            "feedback": f"Invalid output: {err}. Return valid JSON with test_cases only.",
            "agent_trace": _trace_append(state, "parser", f"Parse error; retry scheduled: {err[:120]}", generation=gen),
        }


def score_node(state: AgentState) -> dict:
    env = state["envelope"]
    assert env is not None
    req = json.dumps(state["requirements"], ensure_ascii=False, indent=2)
    body = json.dumps({"test_cases": [c.model_dump() for c in env.test_cases]}, ensure_ascii=False, indent=2)
    prefix = ""
    cp = state.get("coverage_plan")
    if isinstance(cp, dict) and (cp.get("items") or cp.get("out_of_scope") or cp.get("assumptions")):
        prefix = (
            "Coverage plan:\n"
            f"{json.dumps(cp, ensure_ascii=False, indent=2)}\n\n"
        )
    user = f"{prefix}Requirements:\n{req}\n\nGenerated:\n{body}\n\nReturn only the scoring JSON."
    imgs = state_payload_to_images(state.get("requirement_images"))
    msgs, has_imgs = _msgs_with_images(AGENT_TEST_SUITE_VALIDATION_RUBRIC_SYSTEM_PROMPT, user, imgs)
    mx = _effective_round_cap(state)
    gen = int(state.get("generation") or 0)
    try:
        raw = _llm_chat(
            msgs,
            temperature=0.08,
            max_tokens=1024,
            json_response_format=True,
            skip_json_for_vision=has_imgs,
            for_multimodal_with_images=has_imgs,
        )
        data = parse_llm_json(raw)
        vr = ValidatorResult.model_validate(data)
    except Exception as e:
        msg = f"Validator failed to return valid scoring JSON: {e!s}"
        tr = _trace_append(state, "validator", f"Scoring JSON invalid: {msg[:140]}", generation=gen)
        if gen < mx:
            return {"validator": None, "validation_passed": False, "feedback": msg, "agent_trace": tr}
        return {"validator": None, "validation_passed": False, "feedback": msg, "agent_trace": tr}
    quality_issues = _deterministic_quality_issues(env, state)
    if quality_issues:
        vr.must_fix = list(vr.must_fix) + [f"Deterministic check: {x}" for x in quality_issues]
    ok = _passed(vr, state)
    if ok:
        return {
            "validator": vr,
            "validation_passed": True,
            "agent_trace": _trace_append(
                state,
                "validator",
                f"Validation passed (aggregate {vr.aggregate:.2f}).",
                generation=gen,
            ),
        }
    fb_parts: list[str] = []
    fb_parts.extend(vr.must_fix[:8])
    fb_parts.extend(vr.issues[:6])
    gaps = [x for x in (vr.coverage_gaps or []) if (x or "").strip()]
    if gaps:
        fb_parts.append("Coverage gaps (planner ids not adequately covered): " + ", ".join(gaps))
    fb_parts.append(
        f"Scores: aggregate={vr.aggregate:.2f} (need >={AGG_MIN}), min_dim={vr.min_dimension()} (need >={DIM_MIN}). "
        "Fix all items above; output must have no remaining issues."
    )
    return {
        "validator": vr,
        "validation_passed": False,
        "feedback": "\n".join(fb_parts),
        "agent_trace": _trace_append(
            state,
            "validator",
            "Validation incomplete; feedback sent to generator.",
            generation=gen,
        ),
    }


def merge_suggestions_node(state: AgentState) -> dict:
    def fail(reason: str) -> dict:
        return {
            "suggestion_swap": {"done": False, "reason": reason},
            "agent_trace": _trace_append(state, "suggestion_merge", f"Skipped ({reason})."),
        }

    vr = state.get("validator")
    env = state.get("envelope")
    if not vr or not env or not _passed(vr, state):
        return fail("skipped")
    sugs = [s for s in (vr.suggestions or []) if (s or "").strip()]
    if not sugs:
        return fail("no_suggestions")
    allowed = state.get("allowed_priorities") or ["Medium"]
    allowed_sev = state.get("allowed_severities") or resolve_severity_allowed_for_generation(False, None)
    req = json.dumps(state["requirements"], ensure_ascii=False, indent=2)
    sug_block = "\n".join(f"- {s}" for s in sugs)
    pri = ", ".join(allowed)
    sev = ", ".join(allowed_sev)
    user = (
        f"Requirements:\n{req}\n\n"
        f"Create exactly {len(sugs)} test case(s), one per suggestion:\n{sug_block}\n"
        f"Priorities exactly one of: {pri}.\n"
        f"Severities exactly one of: {sev}.\n"
        f"Return only JSON with key test_cases."
    )
    imgs = state_payload_to_images(state.get("requirement_images"))
    msgs, has_imgs = _msgs_with_images(
        AGENT_SUGGESTED_SCENARIOS_GENERATION_SYSTEM_PROMPT, user, imgs
    )
    try:
        raw = _llm_chat(
            msgs,
            temperature=0.12,
            max_tokens=4096,
            json_response_format=True,
            skip_json_for_vision=has_imgs,
            for_multimodal_with_images=has_imgs,
        )
        data = parse_llm_json(raw)
        tc = data.get("test_cases")
        if not isinstance(tc, list) or not tc:
            return fail("candidate_generation_empty")
        raw_cases = [_coerce_raw_case(x) for x in tc[: len(sugs)]]
        env_c = GenerationEnvelope.model_validate({"test_cases": raw_cases})
    except Exception as e:
        return fail(f"candidate_generation_failed: {e!s}"[:200])
    candidates_norm = [_norm(c.model_dump(), allowed_priorities=allowed, allowed_severities=allowed_sev) for c in env_c.test_cases]
    base_norm = [_norm(c.model_dump(), allowed_priorities=allowed, allowed_severities=allowed_sev) for c in env.test_cases]
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
    msgs2, has_imgs2 = _msgs_with_images(AGENT_SCENARIOS_QUALITY_RANKING_SYSTEM_PROMPT, user2, imgs)
    try:
        raw2 = _llm_chat(
            msgs2,
            temperature=0.05,
            max_tokens=1024,
            json_response_format=True,
            skip_json_for_vision=has_imgs2,
            for_multimodal_with_images=has_imgs2,
        )
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
            },
            "agent_trace": _trace_append(state, "suggestion_merge", "No swap: best candidate did not beat weakest base."),
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
        "agent_trace": _trace_append(state, "suggestion_merge", "Re-ranked scenarios and swapped in one improved case."),
    }


def _final_cases_from_env(
    env: GenerationEnvelope, allowed_pri: list[str], allowed_sev: list[str], max_hi: int
) -> list[dict]:
    out = [
        _norm(c.model_dump(), allowed_priorities=allowed_pri, allowed_severities=allowed_sev)
        for c in env.test_cases
    ]
    if max_hi:
        out = out[:max_hi]
    disambiguate_duplicate_test_case_descriptions(out)
    return out


def finalize_node(state: AgentState) -> dict:
    env = state.get("envelope")
    pri = state.get("allowed_priorities") or ["Medium"]
    sev = state.get("allowed_severities") or resolve_severity_allowed_for_generation(False, None)
    vp = state.get("validation_passed")
    hi = int(state.get("max_test_cases") or 0)
    if env and vp is True:
        fc = _final_cases_from_env(env, pri, sev, hi)
        return {
            "final_cases": fc,
            "error": None,
            "agent_trace": _trace_append(state, "finalize", f"Done: {len(fc)} scenario(s), validation passed."),
        }
    if env and vp is False:
        out = _final_cases_from_env(env, pri, sev, hi)
        vr = state.get("validator")
        parts: list[str] = ["validation did not fully pass; returning best attempt"]
        if vr:
            parts.extend([x for x in vr.must_fix if (x or "").strip()])
            parts.extend([x for x in vr.issues if (x or "").strip()])
        return {
            "final_cases": out,
            "error": "; ".join(parts),
            "agent_trace": _trace_append(
                state, "finalize", f"Done: {len(out)} scenario(s); validation incomplete."
            ),
        }
    err = state.get("error") or state.get("parse_error") or "failed"
    return {
        "final_cases": [],
        "error": err,
        "agent_trace": _trace_append(state, "finalize", f"Done: no scenarios ({err[:120]})."),
    }


def route_parse(state: AgentState) -> str:
    if state.get("envelope"):
        return "score"
    gen = int(state.get("generation") or 0)
    cap = _effective_round_cap(state)
    if gen >= cap:
        if int(state.get("auto_extend_remaining") or 0) > 0:
            return "auto_extend"
        return "finalize"
    return "generate"


def route_score(state: AgentState) -> str:
    vr = state.get("validator")
    gen = int(state.get("generation") or 0)
    cap = _effective_round_cap(state)
    rem = int(state.get("auto_extend_remaining") or 0)
    if not vr:
        if state.get("feedback") and gen < cap:
            return "generate"
        if state.get("feedback") and gen >= cap and rem > 0:
            return "auto_extend"
        return "finalize"
    if _passed(vr, state):
        sugs = [s for s in (vr.suggestions or []) if (s or "").strip()]
        if sugs and not state.get("suggestion_swap"):
            return "merge_suggestions"
        return "finalize"
    if gen < cap:
        return "generate"
    if rem > 0:
        return "auto_extend"
    return "finalize"


def route_suggestion_swap(state: AgentState) -> str:
    swap = state.get("suggestion_swap")
    if isinstance(swap, dict) and swap.get("done") is True:
        return "score"
    return "finalize"


def auto_extend_rounds_node(state: AgentState) -> dict:
    bump = _auto_extend_bump()
    prev = int(state.get("rounds_extension") or 0)
    rem = int(state.get("auto_extend_remaining") or 0)
    fb = (state.get("feedback") or "").strip()
    note = "[Automatic extension: extra revision attempts; UI max rounds unchanged.]"
    return {
        "rounds_extension": prev + bump,
        "auto_extend_remaining": max(0, rem - 1),
        "feedback": f"{fb}\n\n{note}".strip() if fb else note,
        "agent_trace": _trace_append(
            state,
            "auto_extend",
            f"Extended generation budget by {bump} (phases left: {max(0, rem - 1)}).",
        ),
    }


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("plan", planner_node)
    g.add_node("generate", generate_node)
    g.add_node("parse", parse_node)
    g.add_node("score", score_node)
    g.add_node("merge_suggestions", merge_suggestions_node)
    g.add_node("auto_extend", auto_extend_rounds_node)
    g.add_node("finalize", finalize_node)
    g.set_entry_point("plan")
    g.add_edge("plan", "generate")
    g.add_edge("generate", "parse")
    g.add_conditional_edges(
        "parse",
        route_parse,
        {"score": "score", "generate": "generate", "finalize": "finalize", "auto_extend": "auto_extend"},
    )
    g.add_conditional_edges(
        "score",
        route_score,
        {
            "finalize": "finalize",
            "generate": "generate",
            "merge_suggestions": "merge_suggestions",
            "auto_extend": "auto_extend",
        },
    )
    g.add_conditional_edges(
        "merge_suggestions",
        route_suggestion_swap,
        {"score": "score", "finalize": "finalize"},
    )
    g.add_edge("auto_extend", "generate")
    g.add_edge("finalize", END)
    return g.compile()


def run_pipeline(
    requirements: dict,
    *,
    allowed_priorities: list[str] | None = None,
    allowed_severities: list[str] | None = None,
    min_test_cases: int = 1,
    max_test_cases: int = 10,
    max_rounds: int = 3,
    prev: dict | None = None,
    paste_mode: bool = False,
    existing_jira_tests: list[dict] | None = None,
    requirement_images: list[tuple[str, str, bytes]] | None = None,
) -> dict:
    pri = allowed_priorities or ["Highest", "High", "Medium", "Low", "Lowest"]
    sev = allowed_severities if allowed_severities is not None else resolve_severity_allowed_for_generation(
        False, None
    )
    gp = build_generation_user_prompt(
        requirements,
        prev,
        paste_mode=paste_mode,
        existing_jira_tests=existing_jira_tests,
        allowed_priorities=pri,
        allowed_severities=sev,
        min_test_cases=min_test_cases,
        max_test_cases=max_test_cases,
    )
    app = build_graph()
    ri = images_to_state_payload(requirement_images or [])
    init: AgentState = {
        "requirements": requirements,
        "generation_prompt": gp,
        "allowed_priorities": pri,
        "allowed_severities": sev,
        "min_test_cases": min_test_cases,
        "max_test_cases": max_test_cases,
        "max_rounds": max_rounds,
        "rounds_extension": 0,
        "auto_extend_remaining": _auto_extend_phases_cap(),
        "feedback": "",
        "requirement_images": ri,
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
    cp = out.get("coverage_plan")
    if isinstance(cp, dict):
        cp = dict(cp)
    else:
        cp = None
    trace = out.get("agent_trace")
    if not isinstance(trace, list):
        trace = []
    return {
        "test_cases": cases,
        "validator": vr,
        "validation_passed": out.get("validation_passed"),
        "error": out.get("error"),
        "generations": out.get("generation"),
        "suggestion_swap": swap,
        "coverage_plan": cp,
        "agent_trace": trace,
    }
