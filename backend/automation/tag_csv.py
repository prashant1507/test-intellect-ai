from __future__ import annotations


def _normalize_one_tag_segment(p: str) -> str:
    t = " ".join(str(p).split())
    return t


def parse_tag_tokens(s: str | None) -> list[str]:
    return [
        t
        for t in (_normalize_one_tag_segment(p) for p in str(s or "").split(","))
        if t
    ]


def parse_jira_key_tokens(
    s: str | None, *, max_keys: int = 80, max_key_len: int = 200
) -> list[str]:
    out = [p.strip() for p in str(s or "").split(",") if p.strip()][:max_keys]
    return [p[:max_key_len] for p in out]


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
