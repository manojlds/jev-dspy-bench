from jev_dspy_bench.metrics import reference_score
from jev_dspy_bench.normalize import normalize_decisions
from jev_dspy_bench.rubric import METRICS, build_questions
from jev_dspy_bench.schema import METRIC_KEYS, RawMetricDecision


def test_rubric_has_three_questions_for_every_metric() -> None:
    questions = build_questions()
    assert tuple(metric.key for metric in METRICS) == METRIC_KEYS
    assert len(questions) == 57
    for metric in METRICS:
        assert f"{metric.key}_applicable" in questions
        assert f"{metric.key}_score" in questions
        assert f"{metric.key}_weakness" in questions


def test_reference_score_rewards_dimension_and_priority_alignment() -> None:
    decisions: dict[str, RawMetricDecision] = {
        metric.key: RawMetricDecision(
            applicable=True,
            score=3 if metric.key == "correctness" else 9,
            weakness="regression_risk" if metric.key == "correctness" else "no_material_issue",
        )
        for metric in METRICS
    }
    scorecard = normalize_decisions("test", decisions)
    reference = {
        "dimensions": {
            metric: "weak" if metric == "correctness" else "acceptable" for metric in METRIC_KEYS
        },
        "priorities": ["correctness"],
    }
    assert reference_score(reference, scorecard) == 1.0

    reference["dimensions"]["correctness"] = "acceptable"
    reference["priorities"] = []
    assert reference_score(reference, scorecard) < 1.0
