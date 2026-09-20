from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .corpus import Corpus
from .schema import METRIC_KEYS, MetricKey

DimensionVerdict = Literal["weak", "acceptable", "not_applicable", "uncertain"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReferenceAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disposition: Literal["clean", "material_issue", "indeterminate"]
    reviewability: Literal["sufficient", "insufficient"]
    confidence: int = Field(ge=1, le=5)
    rationale: str
    dimensions: dict[MetricKey, DimensionVerdict]
    priorities: list[MetricKey] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_reference(self) -> ReferenceAnnotation:
        if set(self.dimensions) != set(METRIC_KEYS):
            raise ValueError("reference must classify every rubric dimension")
        if len(set(self.priorities)) != len(self.priorities):
            raise ValueError("priorities must be unique")
        if any(self.dimensions[item] != "weak" for item in self.priorities):
            raise ValueError("priorities must identify weak dimensions")
        return self


class ComparisonAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred: Literal["A", "B", "tie", "neither", "indeterminate"]
    confidence: int = Field(ge=1, le=5)
    rationale: str
    metric_preferences: dict[MetricKey, Literal["A", "B", "tie", "uncertain"]]

    @model_validator(mode="after")
    def all_metrics_present(self) -> ComparisonAnnotation:
        if set(self.metric_preferences) != set(METRIC_KEYS):
            raise ValueError("comparison must classify every rubric dimension")
        return self


class AdjudicationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS studies (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, artifact_sha256 TEXT NOT NULL UNIQUE,
                    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cases (
                    study_id TEXT NOT NULL REFERENCES studies(id), case_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, metadata_json TEXT NOT NULL, state_json TEXT NOT NULL,
                    evidence_json TEXT, PRIMARY KEY (study_id, case_id)
                );
                CREATE TABLE IF NOT EXISTS outputs (
                    study_id TEXT NOT NULL, case_id TEXT NOT NULL, slot TEXT NOT NULL,
                    evaluator TEXT NOT NULL, result_json TEXT NOT NULL,
                    PRIMARY KEY (study_id, case_id, slot),
                    FOREIGN KEY (study_id, case_id) REFERENCES cases(study_id, case_id)
                );
                CREATE TABLE IF NOT EXISTS annotations (
                    study_id TEXT NOT NULL, case_id TEXT NOT NULL, annotator TEXT NOT NULL,
                    actor_type TEXT NOT NULL CHECK(actor_type IN ('human', 'agent')),
                    status TEXT NOT NULL CHECK(status IN ('draft', 'reference_submitted', 'completed')),
                    reference_json TEXT, comparison_json TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, PRIMARY KEY (study_id, case_id, annotator),
                    FOREIGN KEY (study_id, case_id) REFERENCES cases(study_id, case_id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, study_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    annotator TEXT NOT NULL, event TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _slot(case_id: str, evaluator: str) -> str:
        digest = hashlib.sha256(f"{case_id}\0{evaluator}".encode()).digest()
        return "A" if digest[0] % 2 == 0 else "B"

    def import_artifact(self, artifact_path: Path, corpus_root: Path) -> str:
        raw = artifact_path.read_bytes()
        artifact = json.loads(raw)
        digest = hashlib.sha256(raw).hexdigest()
        study_id = digest[:12]
        corpus = Corpus(corpus_root)
        corpus.validate_lock()
        if artifact.get("corpus", {}).get("contentSha256") != corpus.lock().get("contentSha256"):
            raise ValueError("artifact and local corpus hashes differ")
        runs_by_case: dict[str, list[dict[str, Any]]] = {}
        for run in artifact.get("runs", []):
            if run.get("status") == "success" and run.get("scorecard"):
                runs_by_case.setdefault(run["caseId"], []).append(run)
        if not runs_by_case:
            raise ValueError("artifact has no successful scorecards")

        metadata = {key: value for key, value in artifact.items() if key != "runs"}
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO studies VALUES (?, ?, ?, ?, ?)",
                (study_id, artifact["name"], digest, json.dumps(metadata), _now()),
            )
            for ordinal, (case_id, runs) in enumerate(runs_by_case.items()):
                case = corpus.load_case(case_id)
                case_root = corpus_root / "cases" / case_id
                evidence_path = case_root / "evidence.yaml"
                evidence = (
                    yaml.safe_load(evidence_path.read_text()) if evidence_path.exists() else None
                )
                db.execute(
                    "INSERT OR IGNORE INTO cases VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        study_id,
                        case_id,
                        ordinal,
                        case.metadata.model_dump_json(),
                        case.state_json,
                        json.dumps(evidence),
                    ),
                )
                used_slots: set[str] = set()
                for run in runs:
                    slot = self._slot(case_id, run["evaluator"])
                    if slot in used_slots:
                        slot = "B" if slot == "A" else "A"
                    if slot in used_slots:
                        raise ValueError(f"case {case_id} has more than two successful outputs")
                    used_slots.add(slot)
                    db.execute(
                        "INSERT OR IGNORE INTO outputs VALUES (?, ?, ?, ?, ?)",
                        (study_id, case_id, slot, run["evaluator"], json.dumps(run)),
                    )
        return study_id

    def list_studies(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id, name, created_at FROM studies")]

    def list_cases(self, study_id: str, annotator: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT c.case_id, c.ordinal, c.metadata_json, COALESCE(a.status, 'unstarted') status,
                       COALESCE(a.actor_type, '') actor_type
                FROM cases c LEFT JOIN annotations a
                  ON a.study_id=c.study_id AND a.case_id=c.case_id AND a.annotator=?
                WHERE c.study_id=? ORDER BY c.ordinal
                """,
                (annotator, study_id),
            ).fetchall()
        return [
            {
                "case_id": row["case_id"],
                "ordinal": row["ordinal"],
                "description": json.loads(row["metadata_json"])["description"],
                "status": row["status"],
                "actor_type": row["actor_type"],
            }
            for row in rows
        ]

    def get_case(self, study_id: str, case_id: str, annotator: str) -> dict[str, Any] | None:
        with self.connect() as db:
            case = db.execute(
                "SELECT * FROM cases WHERE study_id=? AND case_id=?", (study_id, case_id)
            ).fetchone()
            if not case:
                return None
            annotation = db.execute(
                "SELECT * FROM annotations WHERE study_id=? AND case_id=? AND annotator=?",
                (study_id, case_id, annotator),
            ).fetchone()
            status = annotation["status"] if annotation else "unstarted"
            result: dict[str, Any] = {
                "case_id": case_id,
                "metadata": json.loads(case["metadata_json"]),
                "state": json.loads(case["state_json"]),
                "evidence": json.loads(case["evidence_json"]) if case["evidence_json"] else None,
                "metrics": METRIC_KEYS,
                "status": status,
                "annotation": None,
            }
            if annotation:
                result["annotation"] = {
                    "actor_type": annotation["actor_type"],
                    "reference": json.loads(annotation["reference_json"])
                    if annotation["reference_json"]
                    else None,
                    "comparison": json.loads(annotation["comparison_json"])
                    if annotation["comparison_json"]
                    else None,
                }
            if status in {"reference_submitted", "completed"}:
                rows = db.execute(
                    "SELECT slot, evaluator, result_json FROM outputs WHERE study_id=? AND case_id=? ORDER BY slot",
                    (study_id, case_id),
                ).fetchall()
                outputs = []
                for row in rows:
                    output = json.loads(row["result_json"])
                    output.pop("evaluator", None)
                    if status != "completed":
                        output["scorecard"]["model"] = f"Evaluator {row['slot']}"
                    outputs.append(
                        {
                            "slot": row["slot"],
                            "evaluator": row["evaluator"] if status == "completed" else None,
                            "result": output,
                        }
                    )
                result["outputs"] = outputs
            return result

    def comparative_report(self, study_id: str, annotator: str) -> dict[str, Any]:
        with self.connect() as db:
            study = db.execute("SELECT id, name FROM studies WHERE id=?", (study_id,)).fetchone()
            if not study:
                raise ValueError("study not found")
            rows = db.execute(
                """
                SELECT c.case_id, c.ordinal, a.status, a.reference_json, a.comparison_json
                FROM cases c LEFT JOIN annotations a
                  ON a.study_id=c.study_id AND a.case_id=c.case_id AND a.annotator=?
                WHERE c.study_id=? ORDER BY c.ordinal
                """,
                (annotator, study_id),
            ).fetchall()
            output_rows = db.execute(
                "SELECT case_id, slot, evaluator, result_json FROM outputs WHERE study_id=?",
                (study_id,),
            ).fetchall()

        completed_case_ids = {row["case_id"] for row in rows if row["status"] == "completed"}
        outputs_by_case: dict[str, list[dict[str, Any]]] = {}
        efficiency: dict[str, dict[str, list[float]]] = {}
        for row in output_rows:
            if row["case_id"] not in completed_case_ids:
                continue
            result = json.loads(row["result_json"])
            usage = result["scorecard"]["usage"]
            outputs_by_case.setdefault(row["case_id"], []).append(
                {
                    "slot": row["slot"],
                    "evaluator": row["evaluator"],
                    "priorities": result["scorecard"]["priorities"],
                    "latency_ms": result.get("latencyMs"),
                    "usage": usage,
                }
            )
            stats = efficiency.setdefault(
                row["evaluator"], {"latencies": [], "tokens": [], "costs": []}
            )
            if result.get("latencyMs") is not None:
                stats["latencies"].append(float(result["latencyMs"]))
            stats["tokens"].append(float(usage["total_tokens"]))
            if usage.get("cost") is not None:
                stats["costs"].append(float(usage["cost"]))

        wins: dict[str, int] = {}
        dimension_preferences: dict[str, dict[str, int]] = {metric: {} for metric in METRIC_KEYS}
        cases: list[dict[str, Any]] = []
        completed = 0
        for row in rows:
            reference = json.loads(row["reference_json"]) if row["reference_json"] else None
            comparison = json.loads(row["comparison_json"]) if row["comparison_json"] else None
            outputs = sorted(outputs_by_case.get(row["case_id"], []), key=lambda item: item["slot"])
            slot_map = {item["slot"]: item["evaluator"] for item in outputs}
            winner = None
            completed_comparison = comparison if row["status"] == "completed" else None
            if completed_comparison:
                completed += 1
                preferred = completed_comparison["preferred"]
                winner = slot_map.get(preferred, preferred)
                wins[winner] = wins.get(winner, 0) + 1
                for metric, choice in completed_comparison["metric_preferences"].items():
                    preference = slot_map.get(choice, choice)
                    counts = dimension_preferences[metric]
                    counts[preference] = counts.get(preference, 0) + 1
            cases.append(
                {
                    "case_id": row["case_id"],
                    "status": row["status"] or "unstarted",
                    "disposition": reference["disposition"] if reference else None,
                    "winner": winner,
                    "confidence": completed_comparison["confidence"]
                    if completed_comparison
                    else None,
                    "rationale": completed_comparison["rationale"]
                    if completed_comparison
                    else None,
                    "outputs": outputs if completed_comparison else [],
                }
            )

        evaluator_efficiency = {
            evaluator: {
                "runs": len(values["tokens"]),
                "median_latency_ms": median(values["latencies"]) if values["latencies"] else None,
                "total_tokens": int(sum(values["tokens"])),
                "total_cost": sum(values["costs"]) if values["costs"] else None,
            }
            for evaluator, values in efficiency.items()
        }
        return {
            "study_id": study["id"],
            "name": study["name"],
            "annotator": annotator,
            "total_cases": len(rows),
            "completed_cases": completed,
            "wins": wins,
            "evaluator_efficiency": evaluator_efficiency,
            "dimension_preferences": dimension_preferences,
            "cases": cases,
        }

    def save_reference(
        self,
        study_id: str,
        case_id: str,
        annotator: str,
        actor_type: str,
        reference: ReferenceAnnotation,
        submit: bool,
    ) -> str:
        payload = reference.model_dump_json()
        status = "reference_submitted" if submit else "draft"
        now = _now()
        with self.connect() as db:
            existing = db.execute(
                "SELECT status FROM annotations WHERE study_id=? AND case_id=? AND annotator=?",
                (study_id, case_id, annotator),
            ).fetchone()
            if existing and existing["status"] != "draft":
                raise ValueError("submitted references are immutable")
            db.execute(
                """
                INSERT INTO annotations VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(study_id, case_id, annotator) DO UPDATE SET
                  actor_type=excluded.actor_type, status=excluded.status,
                  reference_json=excluded.reference_json, updated_at=excluded.updated_at
                """,
                (study_id, case_id, annotator, actor_type, status, payload, now, now),
            )
            self._audit(db, study_id, case_id, annotator, f"reference_{status}", payload)
        return status

    def save_comparison(
        self,
        study_id: str,
        case_id: str,
        annotator: str,
        comparison: ComparisonAnnotation,
        submit: bool,
    ) -> str:
        payload = comparison.model_dump_json()
        status = "completed" if submit else "reference_submitted"
        with self.connect() as db:
            existing = db.execute(
                "SELECT status FROM annotations WHERE study_id=? AND case_id=? AND annotator=?",
                (study_id, case_id, annotator),
            ).fetchone()
            if not existing or existing["status"] == "draft":
                raise ValueError("submit the blinded reference before comparing outputs")
            if existing["status"] == "completed":
                raise ValueError("completed comparisons are immutable")
            db.execute(
                "UPDATE annotations SET status=?, comparison_json=?, updated_at=? WHERE study_id=? AND case_id=? AND annotator=?",
                (status, payload, _now(), study_id, case_id, annotator),
            )
            self._audit(db, study_id, case_id, annotator, f"comparison_{status}", payload)
        return status

    @staticmethod
    def _audit(
        db: sqlite3.Connection,
        study_id: str,
        case_id: str,
        annotator: str,
        event: str,
        payload: str,
    ) -> None:
        db.execute(
            "INSERT INTO audit_events(study_id, case_id, annotator, event, payload_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                study_id,
                case_id,
                annotator,
                event,
                hashlib.sha256(payload.encode()).hexdigest(),
                _now(),
            ),
        )

    def seed_agent_references(self, study_id: str, annotator: str) -> int:
        count = 0
        with self.connect() as db:
            rows = db.execute(
                "SELECT case_id, metadata_json, evidence_json FROM cases WHERE study_id=? ORDER BY ordinal",
                (study_id,),
            ).fetchall()
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            weak = (metadata.get("jev") or {}).get("expectedWeakDimensions", [])
            dimensions: dict[MetricKey, DimensionVerdict] = {
                metric: "uncertain" for metric in METRIC_KEYS
            }
            dimensions.update({metric: "weak" for metric in weak})
            findings = metadata.get("expected", [])
            evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else None
            if findings:
                summary = "; ".join(item["description"] for item in findings)
                if evidence and evidence.get("rationale"):
                    summary += f" Evidence: {evidence['rationale']}"
            else:
                summary = "The frozen corpus metadata identifies this case as a clean control."
            reference = ReferenceAnnotation(
                disposition="material_issue" if findings else "clean",
                reviewability="sufficient",
                confidence=4 if evidence else 3,
                rationale=summary,
                dimensions=dimensions,
                priorities=weak[:5],
            )
            try:
                self.save_reference(study_id, row["case_id"], annotator, "agent", reference, False)
            except ValueError:
                continue
            count += 1
        return count
