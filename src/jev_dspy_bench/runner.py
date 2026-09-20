from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .config import EvaluatorConfig, ExperimentConfig
from .corpus import Corpus
from .metrics import agreement, summarize, summarize_references
from .pricing import cost_basis, with_estimated_cost
from .program import DspyEvaluator
from .providers.direct import DirectEvaluator
from .providers.jev import JevEvaluator
from .providers.laya import LayaEvaluator
from .rubric import build_categorical_questions, build_questions
from .schema import Usage


def run_experiment(root: Path, config: ExperimentConfig) -> Path:
    if not config.live:
        raise ValueError("live provider execution requires live: true")
    corpus_root = root / config.corpus
    corpus = Corpus(corpus_root)
    split = yaml.safe_load((corpus_root / "splits" / f"{config.split}.yaml").read_text())
    case_ids: list[str] = split[config.partition]
    cases = {case_id: corpus.load_case(case_id) for case_id in case_ids}
    evaluators = [_build_evaluator(root, item) for item in config.evaluators]
    runs: list[dict[str, Any]] = []
    try:
        for case_id, case in cases.items():
            for repeat in range(1, config.repeat + 1):
                for evaluator in evaluators:
                    started = time.perf_counter()
                    try:
                        scorecard = evaluator.evaluate(case.state)
                        runs.append(
                            _with_diagnostics(
                                {
                                    "caseId": case_id,
                                    "repeat": repeat,
                                    "evaluator": evaluator.id,
                                    "status": "success",
                                    "stateSha256": case.state_sha256,
                                    "latencyMs": round((time.perf_counter() - started) * 1_000, 3),
                                    "scorecard": scorecard.model_dump(),
                                },
                                evaluator,
                            )
                        )
                    except Exception as error:  # benchmark failures are report data
                        runs.append(
                            {
                                "caseId": case_id,
                                "repeat": repeat,
                                "evaluator": evaluator.id,
                                "status": "failure",
                                "stateSha256": case.state_sha256,
                                "latencyMs": round((time.perf_counter() - started) * 1_000, 3),
                                "error": f"{type(error).__name__}: {error}",
                            }
                        )
    finally:
        for evaluator in evaluators:
            close = getattr(evaluator, "close", None)
            if close:
                close()
    metadata = {case_id: case.metadata for case_id, case in cases.items()}
    references = _load_references(corpus, case_ids)
    report = {
        "schemaVersion": 1,
        "name": config.name,
        "createdAt": datetime.now(UTC).isoformat(),
        "split": config.split,
        "partition": config.partition,
        "repeat": config.repeat,
        "corpus": corpus.lock(),
        "rubricSha256": _hash_json(_protocol_questions(config)),
        "preparedStateGuarantee": "Every evaluator for a case receives the same canonical serialized state content; provider request framing and optimized instructions differ.",
        "uncertaintyNote": "LLM confidence is synthetic and is not compared with Jev probabilities.",
        "costBasis": _cost_basis(runs),
        "analysis": summarize(runs, metadata),
        "referenceAnalysis": summarize_references(runs, references),
        "agreementWithJev": agreement(runs),
        "runs": runs,
    }
    output = root / config.output
    output.mkdir(parents=True, exist_ok=True)
    run_id = (
        f"{config.name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{_hash_json(report)[:8]}"
    )
    path = output / f"{run_id}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    (output / f"{run_id}.md").write_text(format_report(report))
    return path


def format_report(report: dict[str, Any]) -> str:
    quality_rows = []
    efficiency_rows = []
    for name, values in report["analysis"].items():
        quality_rows.append(
            f"| {name} | {_percent(values['successRate'])} | "
            f"{_percent(values['expectedPriorityHitRate'])} | "
            f"{_percent(values['cleanPriorityFreeRate'])} |"
        )
        efficiency_rows.append(
            f"| {name} | {_number(values['medianLatencyMs'], 1)} | "
            f"{_number(values['medianInputTokens'], 0)} | "
            f"{_number(values['medianOutputTokens'], 0)} | "
            f"{_number(values.get('totalTokens'), 0)} | "
            f"{_money(values.get('medianCostUsd'))} | {_money(values.get('totalCostUsd'))} |"
        )
    agreement_rows = [
        f"| {name} | {values['pairedRuns']} | {_percent(values['applicabilityAgreement'])} | "
        f"{_number(values['scoreMeanAbsoluteDifference'], 3)} | "
        f"{_number(values['meanPriorityJaccard'], 3)} |"
        for name, values in report.get("agreementWithJev", {}).items()
    ]
    basis = "\n".join(
        f"- `{name}`: {description}" for name, description in report.get("costBasis", {}).items()
    )
    comparison = _comparison_summary(report["analysis"])
    reference_rows = [
        f"| {name} | {values['cases']} | {_percent(values['meanReferenceScore'])} | "
        f"{_percent(values['dimensionAgreement'])} | "
        f"{_percent(values['weakDimensionDetection'])} | "
        f"{_percent(values['acceptableDimensionAgreement'])} | "
        f"{_percent(values['balancedDimensionAgreement'])} | "
        f"{_percent(values['meanPriorityF1'])} | "
        f"{_percent(values['cleanPriorityFreeRate'])} |"
        for name, values in report.get("referenceAnalysis", {}).items()
    ]
    return (
        f"# {report['name']}\n\n"
        "Only prepared state content is shared exactly; request framing differs by evaluator. "
        "Agreement with Jev is similarity, not correctness.\n\n"
        "## Comparison Summary\n\n" + comparison + "\n\n"
        "## Frozen Reference Agreement\n\n"
        "This is direct agreement with output-independent annotations. Uncertain dimensions are excluded.\n\n"
        "| Evaluator | Cases | Reference score | Dimension agreement | Weak detection | Acceptable agreement | Balanced dimension agreement | Priority F1 | Clean priority-free |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        + (
            "\n".join(reference_rows)
            if reference_rows
            else "| n/a | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
        )
        + "\n\n## Sparse Signals\n\n"
        "Expected-dimension hits are sparse evidence signals, not file-level recall. Clean priority-free "
        "rate is not false-positive precision without manual adjudication.\n\n"
        "| Evaluator | Success | Expected priority hit | Clean priority-free |\n"
        "|---|---:|---:|---:|\n" + "\n".join(quality_rows) + "\n\n## Efficiency\n\n"
        "| Evaluator | Median latency ms | Median input tokens | Median output tokens | Total tokens | Median cost | Total cost |\n"
        "|---|---:|---:|---:|---:|---:|---:|\n"
        + "\n".join(efficiency_rows)
        + "\n\n## Cost Basis\n\n"
        + basis
        + "\n\n## Agreement With Jev\n\n"
        "Similarity does not establish correctness.\n\n"
        "| Evaluator | Paired runs | Applicability agreement | Score MAE | Priority Jaccard |\n"
        "|---|---:|---:|---:|---:|\n"
        + ("\n".join(agreement_rows) if agreement_rows else "| n/a | 0 | n/a | n/a | n/a |")
        + "\n"
    )


def enrich_report_costs(report: dict[str, Any]) -> None:
    for run in report.get("runs", []):
        if run.get("status") != "success" or not isinstance(run.get("scorecard"), dict):
            continue
        scorecard = run["scorecard"]
        model = scorecard.get("model")
        usage = scorecard.get("usage")
        if not isinstance(model, str) or not isinstance(usage, dict):
            continue
        validated = with_estimated_cost(model, Usage.model_validate(usage))
        usage.update(validated.model_dump())
    report["costBasis"] = _cost_basis(report.get("runs", []))


def _build_evaluator(root: Path, config: EvaluatorConfig) -> Any:
    if config.kind == "jev":
        return JevEvaluator(model=config.model or "jev-latest")
    if config.kind == "jev-categorical":
        return JevEvaluator(
            model=config.model or "jev-1.13.0",
            categorical=True,
        )
    if config.kind == "laya":
        return LayaEvaluator(
            config.model or "convaiinnovations/laya",
            subfolder=config.subfolder,
            device=config.device,
            revision=config.revision,
        )
    if config.kind == "direct":
        return DirectEvaluator(config.model or "", batch_size=config.batchSize)
    program = str(root / config.program) if config.program else None
    return DspyEvaluator(config.model or "", program_path=program, batch_size=config.batchSize)


def _protocol_questions(config: ExperimentConfig) -> dict[str, dict[str, object]]:
    if any(item.kind in {"jev-categorical", "laya"} for item in config.evaluators):
        return build_categorical_questions()
    return build_questions()


def _with_diagnostics(run: dict[str, Any], evaluator: Any) -> dict[str, Any]:
    diagnostics = getattr(evaluator, "last_diagnostics", None)
    if diagnostics:
        run["diagnostics"] = diagnostics
    return run


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _load_references(corpus: Corpus, case_ids: list[str] | set[str]) -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    for case_id in case_ids:
        path = corpus.root / "cases" / case_id / "reference.json"
        if path.is_file():
            references[case_id] = json.loads(path.read_text())
    return references


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _number(value: float | None, digits: int) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.6f}"


def _cost_basis(runs: list[dict[str, Any]]) -> dict[str, str]:
    basis: dict[str, str] = {}
    for run in runs:
        scorecard = run.get("scorecard")
        if run.get("status") != "success" or not isinstance(scorecard, dict):
            continue
        model = scorecard.get("model")
        if isinstance(model, str):
            basis[run["evaluator"]] = cost_basis(model)
    return basis


def _comparison_summary(analysis: dict[str, dict[str, Any]]) -> str:
    jev = analysis.get("jev")
    if not jev:
        return "A Jev baseline is required for relative comparisons."
    lines: list[str] = []
    for name, values in analysis.items():
        if name == "jev":
            continue
        hit_delta = _difference_points(
            values.get("expectedPriorityHitRate"), jev.get("expectedPriorityHitRate")
        )
        latency_ratio = _ratio(values.get("medianLatencyMs"), jev.get("medianLatencyMs"))
        cost_ratio = _ratio(values.get("totalCostUsd"), jev.get("totalCostUsd"))
        lines.append(
            f"- `{name}` expected-priority hit rate was {hit_delta} percentage points relative to Jev; "
            f"Jev was {_ratio_text(latency_ratio)} faster and {_ratio_text(cost_ratio)} cheaper on the stated cost basis."
        )
    return "\n".join(lines) or "No non-Jev evaluator completed successfully."


def _difference_points(left: float | None, right: float | None) -> str:
    if left is None or right is None:
        return "n/a"
    return f"{(left - right) * 100:+.1f}"


def _ratio(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or right == 0:
        return None
    return left / right


def _ratio_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}x"
