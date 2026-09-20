from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from .candidates import promote_candidates, stage_candidates, validate_staged_candidates
from .config import load_config
from .corpus import Corpus
from .importer import import_drs_corpus
from .metrics import agreement, summarize, summarize_references
from .optimize import compile_program
from .runner import enrich_report_costs, format_report, run_experiment

app = typer.Typer(no_args_is_help=True, help="Benchmark Jev against DSPy-optimized LLM evaluators.")
corpus_app = typer.Typer(no_args_is_help=True, help="Manage immutable benchmark corpus snapshots.")
adjudicate_app = typer.Typer(no_args_is_help=True, help="Run blinded manual adjudication.")
app.add_typer(corpus_app, name="corpus")
app.add_typer(adjudicate_app, name="adjudicate")


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


@corpus_app.command("import")
def corpus_import(
    drs: Path = typer.Option(..., exists=True, file_okay=False, resolve_path=True),
    suite: list[str] = typer.Option(..., help="DRS suite to import; repeat for multiple suites."),
    force: bool = typer.Option(False, help="Replace the existing corpus snapshot."),
) -> None:
    lock = import_drs_corpus(drs, _root() / "corpus", suite, force=force)
    typer.echo(json.dumps(lock, indent=2))


@corpus_app.command("validate")
def corpus_validate(
    corpus_path: Path = typer.Option(Path("corpus"), "--corpus"),
) -> None:
    corpus = Corpus(_root() / corpus_path)
    corpus.validate_lock()
    lock = corpus.lock()
    suites = lock.get("suites")
    if not isinstance(suites, list) or not all(isinstance(item, str) for item in suites):
        raise typer.BadParameter("corpus lock has invalid suites")
    count = 0
    for suite_name in suites:
        count += len(corpus.iter_suite(suite_name))
    split_root = _root() / corpus_path / "splits"
    for split_path in split_root.glob("*.yaml"):
        split = yaml.safe_load(split_path.read_text())
        partitions = [set(split.get(name, [])) for name in ("train", "dev", "test")]
        if any(partitions[left] & partitions[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise typer.BadParameter(f"split partitions overlap: {split_path.name}")
        for case_id in set().union(*partitions):
            corpus.load_case(case_id)
    typer.echo(f"Validated {len(suites)} suites and {count} suite case entries.")


@corpus_app.command("stage-candidates")
def corpus_stage_candidates(
    repository: Path = typer.Option(..., exists=True, file_okay=False, resolve_path=True),
    manifest: Path = typer.Option(..., exists=True, dir_okay=False, resolve_path=True),
    output: Path = typer.Option(Path("expansion/candidates")),
    force: bool = typer.Option(False),
    fetch_missing: bool = typer.Option(
        False, help="Fetch exact GitHub-retained commits missing from local history."
    ),
) -> None:
    lock = stage_candidates(
        repository,
        manifest,
        _root() / output,
        force=force,
        fetch_missing=fetch_missing,
    )
    typer.echo(f"Staged {len(lock['candidates'])} candidates at {_root() / output}")


@corpus_app.command("validate-candidates")
def corpus_validate_candidates(
    manifest: Path = typer.Option(..., exists=True, dir_okay=False, resolve_path=True),
    candidates: Path = typer.Option(Path("expansion/candidates")),
) -> None:
    counts = validate_staged_candidates(manifest, _root() / candidates)
    typer.echo(
        f"Validated {counts['train']} train and {counts['dev']} dev candidates "
        f"({counts['defect']} defect, {counts['clean']} clean)."
    )


@corpus_app.command("promote-candidates")
def corpus_promote_candidates(
    manifest: Path = typer.Option(..., exists=True, dir_okay=False, resolve_path=True),
    candidates: Path = typer.Option(Path("expansion/candidates")),
    references: Path = typer.Option(Path("expansion/references")),
    base_corpus: Path = typer.Option(Path("corpus")),
    output: Path = typer.Option(Path("corpora/expansion-v1")),
    force: bool = typer.Option(False),
) -> None:
    lock = promote_candidates(
        _root() / base_corpus,
        manifest,
        _root() / candidates,
        _root() / references,
        _root() / output,
        force=force,
    )
    typer.echo(f"Promoted candidate corpus: {lock['contentSha256']}")


@app.command()
def evaluate(
    config: Path = typer.Option(..., exists=True, dir_okay=False, resolve_path=True),
) -> None:
    path = run_experiment(_root(), load_config(config))
    typer.echo(path)


@app.command()
def optimize(
    split: str = typer.Option("pilot-v1"),
    model: str = typer.Option(..., envvar="DSPY_MODEL"),
    output: Path = typer.Option(Path("artifacts/programs/pilot-mipro.json")),
    corpus: Path = typer.Option(Path("corpus")),
    seed: int = typer.Option(42),
    auto: str = typer.Option("light", help="MIPROv2 budget: light, medium, or heavy."),
) -> None:
    if auto not in {"light", "medium", "heavy"}:
        raise typer.BadParameter("auto must be light, medium, or heavy")
    path = compile_program(
        _root(),
        split_name=split,
        model=model,
        output=output,
        corpus_path=corpus,
        seed=seed,
        auto=auto,
    )
    typer.echo(path)


@app.command()
def report(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, resolve_path=True),
    corpus_path: Path = typer.Option(Path("corpus"), "--corpus"),
) -> None:
    data = json.loads(artifact.read_text())
    enrich_report_costs(data)
    corpus = Corpus(_root() / corpus_path)
    case_ids = {run["caseId"] for run in data.get("runs", [])}
    metadata = {case_id: corpus.load_case(case_id).metadata for case_id in case_ids}
    data["analysis"] = summarize(data.get("runs", []), metadata)
    references = {}
    for case_id in case_ids:
        reference_path = corpus.root / "cases" / case_id / "reference.json"
        if reference_path.is_file():
            references[case_id] = json.loads(reference_path.read_text())
    data["referenceAnalysis"] = summarize_references(data.get("runs", []), references)
    data["agreementWithJev"] = agreement(data.get("runs", []))
    artifact.write_text(json.dumps(data, indent=2) + "\n")
    output = artifact.with_suffix(".md")
    output.write_text(format_report(data))
    typer.echo(output)


@adjudicate_app.command("import")
def adjudicate_import(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, resolve_path=True),
    database: Path = typer.Option(Path("artifacts/adjudication/adjudication.sqlite")),
    corpus: Path = typer.Option(Path("corpus")),
) -> None:
    from .adjudication import AdjudicationStore

    store = AdjudicationStore(_root() / database)
    study_id = store.import_artifact(artifact, _root() / corpus)
    typer.echo(study_id)


@adjudicate_app.command("seed-agent")
def adjudicate_seed_agent(
    study: str = typer.Argument(...),
    annotator: str = typer.Option("opencode-agent"),
    database: Path = typer.Option(Path("artifacts/adjudication/adjudication.sqlite")),
) -> None:
    from .adjudication import AdjudicationStore

    count = AdjudicationStore(_root() / database).seed_agent_references(study, annotator)
    typer.echo(f"Seeded {count} blinded agent reference drafts.")


@adjudicate_app.command("serve")
def adjudicate_serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
    database: Path = typer.Option(Path("artifacts/adjudication/adjudication.sqlite")),
) -> None:
    import uvicorn

    from .adjudication_web import create_app

    uvicorn.run(create_app(_root() / database), host=host, port=port)


@adjudicate_app.command("export")
def adjudicate_export(
    study: str = typer.Argument(...),
    annotator: str = typer.Option("opencode-agent"),
    database: Path = typer.Option(Path("artifacts/adjudication/adjudication.sqlite")),
    output: Path | None = typer.Option(None),
) -> None:
    from .adjudication import AdjudicationStore

    destination = output or Path("reports/adjudication") / f"{study}-{annotator}.json"
    destination = _root() / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    snapshot = AdjudicationStore(_root() / database).export_snapshot(study, annotator)
    destination.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    typer.echo(destination)


if __name__ == "__main__":
    app()
