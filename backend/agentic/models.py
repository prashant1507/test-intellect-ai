from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class CoveragePlannerItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=32)
    intent: str = Field(min_length=1, max_length=500)
    category: str = Field(default="", max_length=64)


class CoveragePlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[CoveragePlannerItem] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class TestCaseItem(BaseModel):
    description: str
    preconditions: str = ""
    expected_result: str = ""
    steps: list[str]
    change_status: str = "new"
    priority: str
    severity: str = ""


class GenerationEnvelope(BaseModel):
    test_cases: list[TestCaseItem]


class DimensionScores(BaseModel):
    model_config = ConfigDict(extra="ignore")

    traceability: int = Field(ge=0, le=5)
    coverage: int = Field(ge=0, le=5)
    gherkin_structure: int = Field(ge=0, le=5)
    concreteness: int = Field(ge=0, le=5)
    non_redundancy: int = Field(ge=0, le=5)

    @field_validator("*", mode="before")
    @classmethod
    def _int(cls, v: object) -> int:
        if isinstance(v, bool):
            return int(v)
        x = float(v)
        return int(max(0, min(5, round(x))))


def _coerce_validator_line(x: object) -> str:
    if isinstance(x, str):
        t = x.strip()
        if len(t) >= 2 and t[0] == "{" and t[-1] == "}":
            try:
                d = json.loads(t)
                if isinstance(d, dict):
                    return _coerce_validator_line(d)
            except json.JSONDecodeError:
                pass
        return x
    if isinstance(x, dict):
        rsn = x.get("reason")
        sidx = x.get("scenario_index", x.get("scenarioIndex"))
        if rsn is not None and str(rsn).strip() and sidx is not None and str(sidx).strip() != "":
            return f"Scenario {sidx}: {str(rsn).strip()}"
        sug = x.get("suggestion")
        if sug is not None and str(sug).strip():
            s = str(sug).strip()
            ref = x.get("requirement_ref")
            r = str(ref).strip() if ref is not None else ""
            return f"{s} — {r}" if r else s
        iss = x.get("issue")
        if iss is not None and str(iss).strip():
            s = str(iss).strip()
            ref = x.get("requirement_ref")
            sev = x.get("severity")
            lead = f"[{str(sev).strip()}] " if sev is not None and str(sev).strip() else ""
            tail = f" ({str(ref).strip()})" if ref is not None and str(ref).strip() else ""
            return f"{lead}{s}{tail}"
        dim = x.get("dimension")
        body = next(
            (x.get(k) for k in ("text", "message", "detail", "description", "finding") if x.get(k)),
            None,
        )
        if body is not None:
            s = str(body).strip()
            if dim is not None and str(dim).strip():
                return f"{dim}: {s}"
            return s
        return json.dumps(x, ensure_ascii=False)
    return str(x)


class ValidatorResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dimensions: DimensionScores
    issues: list[str] = Field(default_factory=list)
    must_fix: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)

    @field_validator("issues", "must_fix", "suggestions", "coverage_gaps", mode="before")
    @classmethod
    def _issues_as_strings(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [_coerce_validator_line(x) for x in v]

    @computed_field
    @property
    def aggregate(self) -> float:
        d = self.dimensions
        return (
            0.25 * d.traceability
            + 0.25 * d.coverage
            + 0.2 * d.gherkin_structure
            + 0.15 * d.concreteness
            + 0.15 * d.non_redundancy
        )

    def min_dimension(self) -> int:
        d = self.dimensions
        return min(
            d.traceability,
            d.coverage,
            d.gherkin_structure,
            d.concreteness,
            d.non_redundancy,
        )
