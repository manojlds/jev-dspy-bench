from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from .schema import METRIC_KEYS, CaseMetadata, Scorecard


def expected_signal_score(metadata: CaseMetadata, scorecard: Scorecard) -> float:
    expected = set(metadata.jev.expectedWeakDimensions if metadata.jev else [])
    actual = {priority.metric for priority in scorecard.priorities}
    if not expected:
        return max(0.0, 1 - len(actual) / 5)
    recall = len(expected & actual) / len(expected)
    precision = len(expected & actual) / len(actual) if actual else 0.0
    return 0.8 * recall + 0.2 * precision


def reference_score(reference: dict[str, Any], scorecard: Scorecard) -> float:
    dimensions = reference["dimensions"]
    scored: list[float] = []
    for metric in METRIC_KEYS:
        expected = dimensions[metric]
        actual = scorecard.metrics[metric]
        if expected == "uncertain":
            continue
        if expected == "not_applicable":
            scored.append(1.0 if not actual.applicable else 0.0)
        elif expected == "weak":
            scored.append(1.0 if actual.applicable and actual.score < 8 else 0.0)
        else:
            scored.append(1.0 if actual.applicable and actual.score >= 8 else 0.0)

    expected_priorities = set(reference["priorities"])
    actual_priorities = {priority.metric for priority in scorecard.priorities}
    if not expected_priorities:
        priority_score = max(0.0, 1 - len(actual_priorities) / 5)
    else:
        true_positives = len(expected_priorities & actual_priorities)
        recall = true_positives / len(expected_priorities)
        precision = true_positives / len(actual_priorities) if actual_priorities else 0.0
        priority_score = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    dimension_score = sum(scored) / len(scored) if scored else 0.0
    return 0.7 * dimension_score + 0.3 * priority_score


def summarize_references(
    runs: list[dict[str, Any]], references: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run["status"] == "success" and run["caseId"] in references:
            grouped[run["evaluator"]].append(run)
    output: dict[str, Any] = {}
    for evaluator, selected in grouped.items():
        scores: list[float] = []
        dimension_matches: list[bool] = []
        weak_matches: list[bool] = []
        acceptable_matches: list[bool] = []
        applicability_matches: list[bool] = []
        priority_f1: list[float] = []
        clean_priority_free: list[bool] = []
        for run in selected:
            reference = references[run["caseId"]]
            card = Scorecard.model_validate(run["scorecard"])
            scores.append(reference_score(reference, card))
            for metric in METRIC_KEYS:
                expected = reference["dimensions"][metric]
                actual = card.metrics[metric]
                if expected == "uncertain":
                    continue
                if expected == "not_applicable":
                    match = not actual.applicable
                    applicability_matches.append(match)
                elif expected == "weak":
                    match = actual.applicable and actual.score < 8
                    weak_matches.append(match)
                else:
                    match = actual.applicable and actual.score >= 8
                    acceptable_matches.append(match)
                dimension_matches.append(match)
            expected_priorities = set(reference["priorities"])
            actual_priorities = {item.metric for item in card.priorities}
            if not expected_priorities:
                clean_priority_free.append(not actual_priorities)
                priority_f1.append(1.0 if not actual_priorities else 0.0)
            else:
                true_positives = len(expected_priorities & actual_priorities)
                recall = true_positives / len(expected_priorities)
                precision = true_positives / len(actual_priorities) if actual_priorities else 0.0
                priority_f1.append(
                    2 * precision * recall / (precision + recall) if precision + recall else 0.0
                )
        output[evaluator] = {
            "cases": len(selected),
            "meanReferenceScore": statistics.mean(scores),
            "dimensionAgreement": _rate(sum(dimension_matches), len(dimension_matches)),
            "weakDimensionDetection": _rate(sum(weak_matches), len(weak_matches)),
            "acceptableDimensionAgreement": _rate(sum(acceptable_matches), len(acceptable_matches)),
            "notApplicableAgreement": _rate(sum(applicability_matches), len(applicability_matches)),
            "meanPriorityF1": statistics.mean(priority_f1),
            "cleanPriorityFreeRate": _rate(sum(clean_priority_free), len(clean_priority_free)),
        }
    return output


def summarize(runs: list[dict[str, Any]], cases: dict[str, CaseMetadata]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[run["evaluator"]].append(run)
    result: dict[str, Any] = {}
    for evaluator, selected in grouped.items():
        successful = [run for run in selected if run["status"] == "success"]
        cards = [(run, Scorecard.model_validate(run["scorecard"])) for run in successful]
        expected_hits: list[bool] = []
        clean_free: list[bool] = []
        for run, card in cards:
            metadata = cases[run["caseId"]]
            expected = set(metadata.jev.expectedWeakDimensions if metadata.jev else [])
            priorities = {item.metric for item in card.priorities}
            if expected:
                expected_hits.extend(metric in priorities for metric in expected)
            if not metadata.expected:
                clean_free.append(not priorities)
        result[evaluator] = {
            "runs": len(selected),
            "successRate": _rate(len(successful), len(selected)),
            "expectedPriorityHitRate": _rate(sum(expected_hits), len(expected_hits)),
            "cleanPriorityFreeRate": _rate(sum(clean_free), len(clean_free)),
            "medianLatencyMs": _median([run["latencyMs"] for run in successful]),
            "medianInputTokens": _median([card.usage.input_tokens for _, card in cards]),
            "medianOutputTokens": _median([card.usage.output_tokens for _, card in cards]),
            "totalTokens": sum(card.usage.total_tokens for _, card in cards),
            "medianCostUsd": _median(
                [card.usage.cost for _, card in cards if card.usage.cost is not None]
            ),
            "totalCostUsd": (
                sum(card.usage.cost for _, card in cards if card.usage.cost is not None)
                if cards and all(card.usage.cost is not None for _, card in cards)
                else None
            ),
            "stability": _stability(cards),
        }
    return result


def agreement(runs: list[dict[str, Any]]) -> dict[str, Any]:
    jev = {
        (run["caseId"], run["repeat"]): Scorecard.model_validate(run["scorecard"])
        for run in runs
        if run["evaluator"] == "jev" and run["status"] == "success"
    }
    by_evaluator: dict[str, list[tuple[Scorecard, Scorecard]]] = defaultdict(list)
    for run in runs:
        if run["evaluator"] == "jev" or run["status"] != "success":
            continue
        left = jev.get((run["caseId"], run["repeat"]))
        if left:
            by_evaluator[run["evaluator"]].append(
                (left, Scorecard.model_validate(run["scorecard"]))
            )
    output: dict[str, Any] = {}
    for evaluator, pairs in by_evaluator.items():
        applicability: list[bool] = []
        score_diffs: list[float] = []
        jaccards: list[float] = []
        for left, right in pairs:
            for key in METRIC_KEYS:
                left_metric, right_metric = left.metrics[key], right.metrics[key]
                applicability.append(left_metric.applicable == right_metric.applicable)
                if left_metric.applicable and right_metric.applicable:
                    score_diffs.append(abs(left_metric.score - right_metric.score))
            left_priorities = {item.metric for item in left.priorities}
            right_priorities = {item.metric for item in right.priorities}
            union = left_priorities | right_priorities
            jaccards.append(len(left_priorities & right_priorities) / len(union) if union else 1)
        output[evaluator] = {
            "pairedRuns": len(pairs),
            "applicabilityAgreement": _rate(sum(applicability), len(applicability)),
            "scoreMeanAbsoluteDifference": statistics.mean(score_diffs) if score_diffs else None,
            "meanPriorityJaccard": statistics.mean(jaccards) if jaccards else None,
        }
    return output


def _stability(cards: list[tuple[dict[str, Any], Scorecard]]) -> dict[str, float | None]:
    grouped: dict[str, list[Scorecard]] = defaultdict(list)
    for run, card in cards:
        grouped[run["caseId"]].append(card)
    priority_flips: list[bool] = []
    applicability_flips: list[bool] = []
    for values in grouped.values():
        if len(values) < 2:
            continue
        priority_flips.append(
            len({tuple(priority.metric for priority in card.priorities) for card in values}) > 1
        )
        for key in METRIC_KEYS:
            applicability_flips.append(len({card.metrics[key].applicable for card in values}) > 1)
    return {
        "prioritySetFlipRate": _rate(sum(priority_flips), len(priority_flips)),
        "applicabilityFlipRate": _rate(sum(applicability_flips), len(applicability_flips)),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None
