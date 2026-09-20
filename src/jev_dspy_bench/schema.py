from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MetricKey = Literal[
    "correctness",
    "cognitiveComplexity",
    "readability",
    "modularity",
    "coupling",
    "changeability",
    "abstractionQuality",
    "projectStructure",
    "duplication",
    "maintainability",
    "testQuality",
    "reliability",
    "security",
    "consistency",
    "documentation",
    "performance",
    "scalability",
    "compatibility",
    "observability",
]

METRIC_KEYS: tuple[MetricKey, ...] = (
    "correctness",
    "cognitiveComplexity",
    "readability",
    "modularity",
    "coupling",
    "changeability",
    "abstractionQuality",
    "projectStructure",
    "duplication",
    "maintainability",
    "testQuality",
    "reliability",
    "security",
    "consistency",
    "documentation",
    "performance",
    "scalability",
    "compatibility",
    "observability",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewState(StrictModel):
    task: str
    diff: str
    repositoryContext: str


class MetricIssue(StrictModel):
    severity: Literal["low", "medium", "high"]
    description: str
    suggestion: str | None = None


class NotApplicableMetric(StrictModel):
    applicable: Literal[False]


class ApplicableMetric(StrictModel):
    applicable: Literal[True]
    score: Annotated[float, Field(ge=1, le=10)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    summary: str
    issues: list[MetricIssue] | None = None


MetricEvaluation = Annotated[
    NotApplicableMetric | ApplicableMetric, Field(discriminator="applicable")
]


class Priority(StrictModel):
    metric: MetricKey
    severity: Literal["low", "medium", "high"]
    reason: str


class Usage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)


class Scorecard(StrictModel):
    model: str
    metrics: dict[str, MetricEvaluation]
    priorities: list[Priority] = Field(max_length=5)
    usage: Usage

    @model_validator(mode="after")
    def all_metrics_present(self) -> Scorecard:
        if set(self.metrics) != set(METRIC_KEYS):
            missing = sorted(set(METRIC_KEYS) - set(self.metrics))
            extra = sorted(set(self.metrics) - set(METRIC_KEYS))
            raise ValueError(f"scorecard metric mismatch: missing={missing}, extra={extra}")
        return self


class RawMetricDecision(StrictModel):
    applicable: bool
    score: int = Field(ge=1, le=10)
    weakness: str


class RawMetricBatch(StrictModel):
    metrics: dict[str, RawMetricDecision]


class ExpectedFinding(StrictModel):
    id: str
    description: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    category: Literal["SECURITY", "QUALITY", "STYLE", "PERFORMANCE", "DOCUMENTATION"]
    file: str
    line: int | None = Field(default=None, ge=1)
    endLine: int | None = Field(default=None, ge=1)


class Comparison(StrictModel):
    group: str
    variant: str


class JevExpectation(StrictModel):
    expectedWeakDimensions: list[MetricKey] = Field(min_length=1)


class CaseMetadata(StrictModel):
    id: str
    description: str
    dimensions: list[str] = Field(default_factory=list)
    comparison: Comparison | None = None
    jev: JevExpectation | None = None
    expected: list[ExpectedFinding]


class SuiteManifest(StrictModel):
    name: str
    description: str | None = None
    focus: str | None = None
    cases: list[str]
