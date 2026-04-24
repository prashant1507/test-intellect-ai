"""Comma-separated tag lists: parse tokens and normalize stored form."""

from __future__ import annotations


def _normalize_one_tag_segment(p: str) -> str:
    """Trim and collapse internal runs of whitespace in one CSV segment."""
    t = " ".join(str(p).split())
    return t


def parse_tag_tokens(s: str | None) -> list[str]:
    return [
        t
        for t in (_normalize_one_tag_segment(p) for p in str(s or "").split(","))
        if t
    ]


def normalize_tag_csv(s: str | None, *, max_len: int = 200) -> str:
    parts = parse_tag_tokens(s)
    if not parts:
        return ""
    while parts:
        out = ", ".join(parts)
        if len(out) <= max_len:
            return out
        if len(parts) == 1:
            return parts[0][:max_len]
        parts.pop()
    return ""
