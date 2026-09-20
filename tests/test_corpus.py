from pathlib import Path

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
