# Jev vs unoptimized DSPy: GLM 5.3 Flash pilot

- Run date: 2026-09-20
- Cases: 10 historical DRS pilot cases, one run per evaluator
- Jev transport: direct TypeSafe API
- DSPy transport: OpenCode Go, `opencode-go/glm-5.3-flash`
- DSPy optimization: none

Only prepared state content was shared exactly; request framing differed by evaluator. Agreement
with Jev measures similarity, not correctness.

## Comparison Summary

- Unoptimized DSPy's expected-priority hit rate was 81.8 percentage points higher than Jev's.
- Jev's median end-to-end latency was 22.3 times lower.
- Jev was 5.6 times cheaper on the stated token-equivalent reference basis.
- Both evaluators produced priorities for every clean control, so this run does not establish
  clean-case specificity for either system.

## Quality

Expected-dimension hits are sparse evidence signals, not file-level recall. Clean priority-free
rate is not false-positive precision without manual adjudication.

| Evaluator | Success | Expected priority hit | Clean priority-free |
|---|---:|---:|---:|
| Jev | 100.0% | 9.1% | 0.0% |
| DSPy + OpenCode Go GLM 5.3 Flash | 100.0% | 90.9% | 0.0% |

## Efficiency

| Evaluator | Median latency | Median input tokens | Median output tokens | Total tokens | Median cost | Total cost |
|---|---:|---:|---:|---:|---:|---:|
| Jev | 1.200 s | 10,504 | 2,026 | 125,180 | $0.000441 | $0.004406 |
| DSPy + OpenCode Go GLM 5.3 Flash | 26.799 s | 11,349 | 924 | 129,512 | $0.002168 | $0.024468 |

## Cost Basis

- Jev uses TypeSafe's published direct API rate of `$0.042/M` input tokens with free output.
- OpenCode Go is subscription-billed. Its dollar figures are token-equivalent reference estimates
  using the published GLM 5.3 Flash rates, not marginal OpenCode Go invoice charges.

## Agreement With Jev

| Evaluator | Paired runs | Applicability agreement | Score MAE | Priority Jaccard |
|---|---:|---:|---:|---:|
| DSPy + OpenCode Go GLM 5.3 Flash | 10 | 44.2% | 1.485 | 0.103 |

The pilot is too small for broad model-quality claims. All disagreements require evidence-backed
manual adjudication before reporting recall, precision, or clean-case false-positive rates.
