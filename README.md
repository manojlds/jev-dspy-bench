# Jev vs DSPy Benchmark

Reproducible experiments comparing [TypeSafe Jev](https://typesafe.ai/) with
general-purpose LLM quality evaluators, both directly prompted and optimized with
[DSPy](https://dspy.ai/).

DSPy is not itself an evaluator. The benchmark therefore compares four explicit arms:

1. Jev, a specialized evaluator.
2. A direct, handwritten prompt using a general-purpose LLM.
3. The same LLM through an uncompiled DSPy program.
4. The same DSPy program after train-only optimization.

## Fairness Contract

- Every arm receives the same canonical software-change state for a case.
- Every arm produces the same 19-dimension normalized scorecard.
- Direct and DSPy arms use the same base model in a comparison.
- DSPy compilation sees only the declared train and development partitions.
- Historical cases are test-only in `pilot-v1`.
- Jev agreement is reported as similarity, never as ground truth.
- Jev probabilities are not compared with synthetic LLM confidence.
- Compilation cost is separate from held-out inference cost.
- There is no aggregate quality grade or merge gate.

The state, rubric, corpus, program, and model identities are hashed or recorded in every run.

## Current Corpus

The initial snapshot imports these DRS suites:

- `jev-calibration-v1`: synthetic calibration and defect/fixed fixtures.
- `jev-historical-pilot-v1`: evidence-backed historical defects and clean controls.

The snapshot records the DRS revision, whether its source worktree was dirty, and every imported
file hash in `corpus/corpus.lock.json`. Expected findings and historical evidence are retained for
adjudication but never included in evaluator state.

The corpus is intentionally small. It validates the harness and supports a pilot, but it does not
support broad statistical claims about either system.

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --extra dev
cp .env.example .env
```

Provider credentials are read from the environment. Do not commit `.env` or generated run
artifacts because evaluator state can contain source code.

## Validate The Snapshot

```bash
uv run jev-dspy corpus validate
```

To intentionally refresh it from a DRS working tree:

```bash
uv run jev-dspy corpus import \
  --drs ../drs \
  --suite jev-calibration-v1 \
  --suite jev-historical-pilot-v1 \
  --force
```

Review the lockfile diff after every refresh. A dirty source is allowed but explicitly recorded.

## Run Baselines

Set `live: true` in a copy of `configs/pilot.yaml`, select an exact provider-qualified model, then:

```bash
uv run jev-dspy evaluate --config configs/pilot.yaml
```

Live execution is deliberately opt-in. It requires `JEV_API_KEY` and the selected LLM provider
credential. JSON and Markdown reports are written under `artifacts/runs/` and ignored by Git.

For an unoptimized DSPy comparison through OpenCode Go:

```bash
uv run jev-dspy evaluate --config configs/jev-vs-dspy-glm-5.3-flash.yaml
```

The Jev arm uses TypeSafe directly. The DSPy arm maps `opencode-go/<model>` to OpenCode Go's
OpenAI-compatible endpoint and supplies the required session-routing header. Set `OPENCODE_API_KEY`
and optionally `OPENCODE_BASE_URL`; `OPENAI_API_KEY` and `OPENAI_BASE_URL` are accepted as compatible
fallbacks.

Reports separate quality signals from efficiency. They include latency, input/output tokens, total
tokens, median cost, and total cost. Jev cost uses TypeSafe's published direct rate. OpenCode Go is
subscription-billed, so its dollar figure is explicitly labeled as a token-equivalent reference
estimate rather than a marginal invoice charge.

## Optimize A DSPy Program

```bash
uv run jev-dspy optimize \
  --split pilot-v1 \
  --model openai/gpt-4o-mini \
  --output artifacts/programs/pilot-mipro.json \
  --auto light \
  --seed 42
```

The optimizer uses calibration train/dev cases only. The emitted manifest records the split,
optimizer, model, seed, corpus hash, and program hash. Add the resulting program path to a DSPy
evaluator in a holdout config before evaluating the historical test partition.

The pilot optimization metric rewards expected weak dimensions in the top-five priorities and
penalizes priorities on clean cases. It is weak supervision, not a substitute for complete manual
labels.

## Development

```bash
make check
```

This runs formatting, linting, type checking, and offline tests. Tests never make provider calls.

## Manual Adjudication

Import a completed run, seed optional output-independent agent drafts, and start the service:

```bash
uv run jev-dspy adjudicate import artifacts/runs/<run>.json
uv run jev-dspy adjudicate seed-agent <study-id> --annotator opencode-agent
vaibhav dev start adjudication
```

`vaibhav dev start` runs the service on localhost and publishes it to a tailnet-only Tailscale HTTPS
port. Use `vaibhav dev status` to find the URL. Annotation data is stored under
`artifacts/adjudication/` and is intentionally ignored because it can contain source code.

Each annotator must submit an immutable reference judgment before seeing anonymized evaluator
outputs. Completing the comparison reveals evaluator identities. Human and agent annotations use
separate annotator IDs and every save or submission is recorded in the audit log.

## Expansion Protocol

Before making comparative quality claims:

1. Expand to at least 60–100 train, 20–30 development, and 30–50 chronological holdout cases.
2. Keep all related variants and defect/fixed pairs in one partition.
3. Add blinded dimension applicability, score-range, weakness, and priority adjudication.
4. Freeze the rubric, optimizer settings, prompts, thresholds, and holdout manifest.
5. Run repeated evaluations and inspect every disagreement.
6. Report quality, stability, latency, token use, inference cost, and compilation cost separately.

## Attribution

The 19-dimension rubric is adapted from `jev-review` 0.1.1 under the MIT license, commit
`57690af54ef7d862c2483342c1e61c14dffcf727`. The initial benchmark fixtures are imported from DRS,
licensed under Apache-2.0. See `THIRD_PARTY_NOTICES.md`.
