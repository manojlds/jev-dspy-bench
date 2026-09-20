# Repository Guidance

## Purpose

This repository benchmarks Jev against direct and DSPy-optimized general-purpose LLM evaluators.
Preserve evaluator independence and prevent train/test leakage.

## Commands

```bash
uv sync --extra dev
make check
uv run jev-dspy corpus validate
```

## Rules

- Never expose `case.yaml`, `evidence.yaml`, expectations, or split labels to an evaluator.
- Keep historical test cases out of optimization and prompt development.
- Treat Jev agreement as similarity, not correctness.
- Record compilation usage separately from inference usage.
- Do not commit provider credentials or source-containing run artifacts.
- Any rubric or corpus change must alter its recorded hash.
- Run `make check` after every code change.
