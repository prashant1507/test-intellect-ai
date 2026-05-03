import sqlite3
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"


def open_sqlite(filename: str) -> sqlite3.Connection:
    _DATA.mkdir(parents=True, exist_ok=True)
    base = _DATA.resolve()
    name = str(filename or "").strip().replace("\\", "/")
    if not name or Path(name).is_absolute():
        raise ValueError("invalid sqlite filename")
    path = (base / name).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise ValueError("invalid sqlite filename") from None
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    return c


def opend_saved_history_db():
    return open_sqlite("saved_history.db")


def open_audit_db():
    return open_sqlite("audit.db")
