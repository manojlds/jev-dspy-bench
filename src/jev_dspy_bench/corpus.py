from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from .schema import CaseMetadata, ReviewState, SuiteManifest
from .state import build_state, serialize_state


@dataclass(frozen=True)
class BenchmarkCase:
    metadata: CaseMetadata
    state: ReviewState
    state_json: str
    state_sha256: str


class Corpus:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load_suite(self, name: str) -> SuiteManifest:
        path = self.root / "manifests" / f"{name}.yaml"
        return SuiteManifest.model_validate(yaml.safe_load(path.read_text()))

    def load_case(self, case_id: str) -> BenchmarkCase:
        case_root = self.root / "cases" / case_id
        metadata = CaseMetadata.model_validate(
            yaml.safe_load((case_root / "case.yaml").read_text())
        )
        patch = (case_root / "change.patch").read_text()
        state = build_state(patch)
        state_json = serialize_state(state)
        return BenchmarkCase(
            metadata=metadata,
            state=state,
            state_json=state_json,
            state_sha256=hashlib.sha256(state_json.encode()).hexdigest(),
        )

    def iter_suite(self, name: str) -> list[BenchmarkCase]:
        suite = self.load_suite(name)
        return [self.load_case(case_id) for case_id in suite.cases]

    def lock(self) -> dict[str, object]:
        return json.loads((self.root / "corpus.lock.json").read_text())

    def validate_lock(self) -> None:
        lock = self.lock()
        files = lock.get("files")
        expected_digest = lock.get("contentSha256")
        if not isinstance(files, dict) or not all(
            isinstance(path, str) and isinstance(digest, str) for path, digest in files.items()
        ):
            raise ValueError("corpus lock has an invalid file map")
        actual: dict[str, str] = {}
        for relative_path in sorted(files):
            path = self.root / relative_path
            if not path.is_file():
                raise ValueError(f"corpus lock references missing file: {relative_path}")
            actual[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != files:
            raise ValueError("corpus contents do not match corpus.lock.json")
        canonical = json.dumps(actual, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != expected_digest:
            raise ValueError("corpus aggregate hash does not match corpus.lock.json")
