# Jev vs Frozen Reference Audit

Date: 2026-09-20  
Study: `4516d4754764`  
Run: `jev-vs-dspy-glm-5.3-flash-20260920T104253Z-704d607d.json`  
Reference annotator: `opencode-agent`

## Method

All ten output-independent reference judgments were submitted and frozen before evaluator outputs
were inspected. The existing successful Jev results from the pilot were then compared with each
frozen reference. Material disagreements were rechecked against the canonical patch, case metadata,
historical evidence, and rubric semantics. No evaluator was rerun.

## Results

| Case | Frozen reference | Jev disagreement | Recheck |
| --- | --- | --- | --- |
| `q7m4-x2` | Material issue | Jev marks correctness, reliability, and test quality not applicable; its priorities are generic low-severity concerns. | Reference confirmed. Mutation of the serialized activity input cannot update workflow-owned context. |
| `n8v2-k6` | Material issue | Jev marks every dimension not applicable and emits no priorities. | Reference confirmed. Removing the mode guards allows overlapping commit paths in internal fix mode. |
| `h3d7-w5` | Material issue | Jev identifies reliability but misses correctness, compatibility, abstraction quality, and test quality. | Reference confirmed. The fallback accepts an unknown workflow and bypasses its input contract. |
| `t6a1-j8` | Material issue | Jev identifies security and reliability but misses correctness, abstraction quality, and test quality; its readability concern is unsupported. | Reference confirmed. Removing canonical ID validation permits path traversal outside the artifact directory. |
| `b4l8-s3` | Material issue | Jev misses correctness, reliability, test quality, and repeated-work concerns, while raising peripheral generic priorities. | Reference confirmed. Loop back-edges reactivate completed prerequisites and can repeat side effects. |
| `f2y6-m9` | Material issue | Jev misses every frozen priority and substitutes generic maintainability, readability, and complexity concerns. | Reference confirmed. The parser reverses precedence, mishandles nesting and quotes, and can recurse indefinitely. |
| `x5j1-r7` | Clean | Jev raises unsupported low-severity compatibility, abstraction, modularity, and readability priorities. | Reference confirmed. The extraction preserves behavior and creates an intentional execution boundary. |
| `u2k7-d5` | Clean | Jev raises unsupported low-severity state, observability, reliability, and maintainability concerns. | Reference confirmed. State transitions are deterministic, terminal state is recorded, and cleanup occurs in `finally`. |
| `l8q3-v9` | Clean | Jev raises a medium observability concern plus speculative maintenance and coupling concerns. | Reference confirmed. Trace writing is opt-in, awaited, failure-propagating, and returns its explicit artifact contract. |
| `p3w8-h2` | Clean | Jev manufactures five low priorities despite its own acceptable-to-strong scores and null issue lists. | Reference confirmed. The new control kind is consistently added to types, validation, transition logic, and configuration. |

## Conclusion

All ten frozen references remain supported after rechecking their disagreements with Jev. No
correction record is required. Jev's strongest result is the path-traversal case, where it identifies
the principal security and reliability risks. Its main failure mode in this pilot is treating
behaviorally assessable dimensions as not applicable while prioritizing generic structural concerns;
on the four clean controls, those generic priorities become false alarms.
