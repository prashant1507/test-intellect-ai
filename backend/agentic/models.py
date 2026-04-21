from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class TestCaseItem(BaseModel):
    description: str
    preconditions: str = ""
    expected_result: str = ""
    steps: list[str]
    change_status: str = "new"
    priority: str


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
        return x
    if isinstance(x, dict):
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

    @field_validator("issues", "must_fix", "suggestions", mode="before")
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
