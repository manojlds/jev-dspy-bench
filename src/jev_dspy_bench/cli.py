from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from .config import load_config
from .corpus import Corpus
from .importer import import_drs_corpus
from .metrics import agreement, summarize
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
def corpus_validate() -> None:
    corpus = Corpus(_root() / "corpus")
    corpus.validate_lock()
    lock = corpus.lock()
    suites = lock.get("suites")
    if not isinstance(suites, list) or not all(isinstance(item, str) for item in suites):
        raise typer.BadParameter("corpus lock has invalid suites")
    count = 0
    for suite_name in suites:
        count += len(corpus.iter_suite(suite_name))
    split_root = _root() / "corpus" / "splits"
    for split_path in split_root.glob("*.yaml"):
        split = yaml.safe_load(split_path.read_text())
        partitions = [set(split.get(name, [])) for name in ("train", "dev", "test")]
        if any(partitions[left] & partitions[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise typer.BadParameter(f"split partitions overlap: {split_path.name}")
        for case_id in set().union(*partitions):
            corpus.load_case(case_id)
    typer.echo(f"Validated {len(suites)} suites and {count} suite case entries.")


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
        seed=seed,
        auto=auto,
    )
    typer.echo(path)


@app.command()
def report(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, resolve_path=True),
) -> None:
    data = json.loads(artifact.read_text())
    enrich_report_costs(data)
    corpus = Corpus(_root() / "corpus")
    case_ids = {run["caseId"] for run in data.get("runs", [])}
    metadata = {case_id: corpus.load_case(case_id).metadata for case_id in case_ids}
    data["analysis"] = summarize(data.get("runs", []), metadata)
    data["agreementWithJev"] = agreement(data.get("runs", []))
    artifact.write_text(json.dumps(data, indent=2) + "\n")
    output = artifact.with_suffix(".md")
    output.write_text(format_report(data))
    typer.echo(output)


@adjudicate_app.command("import")
def adjudicate_import(
    artifact: Path = typer.Argument(..., exists=True, dir_okay=False, resolve_path=True),
    database: Path = typer.Option(Path("artifacts/adjudication/adjudication.sqlite")),
) -> None:
    from .adjudication import AdjudicationStore

    store = AdjudicationStore(_root() / database)
    study_id = store.import_artifact(artifact, _root() / "corpus")
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
