from __future__ import annotations

from datetime import datetime, timezone

from key_norm import norm_issue_key
from sqlite_util import open_audit_db


def init_audit_db() -> None:
    with open_audit_db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            username TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            action TEXT NOT NULL,
            jira_username TEXT NOT NULL DEFAULT ''
        )"""
        )
        cols = {row[1] for row in c.execute("PRAGMA table_info(audit_log)")}
        if "jira_username" not in cols:
            c.execute("ALTER TABLE audit_log ADD COLUMN jira_username TEXT NOT NULL DEFAULT ''")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC)")


def append_audit(username: str, ticket_id: str, action: str, jira_username: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    u = (username or "").strip()
    k = norm_issue_key(ticket_id)
    a = (action or "").strip()
    ju = (jira_username or "").strip()
    if not k or not a:
        return
    with open_audit_db() as c:
        c.execute(
            "INSERT INTO audit_log (created_at, username, ticket_id, action, jira_username) VALUES (?,?,?,?,?)",
            (now, u, k, a, ju),
        )


def list_audit(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    with open_audit_db() as c:
        rows = c.execute(
            "SELECT created_at, username, ticket_id, action, jira_username FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
