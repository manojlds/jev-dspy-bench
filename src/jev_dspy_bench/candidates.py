from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
