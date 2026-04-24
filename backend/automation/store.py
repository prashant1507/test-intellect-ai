from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from settings import settings

from .tag_csv import normalize_tag_csv


def _connect() -> sqlite3.Connection:
    p = Path(settings.automation_db_path)
    if p.exists() and p.is_dir():
        raise RuntimeError(
            f"AUTOMATION_DB_PATH must be a file, not a directory: {p!s}"
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_automation_db() -> None:
    c = _connect()
    try:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS automation_runs (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              title TEXT NOT NULL,
              fingerprint TEXT NOT NULL,
              error TEXT,
              trace_path TEXT,
              summary_json TEXT,
              used_cache INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_automation_runs_fp
              ON automation_runs(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_automation_runs_created_at
              ON automation_runs(created_at);
            CREATE TABLE IF NOT EXISTS automation_suite_case_run_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              status TEXT NOT NULL,
              finished_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_suite_hist_case
              ON automation_suite_case_run_history(case_id);
            CREATE TABLE IF NOT EXISTS automation_run_steps (
              run_id TEXT NOT NULL,
              step_index INTEGER NOT NULL,
              step_text TEXT NOT NULL,
              selector TEXT NOT NULL,
              action TEXT NOT NULL,
              value TEXT,
              pass INTEGER NOT NULL DEFAULT 0,
              err TEXT,
              source TEXT,
              screenshot_path TEXT,
              PRIMARY KEY (run_id, step_index)
            );
            CREATE TABLE IF NOT EXISTS automation_selector_cache (
              fingerprint TEXT NOT NULL,
              step_index INTEGER NOT NULL,
              step_text TEXT NOT NULL,
              selector TEXT NOT NULL,
              action TEXT NOT NULL,
              value TEXT,
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              PRIMARY KEY (fingerprint, step_index)
            );
            CREATE TABLE IF NOT EXISTS automation_suite_cases (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              sort_order INTEGER NOT NULL,
              title TEXT NOT NULL,
              bdd TEXT NOT NULL,
              url TEXT NOT NULL,
              html_dom TEXT,
              last_suite_analysis TEXT,
              last_suite_analysis_at TEXT,
              last_suite_run_id TEXT
            );
            CREATE TABLE IF NOT EXISTS automation_kv (
              k TEXT PRIMARY KEY,
              v TEXT NOT NULL
            );
            """
        )
        r = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='automation_suite_cases'"
        ).fetchone()
        if r:
            cols = {x[1] for x in c.execute("PRAGMA table_info(automation_suite_cases)")}
            if "jira_id" not in cols:
                c.execute("ALTER TABLE automation_suite_cases ADD COLUMN jira_id TEXT")
            if "last_suite_analysis" not in cols:
                c.execute(
                    "ALTER TABLE automation_suite_cases ADD COLUMN last_suite_analysis TEXT"
                )
            if "last_suite_analysis_at" not in cols:
                c.execute(
                    "ALTER TABLE automation_suite_cases ADD COLUMN last_suite_analysis_at TEXT"
                )
            if "last_suite_run_id" not in cols:
                c.execute("ALTER TABLE automation_suite_cases ADD COLUMN last_suite_run_id TEXT")
            if "tag" not in cols:
                c.execute("ALTER TABLE automation_suite_cases ADD COLUMN tag TEXT")
            if "requirement_ticket_id" not in cols:
                c.execute(
                    "ALTER TABLE automation_suite_cases ADD COLUMN requirement_ticket_id TEXT"
                )
        c.commit()
    finally:
        c.close()


def begin_run(
    run_id: str, title: str, fingerprint: str, *, error: str | None = None
) -> None:
    c = _connect()
    try:
        c.execute(
            """
            INSERT INTO automation_runs
              (id, created_at, status, title, fingerprint, error, trace_path,
               summary_json, used_cache)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0)
            """,
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                "running",
                title,
                fingerprint,
                error,
            ),
        )
        c.commit()
    finally:
        c.close()


def update_run(
    run_id: str,
    *,
    status: str,
    error: str | None = None,
    trace_path: str | None = None,
    summary: dict | None = None,
    used_cache: bool = False,
) -> None:
    c = _connect()
    try:
        c.execute(
            """
            UPDATE automation_runs
            SET status=?, error=?, trace_path=?, summary_json=?, used_cache=?
            WHERE id=?
            """,
            (
                status,
                error,
                trace_path,
                json.dumps(summary) if summary is not None else None,
                1 if used_cache else 0,
                run_id,
            ),
        )
        c.commit()
    finally:
        c.close()


def replace_run_steps(run_id: str, steps: list[dict]) -> None:
    c = _connect()
    try:
        c.execute("DELETE FROM automation_run_steps WHERE run_id=?", (run_id,))
        for s in steps:
            c.execute(
                """
                INSERT INTO automation_run_steps
                  (run_id, step_index, step_text, selector, action, value,
                   pass, err, source, screenshot_path)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    s["step_index"],
                    s["step_text"],
                    s["selector"],
                    s["action"],
                    s.get("value") or "",
                    1 if s.get("pass") else 0,
                    s.get("err"),
                    s.get("source") or "llm",
                    s.get("screenshot_path"),
                ),
            )
        c.commit()
    finally:
        c.close()


def load_selector_cache(
    fp: str, expected_count: int
) -> list[dict] | None:
    c = _connect()
    try:
        cur = c.execute(
            """
            SELECT step_index, step_text, selector, action, value
            FROM automation_selector_cache
            WHERE fingerprint=? ORDER BY step_index ASC
            """,
            (fp,),
        )
        rows = [dict(x) for x in cur.fetchall()]
        if len(rows) != expected_count:
            return None
        return rows
    finally:
        c.close()


def upsert_selector_cache(fp: str, steps: list[dict]) -> None:
    c = _connect()
    try:
        for s in steps:
            c.execute(
                """
                INSERT INTO automation_selector_cache
                  (fingerprint, step_index, step_text, selector, action, value, updated_at)
                VALUES (?,?,?,?,?,?, datetime('now'))
                ON CONFLICT(fingerprint, step_index) DO UPDATE SET
                  step_text=excluded.step_text,
                  selector=excluded.selector,
                  action=excluded.action,
                  value=excluded.value,
                  updated_at=datetime('now')
                """,
                (
                    fp,
                    s["step_index"],
                    s["step_text"],
                    s["selector"],
                    s["action"],
                    s.get("value") or "",
                ),
            )
        c.commit()
    finally:
        c.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    c = _connect()
    try:
        r1 = c.execute("SELECT * FROM automation_runs WHERE id=?", (run_id,)).fetchone()
        if r1 is None:
            return None
        r2 = c.execute(
            "SELECT * FROM automation_run_steps WHERE run_id=? ORDER BY step_index ASC",
            (run_id,),
        )
        return {"row": dict(r1), "steps": [dict(x) for x in r2.fetchall()]}
    finally:
        c.close()


def list_selector_cache_rows(limit: int) -> list[dict[str, Any]]:
    c = _connect()
    try:
        cur = c.execute(
            """
            SELECT rowid, fingerprint, step_index, step_text, selector, action, value, updated_at
            FROM automation_selector_cache ORDER BY updated_at DESC LIMIT ?
            """,
            (min(max(limit, 1), 500),),
        )
        return [dict(x) for x in cur.fetchall()]
    finally:
        c.close()


def delete_selector_cache_by_rowid(rowid: int) -> bool:
    c = _connect()
    try:
        c.execute("DELETE FROM automation_selector_cache WHERE rowid=?", (rowid,))
        c.commit()
        return c.total_changes > 0
    finally:
        c.close()


def list_suite_cases() -> list[dict[str, Any]]:
    c = _connect()
    try:
        cur = c.execute(
            """
            SELECT
              s.*,
              r.status AS last_suite_run_status
            FROM automation_suite_cases s
            LEFT JOIN automation_runs r ON r.id = s.last_suite_run_id
            ORDER BY s.sort_order ASC, s.created_at ASC
            """
        )
        return [dict(x) for x in cur.fetchall()]
    finally:
        c.close()


def get_suite_case(case_id: str) -> dict[str, Any] | None:
    c = _connect()
    try:
        r = c.execute("SELECT * FROM automation_suite_cases WHERE id=?", (case_id,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def would_duplicate_suite_case(title: str, jira_id: str) -> str | None:
    t = (title or "").strip() or "Untitled"
    j = (jira_id or "").strip()
    c = _connect()
    try:
        if j:
            r = c.execute(
                """
                SELECT 1 FROM automation_suite_cases
                WHERE jira_id IS NOT NULL
                  AND TRIM(COALESCE(jira_id, '')) != ''
                  AND LOWER(TRIM(jira_id)) = LOWER(?)
                """,
                (j,),
            ).fetchone()
            if r:
                return "A saved suite case with this Test ID already exists."
        else:
            r = c.execute(
                """
                SELECT 1 FROM automation_suite_cases
                WHERE (jira_id IS NULL OR TRIM(COALESCE(jira_id, '')) = '')
                  AND TRIM(title) = ?
                """,
                (t,),
            ).fetchone()
            if r:
                return "A saved suite case with this scenario name already exists."
    finally:
        c.close()
    return None


def add_suite_case(
    title: str,
    bdd: str,
    url: str,
    html_dom: str,
    *,
    jira_id: str = "",
    tag: str = "",
    requirement_ticket_id: str = "",
    case_id: str | None = None,
) -> str:
    cid = (case_id or str(uuid.uuid4())).strip() or str(uuid.uuid4())
    jira = (jira_id or "").strip() or None
    ta = normalize_tag_csv(tag) or None
    reqt = (requirement_ticket_id or "").strip() or None
    c = _connect()
    try:
        mx = c.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM automation_suite_cases"
        ).fetchone()[0]
        c.execute(
            """
            INSERT INTO automation_suite_cases
              (id, created_at, sort_order, title, bdd, url, html_dom, jira_id, tag, requirement_ticket_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid,
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                int(mx),
                title.strip() or "Untitled",
                bdd,
                url.strip(),
                (html_dom or "").strip() or None,
                jira,
                ta,
                reqt,
            ),
        )
        c.commit()
    finally:
        c.close()
    return cid


def delete_suite_case(case_id: str) -> bool:
    c = _connect()
    try:
        t = (case_id or "").strip()
        if not c.execute("SELECT 1 FROM automation_suite_cases WHERE id=?", (t,)).fetchone():
            return False
        c.execute("DELETE FROM automation_suite_case_run_history WHERE case_id=?", (t,))
        c.execute("DELETE FROM automation_suite_cases WHERE id=?", (t,))
        c.commit()
        return True
    finally:
        c.close()


def append_suite_case_run_history(case_id: str, run_id: str, status: str) -> None:
    cid = (case_id or "").strip()
    if not cid:
        return
    c = _connect()
    try:
        at = datetime.now(timezone.utc).isoformat()
        c.execute(
            """
            INSERT INTO automation_suite_case_run_history
              (case_id, run_id, status, finished_at)
            VALUES (?,?,?,?)
            """,
            (cid, (run_id or "").strip(), (status or "").strip() or "—", at),
        )
        c.commit()
    finally:
        c.close()


def list_suite_case_run_history(case_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    t = (case_id or "").strip()
    if not t:
        return []
    lim = min(max(int(limit), 1), 500)
    c = _connect()
    try:
        cur = c.execute(
            """
            SELECT run_id, status, finished_at
            FROM automation_suite_case_run_history
            WHERE case_id=?
            ORDER BY finished_at DESC, id DESC
            LIMIT ?
            """,
            (t, lim),
        )
        return [dict(x) for x in cur.fetchall()]
    finally:
        c.close()


def set_suite_case_last_analysis(
    case_id: str, text: str, *, run_id: str | None = None
) -> None:
    cid = (case_id or "").strip()
    if not cid:
        return
    c = _connect()
    try:
        at = datetime.now(timezone.utc).isoformat()
        rid = (run_id or "").strip()
        if rid:
            c.execute(
                "UPDATE automation_suite_cases SET last_suite_analysis=?, "
                "last_suite_analysis_at=?, last_suite_run_id=? WHERE id=?",
                (text, at, rid, cid),
            )
        else:
            c.execute(
                "UPDATE automation_suite_cases SET last_suite_analysis=?, last_suite_analysis_at=? "
                "WHERE id=?",
                (text, at, cid),
            )
        c.commit()
    finally:
        c.close()


def set_suite_case_last_run_id_only(case_id: str, run_id: str) -> None:
    cid = (case_id or "").strip()
    rid = (run_id or "").strip()
    if not cid or not rid:
        return
    c = _connect()
    try:
        c.execute(
            "UPDATE automation_suite_cases SET last_suite_run_id=? WHERE id=?",
            (rid, cid),
        )
        c.commit()
    finally:
        c.close()


def get_automation_kv(key: str) -> str | None:
    k = (key or "").strip()
    if not k:
        return None
    c = _connect()
    try:
        r = c.execute("SELECT v FROM automation_kv WHERE k=?", (k,)).fetchone()
        if r is None:
            return None
        return str(r["v"])
    finally:
        c.close()


def set_automation_kv(key: str, value: str) -> None:
    k = (key or "").strip()
    if not k:
        return
    c = _connect()
    try:
        c.execute(
            "INSERT INTO automation_kv (k, v) VALUES (?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, (value or "").strip()),
        )
        c.commit()
    finally:
        c.close()
