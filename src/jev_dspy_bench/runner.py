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
from .metrics import agreement, summarize
from .program import DspyEvaluator
from .providers.direct import DirectEvaluator
from .providers.jev import JevEvaluator
from .rubric import build_questions


def run_experiment(root: Path, config: ExperimentConfig) -> Path:
    if not config.live:
        raise ValueError("live provider execution requires live: true")
    corpus = Corpus(root / "corpus")
    split = yaml.safe_load((root / "corpus" / "splits" / f"{config.split}.yaml").read_text())
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
                            {
                                "caseId": case_id,
                                "repeat": repeat,
                                "evaluator": evaluator.id,
                                "status": "success",
                                "stateSha256": case.state_sha256,
                                "latencyMs": round((time.perf_counter() - started) * 1_000, 3),
                                "scorecard": scorecard.model_dump(),
                            }
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
    report = {
        "schemaVersion": 1,
        "name": config.name,
        "createdAt": datetime.now(UTC).isoformat(),
        "split": config.split,
        "partition": config.partition,
        "repeat": config.repeat,
        "corpus": corpus.lock(),
        "rubricSha256": _hash_json(build_questions()),
        "preparedStateGuarantee": "Every evaluator for a case receives the same canonical serialized state content; provider request framing and optimized instructions differ.",
        "uncertaintyNote": "LLM confidence is synthetic and is not compared with Jev probabilities.",
        "analysis": summarize(runs, metadata),
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
    rows = []
    for name, values in report["analysis"].items():
        rows.append(
            f"| {name} | {_percent(values['successRate'])} | "
            f"{_percent(values['expectedPriorityHitRate'])} | "
            f"{_percent(values['cleanPriorityFreeRate'])} | {values['medianLatencyMs'] or 'n/a'} |"
        )
    return (
        f"# {report['name']}\n\n"
        "Only prepared state content is shared exactly; request framing differs by evaluator. "
        "Agreement with Jev is similarity, not correctness.\n\n"
        "| Evaluator | Success | Expected priority hit | Clean priority-free | Median latency ms |\n"
        "|---|---:|---:|---:|---:|\n" + "\n".join(rows) + "\n"
    )


def _build_evaluator(root: Path, config: EvaluatorConfig) -> Any:
    if config.kind == "jev":
        return JevEvaluator()
    if config.kind == "direct":
        return DirectEvaluator(config.model or "", batch_size=config.batchSize)
    program = str(root / config.program) if config.program else None
    return DspyEvaluator(config.model or "", program_path=program, batch_size=config.batchSize)


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"
