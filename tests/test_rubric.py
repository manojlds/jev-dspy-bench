from jev_dspy_bench.rubric import METRICS, build_questions
from jev_dspy_bench.schema import METRIC_KEYS


def test_rubric_has_three_questions_for_every_metric() -> None:
    questions = build_questions()
    assert tuple(metric.key for metric in METRICS) == METRIC_KEYS
    assert len(questions) == 57
    for metric in METRICS:
        assert f"{metric.key}_applicable" in questions
        assert f"{metric.key}_score" in questions
        assert f"{metric.key}_weakness" in questions
