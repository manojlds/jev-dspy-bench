from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Any, Literal

from .pricing import with_estimated_cost
from .rubric import METRICS
from .schema import (
    ApplicableMetric,
    MetricIssue,
    NotApplicableMetric,
    Priority,
    RawMetricDecision,
    Scorecard,
    Usage,
)


def _js_round(value: float, digits: int) -> float:
    factor = Decimal(10) ** digits
    scaled = Decimal(str(value)) * factor
    return float((scaled + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR) / factor)


def severity(score: float) -> Literal["low", "medium", "high"]:
    if score <= 3:
        return "high"
    if score <= 5:
        return "medium"
    return "low"


def score_band(score: float) -> str:
    if score <= 3:
        return "seriously weak"
    if score <= 5:
        return "meaningfully weak"
    if score <= 7:
        return "acceptable but improvable"
    if score < 10:
        return "strong"
    return "exceptional"


def normalize_decisions(
    model: str,
    decisions: dict[str, RawMetricDecision],
    usage: Usage | None = None,
) -> Scorecard:
    if set(decisions) != {metric.key for metric in METRICS}:
        raise ValueError("decisions must contain exactly the configured metrics")
    metrics: dict[str, ApplicableMetric | NotApplicableMetric] = {}
    for definition in METRICS:
        decision = decisions[definition.key]
        if decision.weakness not in definition.weaknesses:
            raise ValueError(f"unknown weakness for {definition.key}: {decision.weakness}")
        if not decision.applicable:
            metrics[definition.key] = NotApplicableMetric(applicable=False)
            continue
        summary = (
            f"{definition.label} is {score_band(decision.score)} "
            "based on the supplied change context."
        )
        issues = None
        if decision.score < 8 and decision.weakness != "no_material_issue":
            issues = [
                MetricIssue(
                    severity=severity(decision.score),
                    description=definition.weaknesses[decision.weakness],
                    suggestion=definition.suggestion,
                )
            ]
        metrics[definition.key] = ApplicableMetric(
            applicable=True,
            score=decision.score,
            confidence=1,
            summary=summary,
            issues=issues,
        )
    resolved_usage = usage or Usage(input_tokens=0, output_tokens=0, total_tokens=0)
    return _scorecard(model, metrics, with_estimated_cost(model, resolved_usage))


def normalize_jev_response(response: dict[str, Any]) -> Scorecard:
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("Jev response is missing answers")
    metrics: dict[str, ApplicableMetric | NotApplicableMetric] = {}
    for definition in METRICS:
        applicable = answers.get(f"{definition.key}_applicable")
        score_answer = answers.get(f"{definition.key}_score")
        weakness = answers.get(f"{definition.key}_weakness")
        if not isinstance(applicable, dict) or applicable.get("type") != "noul":
            raise ValueError(f"Jev omitted applicability for {definition.key}")
        if not isinstance(score_answer, dict) or score_answer.get("type") != "score":
            raise ValueError(f"Jev omitted score for {definition.key}")
        if not isinstance(weakness, dict) or weakness.get("type") != "choice":
            raise ValueError(f"Jev omitted weakness for {definition.key}")
        choice = weakness.get("choice")
        if choice not in definition.weaknesses:
            raise ValueError(f"Jev selected an unknown weakness for {definition.key}")
        probability = float(applicable.get("noul", -1))
        if not 0 <= probability <= 1:
            raise ValueError(f"invalid Jev applicability for {definition.key}")
        if probability < 0.5:
            metrics[definition.key] = NotApplicableMetric(applicable=False)
            continue
        raw_score = float(score_answer.get("score", -1))
        confidence = float(score_answer.get("confidence", -1))
        if not 0 <= raw_score <= 9 or not 0 <= confidence <= 1:
            raise ValueError(f"invalid Jev score for {definition.key}")
        score = _js_round(raw_score + 1, 1)
        certainty = 0.5 + abs(probability - 0.5)
        summary = f"{definition.label} is {score_band(score)} based on the supplied change context."
        issues = None
        if score < 8 and choice != "no_material_issue":
            issues = [
                MetricIssue(
                    severity=severity(score),
                    description=definition.weaknesses[choice],
                    suggestion=definition.suggestion,
                )
            ]
        metrics[definition.key] = ApplicableMetric(
            applicable=True,
            score=score,
            confidence=_js_round(min(confidence, certainty), 2),
            summary=summary,
            issues=issues,
        )
    raw_usage = response.get("usage", {})
    input_tokens = int(raw_usage.get("input_tokens", 0))
    output_tokens = int(raw_usage.get("output_tokens", 0))
    model = str(response.get("model", ""))
    usage = Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )
    return _scorecard(model, metrics, with_estimated_cost(model, usage))


def normalize_jev_categorical_response(response: dict[str, Any]) -> Scorecard:
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("Jev response is missing answers")
    decisions: dict[str, RawMetricDecision] = {}
    confidences: dict[str, float] = {}
    for definition in METRICS:
        verdict = answers.get(f"{definition.key}_verdict")
        weakness = answers.get(f"{definition.key}_weakness")
        if not isinstance(verdict, dict) or verdict.get("type") != "choice":
            raise ValueError(f"Jev omitted categorical verdict for {definition.key}")
        if not isinstance(weakness, dict) or weakness.get("type") != "choice":
            raise ValueError(f"Jev omitted weakness for {definition.key}")
        choice = verdict.get("choice")
        if choice not in {"weak", "acceptable", "not_applicable"}:
            raise ValueError(f"Jev selected an unknown verdict for {definition.key}")
        weakness_choice = weakness.get("choice")
        if weakness_choice not in definition.weaknesses:
            raise ValueError(f"Jev selected an unknown weakness for {definition.key}")
        confidence = float(verdict.get("confidence", -1))
        if not 0 <= confidence <= 1:
            raise ValueError(f"invalid Jev verdict confidence for {definition.key}")
        decisions[definition.key] = RawMetricDecision(
            applicable=choice != "not_applicable",
            score=5 if choice == "weak" else 9,
            weakness=weakness_choice,
        )
        confidences[definition.key] = confidence

    raw_usage = response.get("usage", {})
    input_tokens = int(raw_usage.get("input_tokens", 0))
    output_tokens = int(raw_usage.get("output_tokens", 0))
    model = str(response.get("model", ""))
    scorecard = normalize_decisions(
        model,
        decisions,
        Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )
    for metric, confidence in confidences.items():
        evaluation = scorecard.metrics[metric]
        if evaluation.applicable:
            evaluation.confidence = _js_round(confidence, 2)
    return scorecard


def _scorecard(
    model: str,
    metrics: dict[str, ApplicableMetric | NotApplicableMetric],
    usage: Usage,
) -> Scorecard:
    candidates: list[tuple[float, str, ApplicableMetric, Any]] = []
    for definition in METRICS:
        evaluation = metrics[definition.key]
        if evaluation.applicable and evaluation.score < 8:
            candidates.append(
                (
                    evaluation.score - definition.priority_weight * 0.35,
                    definition.key,
                    evaluation,
                    definition,
                )
            )
    candidates.sort(key=lambda item: (item[0], item[1]))
    priorities = [
        Priority(
            metric=definition.key,
            severity=severity(evaluation.score),
            reason=(
                evaluation.issues[0].description
                if evaluation.issues
                else evaluation.summary or f"{definition.label} remains weak."
            ),
        )
        for _, _, evaluation, definition in candidates[:5]
    ]
    return Scorecard(model=model, metrics=metrics, priorities=priorities, usage=usage)
