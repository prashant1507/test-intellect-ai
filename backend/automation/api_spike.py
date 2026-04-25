from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from ai_client import llm_chat_completion, parse_llm_json_object
from prompts import API_BDD_TO_HTTP_OPERATIONS_PLANNER_SYSTEM_PROMPT
from .bdd import parse_bdd_step_lines
from .errors import SpikeUserError
from .prefs import get_effective_automation_default_timeout_ms
from .spike import _l, _llm_base_ok, _raise_if_spike_cancelled


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


def _get_json_path(obj: Any, path: str) -> Any:
    parts = [p for p in (path or "").strip().split(".") if p]
    cur: Any = obj
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _value_for_key_or_path(
    last_json: Any, json_key: str, path: str
) -> Any:
    pth = path.strip()
    jk = json_key.strip()
    if pth:
        return _get_json_path(last_json, pth)
    if not jk:
        return None
    if isinstance(last_json, dict):
        return last_json.get(jk)
    return _get_json_path(last_json, jk)


def _try_response_json(r: requests.Response) -> Any:
    try:
        return r.json()
    except (json.JSONDecodeError, ValueError):
        return None


@dataclass
class _ResponseState:
    last_text: str = ""
    last_status: int | None = None
    last_json: Any = None

    def capture(self, r: requests.Response) -> None:
        self.last_status = r.status_code
        self.last_text = r.text
        self.last_json = _try_response_json(r)


@dataclass
class _RunContext:
    base: str
    timeout: float
    default_headers: dict[str, str] = field(default_factory=dict)
    rsp: _ResponseState = field(default_factory=_ResponseState)

    @property
    def last_text(self) -> str:
        return self.rsp.last_text

    @property
    def last_status(self) -> int | None:
        return self.rsp.last_status

    @property
    def last_json(self) -> Any:
        return self.rsp.last_json

    def capture(self, r: requests.Response) -> None:
        self.rsp.capture(r)


def _llm_api_steps(
    title: str, bdd_lines: list[str], base_url: str, log: list[str]
) -> list[dict[str, Any]]:
    if not _llm_base_ok():
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
        raw = llm_chat_completion(
            API_BDD_TO_HTTP_OPERATIONS_PLANNER_SYSTEM_PROMPT,
            u,
            temperature=0.05,
            max_tokens=16_000,
        )
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


def _append_skipped_tail(
    out: list[dict[str, Any]],
    bdd_lines: list[str],
    from_index: int,
    n: int,
) -> None:
    for j in range(from_index, n):
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


def _op_reachability(ctx: _RunContext, st: dict[str, Any]) -> str | None:
    p = str(st.get("path") or "/").strip() or "/"
    u = _url_join_base(ctx.base, p)
    try:
        r = requests.get(
            u, headers=dict(ctx.default_headers), timeout=ctx.timeout, verify=True
        )
    except requests.RequestException as e:
        return str(e) or type(e).__name__
    ctx.capture(r)
    if 200 <= r.status_code < 500:
        return None
    return f"reachability: HTTP {r.status_code}"


def _op_set_header(ctx: _RunContext, st: dict[str, Any]) -> str | None:
    hn = str(st.get("header_name") or st.get("name") or "").strip()
    if not hn:
        return "set_header: missing header name"
    hv = str(st.get("header_value") or st.get("value") or "")
    ctx.default_headers[hn] = hv
    return None


def _op_http(ctx: _RunContext, st: dict[str, Any]) -> str | None:
    method = str(st.get("method") or "GET").upper()
    p = (str(st.get("path") or "/").strip() or "/")
    u = _url_join_base(ctx.base, p)
    hdr: dict[str, str] = {**ctx.default_headers}
    h_extra = st.get("headers")
    if isinstance(h_extra, dict):
        for k, v in h_extra.items():
            hdr[str(k)] = str(v) if v is not None else ""
    jso = st.get("json")
    try:
        if method in ("POST", "PUT", "PATCH") and jso is not None:
            r = requests.request(
                method, u, json=jso, headers=hdr, timeout=ctx.timeout, verify=True
            )
        else:
            r = requests.request(
                method, u, headers=hdr, timeout=ctx.timeout, verify=True
            )
    except requests.RequestException as e:
        return str(e) or type(e).__name__
    ctx.capture(r)
    return None


def _op_assert_status(ctx: _RunContext, st: dict[str, Any]) -> str | None:
    exp = st.get("expected_status")
    try:
        want = int(exp) if exp is not None else None
    except (TypeError, ValueError):
        want = None
    if want is None:
        return "assert_status: expected_status missing"
    if ctx.last_status is None:
        return "assert_status: no previous HTTP response"
    if ctx.last_status != want:
        return f"status {ctx.last_status} != {want}"
    return None


def _op_assert_json_key(ctx: _RunContext, st: dict[str, Any]) -> str | None:
    k = str(st.get("json_key") or st.get("key") or "").strip()
    if not k:
        return "assert_json_key: missing key"
    if not isinstance(ctx.last_json, dict) or k not in ctx.last_json:
        return f"JSON missing key {k!r}"
    return None


def _op_assert_json_path_not_empty(
    ctx: _RunContext, st: dict[str, Any]
) -> str | None:
    jk = str(st.get("json_key") or "").strip()
    pth = str(st.get("path") or "").strip()
    val = _value_for_key_or_path(ctx.last_json, jk, pth)
    if val is None:
        return f"path/key {pth or jk!r} missing or null"
    if isinstance(val, str) and not val.strip():
        return f"value at {pth or jk!r} is empty"
    return None


def _op_assert_json_path_empty(
    ctx: _RunContext, st: dict[str, Any]
) -> str | None:
    jk = str(st.get("json_key") or "").strip()
    pth = str(st.get("path") or "").strip()
    v = _value_for_key_or_path(ctx.last_json, jk, pth)
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    preview = repr(v)
    if len(preview) > 160:
        preview = preview[:157] + "..."
    return f"expected empty at {pth or jk!r}, got {preview}"


def _op_assert_body_contains(ctx: _RunContext, st: dict[str, Any]) -> str | None:
    sub = str(st.get("substring") or st.get("value") or "")
    if not sub:
        return "assert_body_contains: missing substring"
    if sub not in ctx.last_text:
        return f"body does not contain {sub[:80]!r}"
    return None


_OP: dict[str, Callable[[_RunContext, dict[str, Any]], str | None]] = {
    "noop": lambda _c, _s: None,
    "reachability": _op_reachability,
    "set_header": _op_set_header,
    "http": _op_http,
    "assert_status": _op_assert_status,
    "assert_json_key": _op_assert_json_key,
    "assert_json_path_not_empty": _op_assert_json_path_not_empty,
    "assert_json_not_empty": _op_assert_json_path_not_empty,
    "assert_json_path_empty": _op_assert_json_path_empty,
    "assert_json_empty": _op_assert_json_path_empty,
    "assert_body_contains": _op_assert_body_contains,
}


def _run_api_step(ctx: _RunContext, st: dict[str, Any], op: str) -> str | None:
    fn = _OP.get(op)
    if fn is None:
        return f"unknown op: {op}"
    return fn(ctx, st)


def _run_api_steps(
    bdd_lines: list[str],
    spec: list[dict[str, Any]],
    base_url: str,
    log: list[str],
) -> list[dict[str, Any]]:
    tw = int(get_effective_automation_default_timeout_ms())
    timeout = max(1, min(tw, 300_000)) / 1000.0
    ctx = _RunContext(base=(base_url or "").strip(), timeout=timeout)
    n = len(bdd_lines)
    out: list[dict[str, Any]] = []
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
        err = _run_api_step(ctx, st, op)
        if err:
            rec["err"] = err
            out.append(rec)
            _append_skipped_tail(out, bdd_lines, i + 1, n)
            break
        rec["pass"] = True
        out.append(rec)
    return out


def run_api_bdd(
    run_id: str, title: str, bdd: str, base_url: str, log: list[str]
) -> list[dict[str, Any]]:
    _ = run_id
    bdd_lines = parse_bdd_step_lines(bdd)
    if not bdd_lines:
        raise SpikeUserError("BDD is empty (no steps).", logs=log)
    _l(log, f"API: parsed {len(bdd_lines)} BDD line(s).")
    spec = _llm_api_steps(title, bdd_lines, base_url, log)
    return _run_api_steps(bdd_lines, spec, base_url, log)
