import json

import httpx

from jev_dspy_bench.program import _batch_error, _valid_batch
from jev_dspy_bench.providers.direct import _parse_batch, build_prompt
from jev_dspy_bench.providers.jev import JEV_ENDPOINT, JevEvaluator
from jev_dspy_bench.rubric import METRICS
from jev_dspy_bench.schema import RawMetricBatch, RawMetricDecision, ReviewState


def test_direct_baseline_uses_drs_array_contract() -> None:
    batch = tuple(METRICS[:2])
    prompt = build_prompt('{"task":"test"}', batch)
    assert "three-item array" in prompt
    raw = {"metrics": {metric.key: [True, 7, "no_material_issue"] for metric in batch}}
    parsed = _parse_batch(raw, batch)
    assert set(parsed) == {"correctness", "cognitiveComplexity"}


def test_dspy_batch_rejects_weakness_from_another_metric() -> None:
    batch = tuple(METRICS[:2])
    valid = RawMetricBatch(
        metrics={
            metric.key: RawMetricDecision(applicable=True, score=7, weakness="no_material_issue")
            for metric in batch
        }
    )
    assert _valid_batch(valid, batch)
    valid.metrics["correctness"].weakness = "control_flow"
    assert not _valid_batch(valid, batch)
    assert _batch_error(valid, batch) == (
        "correctness.weakness='control_flow' must be one of "
        "['edge_case', 'incorrect_assumption', 'missing_behavior', 'no_material_issue', "
        "'regression_risk']"
    )


def test_jev_adapter_sends_native_questions_and_normalizes() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        answers = {}
        for metric in METRICS:
            answers[f"{metric.key}_applicable"] = {"type": "noul", "noul": 1}
            answers[f"{metric.key}_score"] = {
                "type": "score",
                "score": 8,
                "confidence": 0.9,
            }
            answers[f"{metric.key}_weakness"] = {
                "type": "choice",
                "choice": "no_material_issue",
            }
        return httpx.Response(
            200,
            json={
                "model": "jev-test",
                "answers": answers,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    evaluator = JevEvaluator(api_key="secret", client=client)
    card = evaluator.evaluate(ReviewState(task="task", diff="diff", repositoryContext="{}"))

    assert captured["model"] == "jev-latest"
    questions = captured["questions"]
    assert isinstance(questions, dict)
    assert len(questions) == 57
    assert captured["state"] == {"task": "task", "diff": "diff", "repositoryContext": "{}"}
    assert card.model == "jev-test"
    assert not card.priorities
    assert JEV_ENDPOINT == "https://api.typesafe.ai/v1/systemone"
