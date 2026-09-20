# Laya categorical native-context diagnostic

- Run date: 2026-09-20
- Cases: 20 labeled expansion train/development cases (10 defect, 10 clean)
- Runs: one deterministic CPU run per checkpoint and case
- Laya package: `0.3.4`
- Model revision: `1c5edc17a7acd8701df6fc341c0d179f1c62c982`
- Checkpoints: base English and `typed-decisions`
- License: Apache-2.0
- Corpus SHA-256: `c8662ecdd98bff50ad33cae2bf4d1a6a6715389b0d9ff4c54eaff0bea2895aac`
- Categorical rubric SHA-256: `e05c3fdce672ae576b0a081ffe941df1b718c4e201a14b38dfc6a6f9e56ae474`
- Raw artifact SHA-256: `da65df06009a5f9bcfc6a0b5bca946f33e0c822ce0ade788f30fcaafae6de742`

This evaluates open-weight Laya with the same 19 direct categorical verdict questions used in the
Jev categorical experiment. Canonical states and frozen references are unchanged. It is a
**native-context diagnostic**, not an apples-to-apples full-context comparison: Laya truncates state
to fit each checkpoint's native sequence budget, whereas Jev received every complete state.

## Result

Both checkpoints completed all 20 cases, but neither demonstrated useful zero-shot code-review
judgment. Both behaved mostly like an `acceptable` classifier and detected only 2 of 52 frozen weak
dimension labels.

| Evaluator/protocol | Reference score | Dimension agreement | Balanced dimension agreement | Weak detection | Acceptable agreement | Not-applicable agreement | Priority F1 | Clean priority-free |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Laya base, native context | 61.1% | 69.1% | 32.2% | 3.8% | 92.9% | 0.0% | 37.5% | 70.0% |
| Laya `typed-decisions`, native context | 55.8% | 66.5% | 31.0% | 3.8% | 89.3% | 0.0% | 21.0% | 40.0% |
| Jev categorical, full context, 5-run mean | **67.0%** | 72.3% | **53.9%** | **26.5%** | 84.4% | **50.6%** | 27.8% | 30.0% |
| Deterministic always-acceptable baseline | 66.7% | **73.9%** | 33.3% | 0.0% | **100.0%** | 0.0% | **50.0%** | **100.0%** |

The base checkpoint's ordinary reference score is 5.6 points below the trivial baseline, and its
balanced dimension agreement is 1.1 points below it. `typed-decisions` performs worse despite its
larger context. Its published specialization targets four non-code-review workflows, so this result
does not contradict its in-domain benchmark.

Mean reference score by case disposition:

| Checkpoint | Defect cases | Clean cases |
|---|---:|---:|
| Laya base | 42.3% | 80.0% |
| Laya `typed-decisions` | 41.7% | 69.9% |

The much higher clean score reflects conservative `acceptable` predictions rather than reliable
three-class discrimination.

## Native context limitation

The base checkpoint uses a 512-token sequence and retained a median 22.2% of canonical state tokens;
only 1 of 20 cases fit completely. `typed-decisions` uses 1,024 tokens and retained a median 52.9%;
only 3 cases fit completely.

| Checkpoint | Minimum retained | Median retained | Maximum retained | Cases fully retained |
|---|---:|---:|---:|---:|
| Laya base | 5.6% | 22.2% | 100.0% | 1/20 |
| Laya `typed-decisions` | 13.3% | 52.9% | 100.0% | 3/20 |

Raw states ranged from 351 to 6,637 Laya tokens. The model keeps the beginning of each serialized
state, so truncation can omit later diff or repository context. A future full-context experiment
would need validated longer-sequence settings or deterministic chunking and aggregation; either is a
new protocol and must be reported separately.

## CPU efficiency on this desktop

Hardware was an AMD Ryzen 5 7600 with 30 GiB RAM. A 38-question smoke test peaked at approximately
4.1 GiB resident memory. The installed AMD Radeon RX 9070-family GPU was not used because ROCm
PyTorch was not installed.

| Checkpoint | Median latency per case | Median processed input tokens | Output tokens | Provider cost |
|---|---:|---:|---:|---:|
| Laya base | 31.35 s | 19,456 | 0 | $0 |
| Laya `typed-decisions` | 67.20 s | 38,912 | 0 | $0 |

Processed input tokens sum all 38 independently encoded question sequences, so they are not directly
comparable with Jev API billing tokens. Self-hosting has no provider charge but still uses local
hardware and electricity.

## Conclusion

Laya runs locally and its typed interface is straightforward to integrate. At native context and
without code-review fine-tuning, however, it does not beat a trivial baseline and misses 96.2% of
weak dimension labels. It should not be presented as an open-source Jev replacement for this task
based on the current result.

Promising follow-ups are GPU enablement, a pre-registered chunking protocol, and training Laya on the
expansion train partition. The untouched 10-case holdout must remain unused until those choices are
frozen.
