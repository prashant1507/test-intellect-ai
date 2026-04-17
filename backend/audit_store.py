from __future__ import annotations

from datetime import datetime, timezone

from sqlite_util import open_sqlite


def _db():
    return open_sqlite("audit.db")


def init_audit_db() -> None:
    with _db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            username TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            action TEXT NOT NULL
        )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC)")


def append_audit(username: str, ticket_id: str, action: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    u = (username or "").strip()
    k = (ticket_id or "").strip().upper()
    a = (action or "").strip()
    if not k or not a:
        return
    with _db() as c:
        c.execute(
            "INSERT INTO audit_log (created_at, username, ticket_id, action) VALUES (?,?,?,?)",
            (now, u, k, a),
        )


def list_audit(limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, 500))
    with _db() as c:
        rows = c.execute(
            "SELECT created_at, username, ticket_id, action FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
