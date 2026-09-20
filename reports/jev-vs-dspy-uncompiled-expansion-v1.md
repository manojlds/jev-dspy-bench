# Jev vs unoptimized DSPy: expanded baseline

- Run date: 2026-09-20
- Cases: 20 labeled historical DRS cases (14 train, 6 development; 10 defect, 10 clean)
- Runs: one per evaluator and case
- Jev transport: direct TypeSafe API
- DSPy transport: OpenCode Go, `opencode-go/glm-5.3-flash`
- DSPy optimization: none
- Corpus SHA-256: `c8662ecdd98bff50ad33cae2bf4d1a6a6715389b0d9ff4c54eaff0bea2895aac`
- Raw artifact SHA-256: `8e396d6fc4fbd7be7e71d80bff85680eeb17f906cf6a9a6f11a4ffc4d2e855ae`
- Adjudication study: `8e396d6fc4fb`

Only canonical prepared state content was shared exactly; provider request framing differed. Expected
findings, evidence, and references were excluded from evaluator input. The full 19-dimension
references were frozen before evaluator outputs were generated.

## Result

Unoptimized DSPy agreed more closely with the frozen references overall, while Jev was substantially
faster and cheaper. Both systems produced at least one priority on every clean control, so neither
demonstrated clean-case specificity in this run.

| Evaluator | Success | Reference score | Dimension agreement | Weak detection | Acceptable agreement | Not-applicable agreement | Priority F1 | Clean priority-free |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev | 100.0% | 21.6% | 22.4% | 55.8% | 5.7% | **85.1%** | 15.9% | 0.0% |
| DSPy + OpenCode Go GLM 5.3 Flash | 100.0% | **40.7%** | **48.3%** | **59.6%** | **45.4%** | 53.2% | **18.3%** | 0.0% |

The reference score is the optimizer metric: 70% full dimension-verdict agreement and 30% priority
set F1. `uncertain` reference dimensions are excluded. DSPy led by 19.1 percentage points on this
metric. Most of that difference came from acceptable-dimension agreement; Jev was better at matching
`not_applicable` labels. Scores remained low in absolute terms, especially priority F1.

The mean reference score split by case disposition was:

| Evaluator | Defect cases | Clean cases |
|---|---:|---:|
| Jev | 29.4% | 13.8% |
| DSPy + OpenCode Go GLM 5.3 Flash | 39.4% | 42.1% |

## Efficiency

| Evaluator | Median latency | Median input tokens | Median output tokens | Total tokens | Median cost | Total cost |
|---|---:|---:|---:|---:|---:|---:|
| Jev | **1.344 s** | **11,774** | 2,026 | **284,883** | **$0.000495** | **$0.010261** |
| DSPy + OpenCode Go GLM 5.3 Flash | 17.638 s | 17,129 | **910** | 382,627 | $0.002984 | $0.063729 |

Jev had 13.1 times lower median latency and was 6.2 times cheaper on the stated cost basis. Jev uses
TypeSafe's published direct API rate of `$0.042/M` input tokens with free output. OpenCode Go is
subscription-billed, so its dollar figures are token-equivalent estimates using published GLM 5.3
Flash rates, not marginal invoice charges.

## Evaluator agreement

| Paired runs | Applicability agreement | Score MAE | Priority Jaccard |
|---:|---:|---:|---:|
| 20 | 61.8% | 0.616 | 0.204 |

This measures similarity between evaluators, not correctness.

## Interpretation limits

- These 20 cases are the labeled expansion train/development set, not the untouched holdout.
- All cases come from one TypeScript repository, limiting external validity.
- There was only one successful run per case, so stability is not measured.
- Frozen-reference agreement is complete, but blinded pairwise preference adjudication for study
  `8e396d6fc4fb` remains unstarted and is not claimed here.
- The result supports early optimization experiments, not broad model-quality claims.
