from __future__ import annotations

import re
from typing import Any

_GH = re.compile(r"^(Given|When|Then|And|But)\b", re.I)
_SKIP = re.compile(r"^(Feature|Rule|Scenario|Background)\b", re.I)


def parse_bdd_step_lines(bdd: str) -> list[str]:
    out: list[str] = []
    cur: str | None = None
    doc: list[str] | None = None
    for raw in (bdd or "").splitlines():
        st = raw.strip()
        if doc is not None:
            if st in ('"""', "'''"):
                inner = "\n".join(doc).strip()
                if cur is not None:
                    cur = cur + "\n" + inner
                else:
                    cur = inner
                doc = None
            else:
                doc.append(raw)
            continue
        if not st:
            continue
        if st.startswith("#"):
            continue
        if _SKIP.match(st) and not _GH.match(st):
            continue
        if _GH.match(st):
            if cur is not None:
                out.append(cur)
            cur = st
        elif cur is not None:
            if st in ('"""', "'''"):
                doc = []
            elif st.startswith('"""') and st.endswith('"""') and len(st) > 6:
                cur = cur + "\n" + st[3:-3].strip()
            else:
                cur = cur + "\n" + raw.rstrip()
    if cur is not None:
        if doc is not None:
            cur = cur + "\n" + "\n".join(doc)
        out.append(cur)
    return out


def parse_bdd_structured(bdd: str) -> list[dict[str, Any]]:
    return []
