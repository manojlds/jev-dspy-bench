from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from jev_dspy_bench.candidates import stage_candidates, validate_staged_candidates


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_stage_candidates_records_patch_and_revisions(tmp_path: Path) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "test@example.com")
    _git(repository, "config", "user.name", "Test")
    source = repository / "example.py"
    source.write_text("enabled = True\n")
    _git(repository, "add", "example.py")
    _git(repository, "commit", "-m", "base")
    base = _git(repository, "rev-parse", "HEAD")
    source.write_text("enabled = False\n")
    _git(repository, "commit", "-am", "change")
    proposed = _git(repository, "rev-parse", "HEAD")
    source.write_text("enabled = True\n")
    _git(repository, "commit", "-am", "fix")
    confirming = _git(repository, "rev-parse", "HEAD")

    manifest = tmp_path / "candidates.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schemaVersion": 1,
                "name": "test-v1",
                "sourceRepository": "https://example.com/repo",
                "frozenHoldout": "pilot-v1:test",
                "candidates": [
                    {
                        "id": "example-defect",
                        "group": "example-pair",
                        "target": "train",
                        "outcome": "defect",
                        "description": "A condition is inverted.",
                        "category": "correctness",
                        "severity": "HIGH",
                        "pullRequest": 1,
                        "source": "https://example.com/repo/pull/1",
                        "fromRevision": base,
                        "toRevision": proposed,
                        "confirmingRevision": confirming,
                        "paths": ["example.py"],
                        "evidence": "The next commit restores the condition.",
                    }
                ],
            }
        )
    )
    output = tmp_path / "staged"
    lock = stage_candidates(repository, manifest, output)

    assert len(lock["candidates"]) == 1
    patch = (output / "example-defect" / "change.patch").read_text()
    assert "-enabled = True" in patch
    assert "+enabled = False" in patch
    metadata = json.loads((output / "example-defect" / "candidate.json").read_text())
    assert metadata["resolvedRevisions"][base] == base
    assert len(metadata["patchSha256"]) == 64
    assert validate_staged_candidates(manifest, output) == {
        "train": 1,
        "dev": 0,
        "defect": 1,
        "clean": 0,
    }

    (output / "example-defect" / "change.patch").write_text("tampered\n")
    with pytest.raises(ValueError, match="patch hash mismatch"):
        validate_staged_candidates(manifest, output)
