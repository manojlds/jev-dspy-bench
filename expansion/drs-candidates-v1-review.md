# DRS Candidate Batch V1 Review

Date: 2026-09-20
Manifest: `drs-candidates-v1.yaml`
Frozen holdout: `pilot-v1:test`

## Accepted Batch

The staged batch contains 20 candidates from exact historical revisions:

| Target | Defect | Clean | Total |
| --- | ---: | ---: | ---: |
| Train | 7 | 7 | 14 |
| Development | 3 | 3 | 6 |
| Total | 10 | 10 | 20 |

Defects cover correctness, security, reliability, concurrency, input validation, review-context
completeness, and release automation. Clean controls cover validation, CLI behavior, artifact
persistence, compatibility migrations, observability, and parsing precedence.

Every accepted patch was independently checked for:

- A patch-only review state that supports the claimed outcome.
- Correct revision direction, including derived reverse-fix patches.
- Coherent confirming evidence for defects.
- Focused tests and no visible material defect for clean controls.
- No expected-finding prose embedded in evaluator input.
- No semantic duplication or source continuation from the frozen pilot holdout.
- No related group crossing the train/development boundary.

## Rejected Candidates

Candidate discovery intentionally retained rejection information to make selection pressure visible.

| Candidate | Reason rejected |
| --- | --- |
| PR 122 artifact path sanitization | Duplicated the frozen holdout's path-traversal reasoning. |
| PR 129 post-fix routing | Overlapped the frozen holdout's fix-mode commit-branch isolation case. |
| PR 115 adaptive diff context | Independent review found omitted remote/staged patches may be unrecoverable through the default tool path, so it was not a clean control. |
| PR 168 cancellation state | Directly continued the workflow-status API used by frozen holdout source PR 167. |
| PR 208 guidance-rubric freshness | The focused patch lacked enough visible repository context to establish the expected defect. |

Broad or ambiguous PRs, documentation-only changes, test-only changes, and changes without a
distinct confirming revision were also excluded during discovery.

## Status

These remain staged candidates, not benchmark labels. Promotion requires complete output-independent
19-dimension references and a regenerated corpus lock. The existing ten pilot test cases remain
unchanged and cannot be used for DSPy optimization.
