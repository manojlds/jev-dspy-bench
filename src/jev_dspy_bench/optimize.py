from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import dspy
import yaml

from .corpus import Corpus
from .lm import create_lm
from .metrics import expected_signal_score
from .program import QualityProgram
from .schema import CaseMetadata, Scorecard

OptimizationBudget = Literal["light", "medium", "heavy"]


def compile_program(
    root: Path,
    *,
    split_name: str,
    model: str,
    output: Path,
    corpus_path: Path = Path("corpus"),
    seed: int = 42,
    auto: OptimizationBudget = "light",
) -> Path:
    corpus_root = corpus_path if corpus_path.is_absolute() else root / corpus_path
    corpus = Corpus(corpus_root)
    split = yaml.safe_load((corpus_root / "splits" / f"{split_name}.yaml").read_text())
    trainset = [_example(corpus, case_id) for case_id in split["train"]]
    valset = [_example(corpus, case_id) for case_id in split["dev"]]
    if not trainset or not valset:
        raise ValueError("optimization requires non-empty train and dev partitions")

    lm = create_lm(model)
    dspy.configure(lm=lm, adapter=dspy.ChatAdapter(), track_usage=True)
    student = QualityProgram(model)
    optimizer = dspy.MIPROv2(
        metric=_optimization_metric,
        prompt_model=lm,
        task_model=lm,
        auto=auto,
        seed=seed,
        num_threads=1,
    )
    compiled = optimizer.compile(student, trainset=trainset, valset=valset)
    output = output if output.is_absolute() else root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    compiled.save(str(output))
    manifest = {
        "schemaVersion": 1,
        "createdAt": datetime.now(UTC).isoformat(),
        "model": model,
        "optimizer": "MIPROv2",
        "auto": auto,
        "seed": seed,
        "split": split_name,
        "corpus": str(corpus_path),
        "trainCases": split["train"],
        "devCases": split["dev"],
        "testCasesSeen": False,
        "corpusContentSha256": corpus.lock()["contentSha256"],
        "programSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "metric": "0.7 reference dimension agreement + 0.3 reference priority F1; falls back to sparse expected signals when no full reference exists",
        "warning": "Optimization quality remains limited by corpus size and source diversity.",
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return output


def _example(corpus: Corpus, case_id: str) -> dspy.Example:
    case = corpus.load_case(case_id)
    return dspy.Example(
        state_json=case.state_json,
        case_metadata_json=case.metadata.model_dump_json(),
    ).with_inputs("state_json")


def _optimization_metric(
    example: dspy.Example, prediction: dspy.Prediction, trace: object = None
) -> float:
    del trace
    try:
        metadata = CaseMetadata.model_validate_json(example.case_metadata_json)
        scorecard = Scorecard.model_validate_json(prediction.scorecard_json)
        return expected_signal_score(metadata, scorecard)
    except (ValueError, TypeError, AttributeError):
        return 0.0
