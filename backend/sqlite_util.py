import sqlite3
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"


def open_sqlite(filename: str):
    _DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DATA / filename))
    c.row_factory = sqlite3.Row
    return c
