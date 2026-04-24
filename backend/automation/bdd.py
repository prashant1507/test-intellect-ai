from __future__ import annotations

import re
from typing import Any

_GH = re.compile(r"^(Given|When|Then|And)\b", re.I)
_SKIP = re.compile(r"^(Feature|Scenario|Background)\b", re.I)


def parse_bdd_step_lines(bdd: str) -> list[str]:
    out: list[str] = []
    for line in (bdd or "").splitlines():
        s = line.strip()
        if not s or _SKIP.match(s):
            continue
        if _GH.match(s):
            out.append(s)
    return out


def parse_bdd_structured(bdd: str) -> list[dict[str, Any]]:
    return []
