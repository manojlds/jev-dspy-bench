from jev_dspy_bench.normalize import normalize_decisions, normalize_jev_response
from jev_dspy_bench.rubric import METRICS
from jev_dspy_bench.schema import ApplicableMetric, RawMetricDecision


def test_normalizes_decisions_and_prioritizes_weighted_metrics() -> None:
    decisions: dict[str, RawMetricDecision] = {
        metric.key: RawMetricDecision(
            applicable=True,
            score=7,
            weakness="no_material_issue",
        )
        for metric in METRICS
    }
    decisions["security"] = RawMetricDecision(applicable=True, score=4, weakness="authorization")
    decisions["correctness"] = RawMetricDecision(
        applicable=True, score=4, weakness="missing_behavior"
    )
    scorecard = normalize_decisions("test/model", decisions)

    assert [item.metric for item in scorecard.priorities[:2]] == ["correctness", "security"]
    security = scorecard.metrics["security"]
    assert isinstance(security, ApplicableMetric)
    assert security.issues is not None
    assert security.issues[0].severity == "medium"


def test_jev_threshold_and_confidence_match_drs() -> None:
    answers = {}
    for metric in METRICS:
        answers[f"{metric.key}_applicable"] = {"type": "noul", "noul": 0.5}
        answers[f"{metric.key}_score"] = {"type": "score", "score": 6.5, "confidence": 0.9}
        answers[f"{metric.key}_weakness"] = {
            "type": "choice",
            "choice": "no_material_issue",
        }
    scorecard = normalize_jev_response(
        {
            "model": "jev-1.13.0",
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )
    metric = scorecard.metrics["correctness"]
    assert isinstance(metric, ApplicableMetric)
    assert metric.score == 7.5
    assert metric.confidence == 0.5
    assert scorecard.usage.total_tokens == 15
    assert scorecard.usage.cost == 10 * 0.042 / 1_000_000
