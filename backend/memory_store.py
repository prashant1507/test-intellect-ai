from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone

from ai_client import strip_test_case_diff_meta
from key_norm import norm_issue_key
from sqlite_util import open_memory_db

_WS = re.compile(r"\s+")
_TEST_HASH_KEY = re.compile(r"^TEST-[0-9A-F]{10}$")


def _loads_req(raw: str) -> dict | None:
    try:
        o = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return o if isinstance(o, dict) else None


def _loads_tc_list(raw: str) -> list:
    try:
        tc_raw = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(tc_raw, list):
        return []
    return [x for x in tc_raw if isinstance(x, dict)]


def _prev_bundle(stored_req: dict, test_cases_json: str) -> dict | None:
    try:
        tc_raw = json.loads(test_cases_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(tc_raw, list):
        return None
    tc_list = [x for x in tc_raw if isinstance(x, dict)]
    return {"requirements": stored_req, "test_cases": tc_list}


def init_db() -> None:
    with open_memory_db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS ticket_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jira_key TEXT NOT NULL,
            requirements_json TEXT NOT NULL,
            test_cases_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_ticket_memory_key ON ticket_memory(jira_key)")


def _norm_req_text(req: dict) -> str:
    t = _WS.sub(" ", str(req.get("title") or "").strip()).casefold()
    d = _WS.sub(" ", str(req.get("description") or "").strip()).casefold()
    return f"title: {t}\n\ndescription:\n{d}"


def normalized_paste_key_material(title: str, description: str) -> str:
    t = _WS.sub(" ", str(title or "").strip())
    d = _WS.sub(" ", str(description or "").strip())
    return f"{t}\n{d}"


def find_similar_memory(req: dict, threshold: float) -> tuple[str | None, dict | None]:
    if threshold <= 0:
        return None, None
    target = _norm_req_text(req)
    if len(target) < 12:
        return None, None
    with open_memory_db() as c:
        rows = c.execute(
            "SELECT jira_key, requirements_json, test_cases_json FROM ticket_memory"
        ).fetchall()
    best_key: str | None = None
    best_score = 0.0
    best_prev: dict | None = None
    for row in rows:
        k = row["jira_key"]
        stored_req = _loads_req(row["requirements_json"])
        if stored_req is None:
            continue
        cand = _norm_req_text(stored_req)
        score = difflib.SequenceMatcher(None, target, cand).ratio()
        if score > best_score:
            best_score = score
            best_key = str(k)
            best_prev = _prev_bundle(stored_req, row["test_cases_json"])
    if best_score >= threshold and best_prev and best_key:
        return best_key.upper(), best_prev
    return None, None


_DEFAULT_PASTE_TITLE_CF = _WS.sub(" ", "Pasted requirements").strip().casefold()


def _is_test_hash_key(k: str) -> bool:
    return bool(_TEST_HASH_KEY.match(norm_issue_key(str(k or ""))))


_JIRA_STYLE_MEMORY_KEY = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")


def _is_jira_style_memory_key(k: str) -> bool:
    s = norm_issue_key(str(k or ""))
    if not s or _is_test_hash_key(s):
        return False
    return bool(_JIRA_STYLE_MEMORY_KEY.match(s))


def find_jira_history_key_for_same_requirements(req: dict, *, exclude_key: str | None = None) -> str | None:
    """Another saved row (JIRA-shaped key) with identical normalized requirements text."""
    if not isinstance(req, dict):
        return None
    target = _norm_req_text(req)
    if len(target) < 12:
        return None
    ex = norm_issue_key(exclude_key or "")
    with open_memory_db() as c:
        rows = c.execute(
            "SELECT jira_key, requirements_json FROM ticket_memory ORDER BY updated_at DESC"
        ).fetchall()
    for row in rows:
        mk = str(row["jira_key"] or "").strip()
        if not mk:
            continue
        ku = norm_issue_key(mk)
        if ex and ku == ex:
            continue
        if not _is_jira_style_memory_key(ku):
            continue
        stored = _loads_req(row["requirements_json"])
        if stored is None:
            continue
        if _norm_req_text(stored) != target:
            continue
        return ku
    return None


def find_latest_memory_by_title(req: dict) -> tuple[str | None, dict | None]:
    if not isinstance(req, dict):
        return None, None
    t = _WS.sub(" ", str(req.get("title") or "").strip()).casefold()
    if len(t) < 4 or t == _DEFAULT_PASTE_TITLE_CF:
        return None, None
    candidates: list[tuple[str, str, dict]] = []
    with open_memory_db() as c:
        rows = c.execute(
            "SELECT jira_key, requirements_json, test_cases_json, updated_at FROM ticket_memory"
        ).fetchall()
    for row in rows:
        stored_req = _loads_req(row["requirements_json"])
        if stored_req is None:
            continue
        st = _WS.sub(" ", str(stored_req.get("title") or "").strip()).casefold()
        if st != t:
            continue
        k = str(row["jira_key"])
        ts = str(row["updated_at"] or "")
        prev = _prev_bundle(stored_req, row["test_cases_json"])
        if prev is None:
            continue
        candidates.append((k, ts, prev))
    if not candidates:
        return None, None
    k, _, prev = max(candidates, key=lambda x: (not _is_test_hash_key(x[0]), x[1]))
    return k.upper(), prev


def get_latest(key: str) -> dict | None:
    k = key.upper()
    with open_memory_db() as c:
        row = c.execute(
            "SELECT requirements_json, test_cases_json FROM ticket_memory WHERE jira_key=? ORDER BY id DESC LIMIT 1",
            (k,),
        ).fetchone()
    if not row:
        return None
    rj = _loads_req(row[0])
    if rj is None:
        rj = {}
    tc = _loads_tc_list(row[1])
    return {"requirements": rj, "test_cases": tc}


def list_saved() -> list[dict]:
    with open_memory_db() as c:
        rows = c.execute(
            """
            SELECT jira_key, created_at, updated_at, requirements_json, test_cases_json
            FROM ticket_memory
            ORDER BY updated_at DESC
            """
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        req = _loads_req(row[3])
        if req is None:
            continue
        try:
            tc_raw = json.loads(row[4])
        except (json.JSONDecodeError, TypeError):
            continue
        n = len(tc_raw) if isinstance(tc_raw, list) else 0
        out.append(
            {
                "ticket_id": row[0],
                "title": (req.get("title") or "")[:200],
                "created_at": row[1],
                "updated_at": row[2],
                "test_case_count": n,
            }
        )
    return out


def save(jira_key: str, requirements: dict, test_cases: list) -> None:
    k, now = jira_key.upper(), datetime.now(timezone.utc).isoformat()
    tcs = list(test_cases) if isinstance(test_cases, list) else []
    rj, tj = json.dumps(requirements, ensure_ascii=False), json.dumps(tcs, ensure_ascii=False)
    with open_memory_db() as c:
        prev = c.execute(
            "SELECT id FROM ticket_memory WHERE jira_key=? ORDER BY id DESC LIMIT 1",
            (k,),
        ).fetchone()
        if prev:
            c.execute(
                "UPDATE ticket_memory SET requirements_json=?, test_cases_json=?, updated_at=? WHERE id=?",
                (rj, tj, now, prev["id"]),
            )
        else:
            c.execute(
                "INSERT INTO ticket_memory (jira_key, requirements_json, test_cases_json, created_at, updated_at) VALUES (?,?,?,?,?)",
                (k, rj, tj, now, now),
            )


def _normalize_ws_tc(s: str) -> str:
    return _WS.sub(" ", str(s or "").strip())


def _tc_fingerprint_canonical(tc: dict) -> str:
    if not isinstance(tc, dict):
        return "\x00"
    d = _normalize_ws_tc(str(tc.get("description") or "")).lower()
    steps = tc.get("steps") if isinstance(tc.get("steps"), list) else []
    step_parts = [_normalize_ws_tc(str(x)).lower() for x in steps]
    return d + "\x00" + "\x01".join(step_parts)


def _fnv1a32(s: str) -> int:
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _to_base36(n: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out: list[str] = []
    while n:
        n, r = divmod(n, 36)
        out.append(alphabet[r])
    return "".join(reversed(out))


def jira_push_fingerprint(tc: dict) -> str:
    raw = _tc_fingerprint_canonical(tc)
    return "h" + _to_base36(_fnv1a32(raw))


def merge_test_case_into_memory(jira_key: str, requirements: dict, test_case: dict) -> None:
    k = jira_key.upper()
    test_case = strip_test_case_diff_meta(test_case) if isinstance(test_case, dict) else test_case
    fp_new = jira_push_fingerprint(test_case)
    latest = get_latest(k)
    if not latest:
        req = requirements if isinstance(requirements, dict) else {}
        save(k, req, [test_case])
        return
    tcs = list(latest["test_cases"])
    for i, tc in enumerate(tcs):
        if isinstance(tc, dict) and jira_push_fingerprint(tc) == fp_new:
            tcs[i] = test_case
            save(k, latest["requirements"], tcs)
            return
    tcs.append(test_case)
    save(k, latest["requirements"], tcs)
