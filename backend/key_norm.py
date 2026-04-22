from __future__ import annotations


def norm_issue_key(s: str) -> str:
    return (s or "").strip().upper()
