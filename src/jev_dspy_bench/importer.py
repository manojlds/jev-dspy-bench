from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .schema import CaseMetadata, SuiteManifest


def import_drs_corpus(
    drs_root: Path,
    destination: Path,
    suites: list[str],
    *,
    force: bool = False,
) -> dict[str, object]:
    source = drs_root.resolve() / "benchmarks" / "review"
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifests = destination / "manifests"
    cases_root = destination / "cases"
    manifests.mkdir(exist_ok=True)
    cases_root.mkdir(exist_ok=True)

    case_ids: set[str] = set()
    copied: list[Path] = []
    for suite_name in suites:
        source_manifest = source / "suites" / f"{suite_name}.yaml"
        suite = SuiteManifest.model_validate(yaml.safe_load(source_manifest.read_text()))
        target_manifest = manifests / source_manifest.name
        _copy(source_manifest, target_manifest, force)
        copied.append(target_manifest)
        case_ids.update(suite.cases)

    for case_id in sorted(case_ids):
        source_case = source / "cases" / case_id
        target_case = cases_root / case_id
        target_case.mkdir(exist_ok=True)
        metadata = CaseMetadata.model_validate(
            yaml.safe_load((source_case / "case.yaml").read_text())
        )
        if metadata.id != case_id:
            raise ValueError(f"case id mismatch: {case_id}")
        for filename in ("case.yaml", "change.patch", "evidence.yaml"):
            source_file = source_case / filename
            if not source_file.exists():
                if filename == "evidence.yaml":
                    continue
                raise FileNotFoundError(source_file)
            target_file = target_case / filename
            _copy(source_file, target_file, force)
            copied.append(target_file)

    revision = _git(drs_root, "rev-parse", "HEAD")
    source_dirty = bool(_git(drs_root, "status", "--porcelain"))
    hashes = {
        str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(copied)
    }
    lock: dict[str, object] = {
        "schemaVersion": 1,
        "source": "https://github.com/manojlds/drs",
        "sourceRevision": revision,
        "sourceDirty": source_dirty,
        "importedAt": datetime.now(UTC).isoformat(),
        "suites": suites,
        "files": hashes,
        "contentSha256": _hash_mapping(hashes),
    }
    lock_path = destination / "corpus.lock.json"
    if lock_path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {lock_path}")
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    return lock


def _copy(source: Path, target: Path, force: bool) -> None:
    if target.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {target}")
    shutil.copyfile(source, target)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hash_mapping(values: dict[str, str]) -> str:
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
