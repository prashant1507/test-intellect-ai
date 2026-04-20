from __future__ import annotations

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


class ValidatorResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dimensions: DimensionScores
    issues: list[str] = Field(default_factory=list)
    must_fix: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

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
