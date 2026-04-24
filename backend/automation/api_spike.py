from __future__ import annotations

import json
import re
from typing import Any

import requests

from ai_client import llm_chat_completion, parse_llm_json_object
from settings import settings
from . import cancel
from .prefs import get_effective_automation_default_timeout_ms
from .bdd import parse_bdd_step_lines
from .errors import SpikeUserError

_SYS_API = (
    "You are an API test planner. The user provides BDD steps for HTTP API testing. "
    "For EACH BDD line (same count, same order) you return one JSON object describing how to "
    "execute or verify that line.\n"
    "Return ONLY valid JSON: {\"steps\": [ ... ]} with length exactly N.\n"
    "Each step object has:\n"
    '- "op": one of: noop, reachability, set_header, http, assert_status, assert_json_key, '
    "assert_json_path_not_empty, assert_json_path_empty, assert_body_contains.\n"
    "- For noop: no extra fields (documentation-only line).\n"
    '- For reachability: optional "path" (default "/") — GET that path relative to base to verify the host responds.\n'
    '- For set_header: "header_name" and "header_value" (applies to following requests).\n'
    '- For http: "method" (GET, POST, PUT, PATCH, DELETE, HEAD), "path" (relative, e.g. /auth), '
    'optional "json" (object as request JSON body for POST/PUT/PATCH), optional "headers" (object, merged for this call).\n'
    '- For assert_status: "expected_status" (integer).\n'
    '- For assert_json_key: "json_key" (top-level key in last JSON response).\n'
    '- For assert_json_path_not_empty: "json_key" (top level) OR "path" with dots e.g. "data.token" — value must exist and not be null or empty string.\n'
    '- For assert_json_path_empty: "json_key" or "path" (dots) — value must be null, missing, or empty string. '
    "Use when BDD says the value \u201cshould be empty\u201d or \u201cmust be empty\u201d. Fails on non-empty strings (e.g. a real API token).\n"
    '- For assert_body_contains: "substring" — last response text must include it (e.g. the word token in JSON).\n'
    "Map Givens to reachability, set_header, or noop. Map When to http. Map Then/And to assertion ops. "
    "If a When line includes a JSON body, put it in the http step as \"json\".\n"
    "Use values from the BDD only."
)


def _l(log: list[str], m: str) -> None:
    log.append(m)


def _llm_url_ok() -> bool:
    return bool((settings.llm_url or "").strip()) and not settings.mock


def _raise_if_spike_cancelled(log: list[str]) -> None:
    if cancel.is_stop_one_spike() or cancel.is_stop_all_suite():
        _l(log, "Run cancelled (user).")
        raise SpikeUserError(cancel.cancel_message(), logs=log)


def _url_join_base(base: str, path: str) -> str:
    b = (base or "").rstrip("/")
    p = (path or "").strip()
    if not p:
        return b + "/"
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if p.startswith("/"):
        m = re.match(r"^(https?://[^/]+)(.*)$", b, re.I)
        if m and m.group(2) and m.group(2) != "/":
            return m.group(1).rstrip("/") + p
        return b + p
    return f"{b}/{p.lstrip('/')}"


def _llm_api_steps(
    title: str, bdd_lines: list[str], base_url: str, log: list[str]
) -> list[dict[str, Any]]:
    if not _llm_url_ok():
        raise SpikeUserError("LLM_URL is not set; cannot run API BDD.", logs=log)
    n = len(bdd_lines)
    num = "\n".join(f"  {i}. {line}" for i, line in enumerate(bdd_lines))
    user = (
        f"Title: {title}\n"
        f"Base URL: {base_url}\n"
        f"N={n}\nBDD lines (one object per line, indices 0..n-1):\n{num}\n"
    )
    data: Any = None
    for attempt in (0, 1):
        u = user if attempt == 0 else user + f"\nCRITICAL: steps array must have length EXACTLY {n}.\n"
        raw = llm_chat_completion(_SYS_API, u, temperature=0.05, max_tokens=16_000)
        data = parse_llm_json_object(raw)
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            if len(data["steps"]) == n:
                break
        if isinstance(data, list) and len(data) == n:
            data = {"steps": data}
            break
        _l(log, f"LLM API: length retry {attempt + 1} (need {n}).")
    steps = (data or {}).get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or len(steps) != n:
        raise SpikeUserError(
            f"LLM did not return {n} API step spec(s).", logs=log
        )
    out: list[dict[str, Any]] = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            raise SpikeUserError(f"API step {i} is not a JSON object.", logs=log)
        if not str(s.get("op") or "").strip():
            raise SpikeUserError(f"API step {i} missing op.", logs=log)
        out.append(dict(s))
    return out


def _get_json_path(obj: Any, path: str) -> Any:
    parts = [p for p in (path or "").strip().split(".") if p]
    cur: Any = obj
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _run_api_steps(
    run_id: str,
    bdd_lines: list[str],
    spec: list[dict[str, Any]],
    base_url: str,
    log: list[str],
) -> list[dict[str, Any]]:
    _ = run_id
    tw = int(get_effective_automation_default_timeout_ms())
    timeout = max(1, min(tw, 300_000)) / 1000.0
    default_h: dict[str, str] = {}
    last_text = ""
    last_status: int | None = None
    last_json: Any = None
    out: list[dict[str, Any]] = []
    b = (base_url or "").strip()
    n = len(bdd_lines)
    for i, bline in enumerate(bdd_lines):
        _raise_if_spike_cancelled(log)
        st = spec[i] if i < len(spec) else {}
        op = str(st.get("op") or "noop").strip().lower()
        _l(log, f"API step {i} op={op!r}")
        detail = json.dumps(st, ensure_ascii=False)[:2000]
        rec: dict[str, Any] = {
            "step_index": i,
            "step_text": bline,
            "selector": op,
            "action": "api",
            "value": detail,
            "source": "llm",
            "pass": False,
            "err": None,
        }
        err: str | None = None
        ok = False
        try:
            if op == "noop":
                ok = True
            elif op == "reachability":
                p = str(st.get("path") or "/").strip() or "/"
                u = _url_join_base(b, p)
                r = requests.get(u, headers=dict(default_h), timeout=timeout, verify=True)
                last_status = r.status_code
                last_text = r.text
                try:
                    last_json = r.json()
                except (json.JSONDecodeError, ValueError):
                    last_json = None
                ok = 200 <= r.status_code < 500
                if not ok:
                    err = f"reachability: HTTP {r.status_code}"
            elif op == "set_header":
                hn = str(st.get("header_name") or st.get("name") or "").strip()
                hv = str(st.get("header_value") or st.get("value") or "")
                if not hn:
                    err = "set_header: missing header name"
                else:
                    default_h[hn] = hv
                    ok = True
            elif op == "http":
                method = str(st.get("method") or "GET").upper()
                p = str(st.get("path") or "/").strip() or "/"
                u = _url_join_base(b, p)
                hdr: dict[str, str] = {**default_h}
                h_extra = st.get("headers")
                if isinstance(h_extra, dict):
                    for k, v in h_extra.items():
                        hdr[str(k)] = str(v) if v is not None else ""
                jso = st.get("json")
                if method in ("POST", "PUT", "PATCH") and jso is not None:
                    r = requests.request(
                        method, u, json=jso, headers=hdr, timeout=timeout, verify=True
                    )
                else:
                    r = requests.request(
                        method, u, headers=hdr, timeout=timeout, verify=True
                    )
                last_status = r.status_code
                last_text = r.text
                try:
                    last_json = r.json()
                except (json.JSONDecodeError, ValueError):
                    last_json = None
                ok = True
            elif op == "assert_status":
                exp = st.get("expected_status")
                try:
                    want = int(exp) if exp is not None else None
                except (TypeError, ValueError):
                    want = None
                if want is None:
                    err = "assert_status: expected_status missing"
                elif last_status is None:
                    err = "assert_status: no previous HTTP response"
                elif last_status != want:
                    err = f"status {last_status} != {want}"
                else:
                    ok = True
            elif op == "assert_json_key":
                k = str(st.get("json_key") or st.get("key") or "").strip()
                if not k:
                    err = "assert_json_key: missing key"
                elif not isinstance(last_json, dict) or k not in last_json:
                    err = f"JSON missing key {k!r}"
                else:
                    ok = True
            elif op in ("assert_json_path_not_empty", "assert_json_not_empty"):
                jk = str(st.get("json_key") or "").strip()
                pth = str(st.get("path") or "").strip()
                val: Any = None
                if pth:
                    val = _get_json_path(last_json, pth)
                elif jk:
                    val = _get_json_path(last_json, jk) if isinstance(
                        last_json, dict
                    ) else None
                if val is None:
                    err = f"path/key {pth or jk!r} missing or null"
                elif isinstance(val, str) and not val.strip():
                    err = f"value at {pth or jk!r} is empty"
                else:
                    ok = not (val is None or (isinstance(val, str) and not val.strip()))
            elif op in ("assert_json_path_empty", "assert_json_empty"):
                jk = str(st.get("json_key") or "").strip()
                pth = str(st.get("path") or "").strip()
                v: Any = None
                if pth:
                    v = _get_json_path(last_json, pth)
                elif jk and isinstance(last_json, dict):
                    v = last_json.get(jk)
                elif jk:
                    v = _get_json_path(last_json, jk)
                if v is None:
                    ok = True
                elif isinstance(v, str) and not v.strip():
                    ok = True
                else:
                    preview = repr(v)
                    if len(preview) > 160:
                        preview = preview[:157] + "..."
                    err = f"expected empty at {pth or jk!r}, got {preview}"
            elif op == "assert_body_contains":
                sub = str(st.get("substring") or st.get("value") or "")
                if not sub:
                    err = "assert_body_contains: missing substring"
                elif sub not in last_text:
                    err = f"body does not contain {sub[:80]!r}"
                else:
                    ok = True
            else:
                err = f"unknown op: {op}"
        except requests.RequestException as e:
            err = str(e) or type(e).__name__
        if err:
            rec["err"] = err
            out.append(rec)
            for j in range(i + 1, n):
                out.append(
                    {
                        "step_index": j,
                        "step_text": bdd_lines[j],
                        "selector": "skip",
                        "action": "api",
                        "value": "",
                        "source": "skip",
                        "pass": False,
                        "err": "skipped (previous step failed)",
                    }
                )
            break
        rec["pass"] = ok
        if not ok and not rec.get("err"):
            rec["err"] = "assertion failed"
        out.append(rec)
    return out


def run_api_bdd(
    run_id: str, title: str, bdd: str, base_url: str, log: list[str]
) -> list[dict[str, Any]]:
    bdd_lines = parse_bdd_step_lines(bdd)
    if not bdd_lines:
        raise SpikeUserError("BDD is empty (no steps).", logs=log)
    _l(log, f"API: parsed {len(bdd_lines)} BDD line(s).")
    spec = _llm_api_steps(title, bdd_lines, base_url, log)
    return _run_api_steps(run_id, bdd_lines, spec, base_url, log)
