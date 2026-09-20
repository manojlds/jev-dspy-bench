from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import METRIC_KEYS, Comparison, MetricKey


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    group: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    target: Literal["train", "dev"]
    outcome: Literal["defect", "clean"]
    description: str
    category: str
    severity: Literal["HIGH", "MEDIUM", "LOW"] | None = None
    pullRequest: int = Field(gt=0)
    source: str
    fromRevision: str = Field(min_length=7)
    toRevision: str = Field(min_length=7)
    confirmingRevision: str | None = None
    paths: list[str] = Field(min_length=1)
    evidence: str

    @model_validator(mode="after")
    def validate_outcome(self) -> Candidate:
        if self.outcome == "defect" and (not self.severity or not self.confirmingRevision):
            raise ValueError("defect candidates require severity and confirmingRevision")
        if self.outcome == "clean" and self.severity is not None:
            raise ValueError("clean candidates cannot have severity")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("candidate paths must be unique")
        return self


class CandidateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal[1]
    name: str
    sourceRepository: str
    frozenHoldout: str
    candidates: list[Candidate] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> CandidateManifest:
        ids = [candidate.id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique")
        return self


class CandidateReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    candidate_id: str
    annotator: str
    disposition: Literal["clean", "material_issue", "indeterminate"]
    reviewability: Literal["sufficient", "insufficient"]
    confidence: int = Field(ge=1, le=5)
    rationale: str
    dimensions: dict[MetricKey, Literal["weak", "acceptable", "not_applicable", "uncertain"]]
    priorities: list[MetricKey] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_reference(self) -> CandidateReference:
        if set(self.dimensions) != set(METRIC_KEYS):
            raise ValueError("reference must classify every rubric dimension")
        if len(set(self.priorities)) != len(self.priorities):
            raise ValueError("reference priorities must be unique")
        if any(self.dimensions[metric] != "weak" for metric in self.priorities):
            raise ValueError("reference priorities must identify weak dimensions")
        if self.disposition == "clean" and self.priorities:
            raise ValueError("clean references cannot have priorities")
        return self


def load_candidate_manifest(path: Path) -> CandidateManifest:
    return CandidateManifest.model_validate(yaml.safe_load(path.read_text()))


def stage_candidates(
    repository: Path,
    manifest_path: Path,
    destination: Path,
    *,
    force: bool = False,
    fetch_missing: bool = False,
    max_patch_bytes: int = 150_000,
) -> dict[str, Any]:
    repository = repository.resolve()
    destination = destination.resolve()
    manifest = load_candidate_manifest(manifest_path)
    source_dirty = bool(_git(repository, "status", "--porcelain"))

    destination.mkdir(parents=True, exist_ok=True)
    expected_ids = {candidate.id for candidate in manifest.candidates}
    if force:
        for path in destination.iterdir():
            if path.is_dir() and path.name not in expected_ids:
                shutil.rmtree(path)
    staged: list[dict[str, object]] = []
    for candidate in manifest.candidates:
        revisions = [candidate.fromRevision, candidate.toRevision]
        if candidate.confirmingRevision:
            revisions.append(candidate.confirmingRevision)
        resolved = {
            revision: _resolve_revision(repository, revision, fetch_missing)
            for revision in revisions
        }
        patch = _git_bytes(
            repository,
            "diff",
            "--no-ext-diff",
            "--find-renames",
            candidate.fromRevision,
            candidate.toRevision,
            "--",
            *candidate.paths,
        )
        if not patch.strip():
            raise ValueError(f"candidate {candidate.id} produced an empty patch")
        if len(patch) > max_patch_bytes:
            raise ValueError(
                f"candidate {candidate.id} patch is {len(patch)} bytes; limit is {max_patch_bytes}"
            )
        target = destination / candidate.id
        if target.exists() and not force:
            raise FileExistsError(f"refusing to overwrite {target}")
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        patch_path = target / "change.patch"
        metadata_path = target / "candidate.json"
        patch_path.write_bytes(patch)
        metadata = {
            **candidate.model_dump(),
            "resolvedRevisions": resolved,
            "patchSha256": hashlib.sha256(patch).hexdigest(),
            "patchBytes": len(patch),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        staged.append(metadata)

    lock = {
        "schemaVersion": 1,
        "manifest": manifest.name,
        "sourceRepository": manifest.sourceRepository,
        "sourceRevision": _git(repository, "rev-parse", "HEAD"),
        "sourceDirty": source_dirty,
        "frozenHoldout": manifest.frozenHoldout,
        "manifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "candidates": staged,
    }
    lock_path = destination / "candidates.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    validate_staged_candidates(manifest_path, destination)
    return lock


def validate_staged_candidates(manifest_path: Path, destination: Path) -> dict[str, int]:
    manifest = load_candidate_manifest(manifest_path)
    lock_path = destination / "candidates.lock.json"
    lock = json.loads(lock_path.read_text())
    if lock.get("manifestSha256") != hashlib.sha256(manifest_path.read_bytes()).hexdigest():
        raise ValueError("candidate manifest hash does not match lock")
    entries = {entry["id"]: entry for entry in lock.get("candidates", [])}
    expected = {candidate.id: candidate for candidate in manifest.candidates}
    if set(entries) != set(expected):
        raise ValueError("candidate lock ids do not match manifest")

    group_targets: dict[str, set[str]] = {}
    counts = {"train": 0, "dev": 0, "defect": 0, "clean": 0}
    for case_id, candidate in expected.items():
        entry = entries[case_id]
        metadata_path = destination / case_id / "candidate.json"
        patch_path = destination / case_id / "change.patch"
        if not metadata_path.is_file() or not patch_path.is_file():
            raise ValueError(f"candidate {case_id} is missing staged files")
        metadata = json.loads(metadata_path.read_text())
        if metadata != entry:
            raise ValueError(f"candidate {case_id} metadata differs from lock")
        for key, value in candidate.model_dump().items():
            if metadata.get(key) != value:
                raise ValueError(f"candidate {case_id} metadata differs for {key}")
        patch = patch_path.read_bytes()
        if metadata.get("patchSha256") != hashlib.sha256(patch).hexdigest():
            raise ValueError(f"candidate {case_id} patch hash mismatch")
        if metadata.get("patchBytes") != len(patch):
            raise ValueError(f"candidate {case_id} patch size mismatch")
        group_targets.setdefault(candidate.group, set()).add(candidate.target)
        counts[candidate.target] += 1
        counts[candidate.outcome] += 1
    leaking = sorted(group for group, targets in group_targets.items() if len(targets) > 1)
    if leaking:
        raise ValueError(f"candidate groups cross train/dev partitions: {leaking}")
    return counts


def promote_candidates(
    base_corpus: Path,
    manifest_path: Path,
    staged: Path,
    references: Path,
    destination: Path,
    *,
    force: bool = False,
) -> dict[str, object]:
    manifest = load_candidate_manifest(manifest_path)
    validate_staged_candidates(manifest_path, staged)
    if destination.exists():
        if not force:
            raise FileExistsError(f"refusing to overwrite {destination}")
        shutil.rmtree(destination)
    shutil.copytree(base_corpus, destination)
    (destination / "corpus.lock.json").unlink(missing_ok=True)

    train: list[str] = []
    dev: list[str] = []
    for candidate in manifest.candidates:
        reference_path = references / f"{candidate.id}.json"
        if not reference_path.is_file():
            raise ValueError(f"candidate {candidate.id} has no reference")
        reference = CandidateReference.model_validate_json(reference_path.read_text())
        if reference.candidate_id != candidate.id:
            raise ValueError(f"reference id mismatch for {candidate.id}")
        expected_clean = candidate.outcome == "clean"
        if expected_clean != (reference.disposition == "clean"):
            raise ValueError(f"reference outcome mismatch for {candidate.id}")

        target = destination / "cases" / candidate.id
        target.mkdir(parents=True)
        shutil.copyfile(staged / candidate.id / "change.patch", target / "change.patch")
        shutil.copyfile(reference_path, target / "reference.json")
        expected = []
        if candidate.outcome == "defect":
            category = "SECURITY" if candidate.category == "security" else "QUALITY"
            expected = [
                {
                    "id": f"DRS-PR{candidate.pullRequest}-001",
                    "description": candidate.description,
                    "severity": candidate.severity,
                    "category": category,
                    "file": candidate.paths[0],
                    "line": None,
                }
            ]
        case = {
            "id": candidate.id,
            "description": candidate.description,
            "dimensions": [candidate.category],
            "comparison": Comparison(group=candidate.group, variant=candidate.outcome).model_dump(),
            "jev": {"expectedWeakDimensions": reference.priorities}
            if reference.priorities
            else None,
            "expected": expected,
        }
        (target / "case.yaml").write_text(yaml.safe_dump(case, sort_keys=False))
        evidence = {
            "provenance": "historical" if candidate.outcome == "clean" else "derived-historical",
            "source": candidate.source,
            "proposedRevision": candidate.toRevision,
            "confirmingRevision": candidate.confirmingRevision,
            "rationale": candidate.evidence,
            "referenceAnnotator": reference.annotator,
        }
        (target / "evidence.yaml").write_text(yaml.safe_dump(evidence, sort_keys=False))
        (train if candidate.target == "train" else dev).append(candidate.id)

    suite = {
        "name": "expansion-v1",
        "description": "Evidence-backed DRS training and development cases.",
        "focus": "quality-evaluator-optimization",
        "cases": train + dev,
    }
    (destination / "manifests" / "expansion-v1.yaml").write_text(
        yaml.safe_dump(suite, sort_keys=False)
    )
    base_split = yaml.safe_load((base_corpus / "splits" / "pilot-v1.yaml").read_text())
    split = {
        "name": "expansion-v1",
        "policy": "Historical groups are isolated; the original pilot test remains frozen.",
        "train": train,
        "dev": dev,
        "test": base_split["test"],
    }
    (destination / "splits" / "expansion-v1.yaml").write_text(
        yaml.safe_dump(split, sort_keys=False)
    )
    baseline_split = {
        "name": "expansion-baseline-v1",
        "policy": "Diagnostic baseline over labeled train and development cases; not a holdout.",
        "train": [],
        "dev": [],
        "test": train + dev,
    }
    (destination / "splits" / "expansion-baseline-v1.yaml").write_text(
        yaml.safe_dump(baseline_split, sort_keys=False)
    )

    files = {
        str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file() and path.name != "corpus.lock.json"
    }
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    lock: dict[str, object] = {
        "schemaVersion": 2,
        "source": manifest.sourceRepository,
        "sourceRevision": json.loads((staged / "candidates.lock.json").read_text())[
            "sourceRevision"
        ],
        "sourceDirty": json.loads((staged / "candidates.lock.json").read_text())["sourceDirty"],
        "suites": ["expansion-v1"],
        "baseCorpusSha256": json.loads((base_corpus / "corpus.lock.json").read_text())[
            "contentSha256"
        ],
        "files": files,
        "contentSha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    (destination / "corpus.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    return lock


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _resolve_revision(repository: Path, revision: str, fetch_missing: bool) -> str:
    try:
        return _git(repository, "rev-parse", f"{revision}^{{commit}}")
    except subprocess.CalledProcessError as error:
        if not fetch_missing:
            raise ValueError(
                f"revision {revision} is unavailable; rerun with --fetch-missing"
            ) from error
        _git(repository, "fetch", "--no-tags", "origin", revision)
        return _git(repository, "rev-parse", f"{revision}^{{commit}}")


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout
