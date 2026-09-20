from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from jev_dspy_bench.adjudication import AdjudicationStore
from jev_dspy_bench.adjudication_web import create_app
from jev_dspy_bench.schema import METRIC_KEYS


def _corpus(root: Path) -> Path:
    corpus = root / "corpus"
    case = corpus / "cases" / "case-1"
    case.mkdir(parents=True)
    (case / "case.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "case-1",
                "description": "A defect",
                "jev": {"expectedWeakDimensions": ["correctness"]},
                "expected": [
                    {
                        "id": "F-1",
                        "description": "The condition is inverted.",
                        "severity": "HIGH",
                        "category": "QUALITY",
                        "file": "a.py",
                        "line": 1,
                    }
                ],
            }
        )
    )
    (case / "change.patch").write_text(
        "diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x\n+y\n"
    )
    files = {}
    for path in sorted(corpus.rglob("*")):
        if path.is_file():
            relative = str(path.relative_to(corpus))
            import hashlib

            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    import hashlib

    (corpus / "corpus.lock.json").write_text(
        json.dumps(
            {
                "files": files,
                "contentSha256": hashlib.sha256(canonical.encode()).hexdigest(),
            }
        )
    )
    return corpus


def _artifact(path: Path, corpus: Path) -> Path:
    scorecard = {
        "model": "test",
        "metrics": {metric: {"applicable": False} for metric in METRIC_KEYS},
        "priorities": [],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    artifact = {
        "name": "pilot",
        "corpus": {
            "contentSha256": json.loads((corpus / "corpus.lock.json").read_text())["contentSha256"]
        },
        "runs": [
            {"caseId": "case-1", "evaluator": name, "status": "success", "scorecard": scorecard}
            for name in ("jev", "dspy:test")
        ],
    }
    path.write_text(json.dumps(artifact))
    return path


def _reference() -> dict[str, object]:
    dimensions = {metric: "acceptable" for metric in METRIC_KEYS}
    dimensions["correctness"] = "weak"
    return {
        "disposition": "material_issue",
        "reviewability": "sufficient",
        "confidence": 4,
        "rationale": "The condition is inverted.",
        "dimensions": dimensions,
        "priorities": ["correctness"],
    }


def test_blind_workflow_and_identity_reveal(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    database = tmp_path / "annotations.sqlite"
    study = AdjudicationStore(database).import_artifact(
        _artifact(tmp_path / "run.json", corpus), corpus
    )
    client = TestClient(create_app(database))

    initial = client.get(f"/api/studies/{study}/cases/case-1?annotator=alice").json()
    assert "outputs" not in initial

    response = client.put(
        f"/api/studies/{study}/cases/case-1/reference",
        json={
            "annotator": "alice",
            "actor_type": "human",
            "submit": True,
            "reference": _reference(),
        },
    )
    assert response.json() == {"status": "reference_submitted"}
    revealed = client.get(f"/api/studies/{study}/cases/case-1?annotator=alice").json()
    assert {output["slot"] for output in revealed["outputs"]} == {"A", "B"}
    assert all(output["evaluator"] is None for output in revealed["outputs"])
    assert all("evaluator" not in output["result"] for output in revealed["outputs"])
    assert {output["result"]["scorecard"]["model"] for output in revealed["outputs"]} == {
        "Evaluator A",
        "Evaluator B",
    }

    comparison = {
        "preferred": "A",
        "confidence": 3,
        "rationale": "A better matches the reference.",
        "metric_preferences": {metric: "tie" for metric in METRIC_KEYS},
    }
    response = client.put(
        f"/api/studies/{study}/cases/case-1/comparison",
        json={"annotator": "alice", "submit": True, "comparison": comparison},
    )
    assert response.json() == {"status": "completed"}
    completed = client.get(f"/api/studies/{study}/cases/case-1?annotator=alice").json()
    assert {output["evaluator"] for output in completed["outputs"]} == {"jev", "dspy:test"}


def test_agent_seed_is_a_blinded_draft(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    store = AdjudicationStore(tmp_path / "annotations.sqlite")
    study = store.import_artifact(_artifact(tmp_path / "run.json", corpus), corpus)

    assert store.seed_agent_references(study, "agent-1") == 1
    case = store.get_case(study, "case-1", "agent-1")
    assert case is not None
    assert case["status"] == "draft"
    assert case["annotation"]["actor_type"] == "agent"
    assert "outputs" not in case


def test_agent_seed_accepts_missing_jev_expectation(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    case_path = corpus / "cases" / "case-1" / "case.yaml"
    metadata = yaml.safe_load(case_path.read_text())
    metadata["jev"] = None
    case_path.write_text(yaml.safe_dump(metadata))
    import hashlib

    lock = json.loads((corpus / "corpus.lock.json").read_text())
    lock["files"]["cases/case-1/case.yaml"] = hashlib.sha256(case_path.read_bytes()).hexdigest()
    canonical = json.dumps(lock["files"], sort_keys=True, separators=(",", ":"))
    lock["contentSha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    (corpus / "corpus.lock.json").write_text(json.dumps(lock))

    store = AdjudicationStore(tmp_path / "annotations.sqlite")
    study = store.import_artifact(_artifact(tmp_path / "run.json", corpus), corpus)
    assert store.seed_agent_references(study, "agent-1") == 1
