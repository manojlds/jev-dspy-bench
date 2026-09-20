# Dataset Expansion

This directory stages evidence-backed candidates before they enter the immutable benchmark corpus.
Candidate metadata and patches are review material, not labels available to evaluators.

## Current Batch

`drs-candidates-v1.yaml` defines the first 20 candidates:

- 14 training candidates: 7 defect and 7 clean.
- 6 development candidates: 3 defect and 3 clean.
- 10 frozen `pilot-v1:test` cases remain unchanged and are not reused.

Cases sharing a root cause use the same `group` and must remain in one partition. Defect evidence is
based on an accepted review fix or an exact later corrective revision. Clean evidence requires
focused tests, successful checks, a zero-finding final review, and no attributable corrective
follow-up.

## Reproduce

Generate focused patches and a hash lock from exact Git revisions:

```bash
uv run jev-dspy corpus stage-candidates \
  --repository ../drs \
  --manifest expansion/drs-candidates-v1.yaml \
  --fetch-missing \
  --force
```

`--fetch-missing` explicitly fetches GitHub-retained in-PR commits that are not reachable from the
source repository's main branch. A dirty source worktree is recorded in the lock but cannot affect
revision-to-revision diffs.

Verify the committed patch and metadata hashes without network or source-repository access:

```bash
uv run jev-dspy corpus validate-candidates \
  --manifest expansion/drs-candidates-v1.yaml
```

## Promotion Gate

A staged candidate can enter a versioned corpus only after:

1. Its patch is independently checked against the claimed outcome and evidence.
2. An output-independent 19-dimension reference is completed.
3. Related variants and fixes are confirmed to remain in the same split.
4. The case is checked for semantic overlap with the frozen holdout.
5. The promoted corpus lock is regenerated and reviewed.

Expected findings and evidence remain adjudication-only data and are never included in evaluator
state.

The 20 output-independent references are stored in `references/`. Promotion creates the separate
`corpora/expansion-v1` snapshot and a new lock without mutating the original `corpus/`:

```bash
uv run jev-dspy corpus promote-candidates \
  --manifest expansion/drs-candidates-v1.yaml \
  --output corpora/expansion-v1 \
  --force
```
