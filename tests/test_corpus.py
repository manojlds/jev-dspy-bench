from pathlib import Path

import yaml

from jev_dspy_bench.corpus import Corpus


def test_committed_corpus_is_loadable() -> None:
    root = Path(__file__).resolve().parents[1]
    corpus = Corpus(root / "corpus")
    corpus.validate_lock()
    cases = corpus.iter_suite("jev-calibration-v1")
    assert len(cases) == 6
    assert len({case.state_sha256 for case in cases}) == 6
    assert corpus.load_case("q7m4-x2").state_sha256 == (
        "fdc9caea51627eddaaf960008a4dc298243a23d1594a5994cdd3b0b518637af7"
    )
    assert corpus.lock()["sourceRevision"]


def test_expansion_corpus_preserves_holdout_and_full_references() -> None:
    root = Path(__file__).resolve().parents[1]
    corpus = Corpus(root / "corpora" / "expansion-v1")
    corpus.validate_lock()
    assert len(corpus.iter_suite("expansion-v1")) == 20
    split = yaml.safe_load((corpus.root / "splits" / "expansion-v1.yaml").read_text())
    assert (len(split["train"]), len(split["dev"]), len(split["test"])) == (14, 6, 10)
    assert set(split["train"]).isdisjoint(split["dev"])
    pilot = yaml.safe_load((root / "corpus" / "splits" / "pilot-v1.yaml").read_text())
    assert split["test"] == pilot["test"]
    for case_id in split["train"] + split["dev"]:
        assert (corpus.root / "cases" / case_id / "reference.json").is_file()
