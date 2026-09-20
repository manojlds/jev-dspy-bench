# Jev categorical-verdict protocol experiment

- Run date: 2026-09-20
- Cases: 20 labeled expansion train/development cases
- Repeats: 5 per case (100 successful evaluations)
- Model: pinned `jev-1.13.0`
- Corpus SHA-256: `c8662ecdd98bff50ad33cae2bf4d1a6a6715389b0d9ff4c54eaff0bea2895aac`
- Categorical rubric SHA-256: `e05c3fdce672ae576b0a081ffe941df1b718c4e201a14b38dfc6a6f9e56ae474`
- Raw artifact SHA-256: `6a3180432f39082476b17cfcea1be550aec0dbd45f694073c7edac59828117d7`

This experiment tests one protocol change suggested by TypeSafe's Jev 1.13 guidance: ask for
the annotated verdict directly as a Choice (`weak`, `acceptable`, or `not_applicable`) instead of
deriving it from an applicability Noul and a 1–10 Score. The canonical state, 19 dimensions, and
frozen output-independent references are unchanged. Weakness choices remain separate.

## Result

Direct categorical judgments dramatically reduced the original protocol's over-flagging, but also
missed more true weak dimensions. The apparent increase in the existing aggregate reference score
is mostly label-imbalance inflation, not a 45-point model-quality gain.

| Evaluator/protocol | Reference score | Dimension agreement | Balanced dimension agreement | Weak detection | Acceptable agreement | Not-applicable agreement | Priority F1 | Clean priority-free |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Jev original Score protocol, 1 run | 21.6% | 22.4% | 48.9% | **55.8%** | 5.7% | **85.1%** | 15.9% | 0.0% |
| Jev categorical protocol, 5-run mean | **67.0%** | 72.3% | **53.9%** | 26.5% | 84.4% | 50.6% | 27.8% | 30.0% |
| Deterministic always-acceptable baseline | 66.7% | **73.9%** | 33.3% | 0.0% | **100.0%** | 0.0% | **50.0%** | **100.0%** |

Balanced dimension agreement is the macro-average of recall for the three verdict classes. It is
included because ordinary dimension agreement is dominated by `acceptable` labels. The categorical
protocol improves this balanced measure by 5.0 percentage points over the original Jev protocol and
by 20.5 points over the trivial baseline, but its weak-dimension recall is 29.2 points lower than the
original protocol.

Across all five categorical repeats, the label confusion counts were:

| Frozen label | Predicted weak | Predicted acceptable | Predicted not applicable |
|---|---:|---:|---:|
| Weak | 69 | 166 | 25 |
| Acceptable | 118 | 1,182 | 100 |
| Not applicable | 5 | 111 | 119 |

## Repeat stability

- Per-repeat reference score ranged from 65.7% to 68.6%.
- Five of 20 cases (25.0%) changed priority sets across repeats.
- Seven of 380 case-dimension pairs (1.8%) changed applicability verdict across repeats.
- All 100 API evaluations succeeded.

## Efficiency

Compared with the original one-run Jev baseline, the categorical protocol used fewer input tokens
and was faster per evaluation because it asks 38 questions instead of 57.

| Protocol | Median latency | Median input tokens | Median output tokens | Median estimated cost |
|---|---:|---:|---:|---:|
| Original Score protocol | 1.344 s | 11,774 | 2,026 | $0.000495 |
| Categorical protocol | **0.321 s** | **8,296** | 2,122 | **$0.000348** |

Output tokens are free under the published TypeSafe rate. Total categorical experiment cost was
approximately `$0.036695` for 100 evaluations.

## Conclusion

The categorical protocol is operationally better: it is faster, cheaper, materially less prone to
flag every clean case, and modestly better on class-balanced verdict agreement. It should not yet
replace the benchmark protocol, because its gain on the existing reference score is nearly matched
by an always-acceptable classifier and it substantially reduces weak-dimension recall.

Before optimization or a categorical Jev-vs-DSPy comparison, the training metric should be revised
to resist class imbalance. At minimum, report balanced verdict agreement, weak recall, defect-case
priority F1, and clean specificity separately. The untouched 10-case holdout must remain unused
while making that metric decision.
