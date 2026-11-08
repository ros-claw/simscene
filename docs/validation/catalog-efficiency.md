# Catalog efficiency: measured results and limits

The frozen six-task study completed **36 independent sessions** on
`gpt-6.1-sol`, reasoning effort `medium`, Codex CLI 0.166.0. It did **not**
establish token savings or a time advantage. The four strictly passing
common-task pairs had a median candidate/baseline token ratio of **1.1201**.
Quality was unequal across all trials, so similar aggregate token totals are
not evidence of equivalent-cost success. The 30% reduction in the design remains
an unproven optimization target.

These results compare legacy v44
`a36d2b272cd7d64b739a9d3ebc4d9a761323aafd` with V2 candidate
[`599a90e`](https://github.com/ros-claw/simscene/commit/599a90edb6197fa5ec19f6022907416f276effd7).
The final preview includes later capture and audit fixes; these old measurements
are **not** an efficiency certification for that later package.

## Success before cost

| Task, three sessions per version | Baseline strict result | Candidate strict result | All reported tokens: baseline / candidate |
|---|---|---|---|
| Native USD layout | 3 pass | 2 pass, 1 support-height failure | 1,664,132 / 1,790,512 |
| Warm 20 mm edit | 3 pass | 2 pass, 1 audit failure | 1,504,858 / 1,511,820 |
| Native five-second video | 3 fail | 3 fail | 2,308,904 / 2,173,100 |
| Imported GLB rigid body | 3 capability gaps | 2 pass, 1 settling failure | 571,186 / 2,731,773 |
| Native articulated asset | 2 capability gaps, 1 audit failure | 3 pass | 558,884 / 1,878,167 |
| Generated module | 3 capability gaps | 3 pass | 379,699 / 2,795,590 |

Every row includes failed attempts. Group A strict passes were 6/9 baseline and
4/9 candidate. Group B candidate passes were 8/9. The host independently
verified missing baseline capabilities in all nine Group B sessions, including
one whose strict status remained failed because of the audit. Unsupported
capabilities are neither zero-token successes nor 100% savings. Group B has no
efficiency ratio. Total reported input plus output across the 36 sessions was
19,868,625 tokens. Cached input and reasoning are subsets, not extra buckets.

The [public result JSON](../../examples/catalog_benchmark/results/catalog-efficiency-results.json)
contains all trial statuses, input/cache/output/reasoning counters, wall times,
MCP calls, returned bytes, failed checks and trace hashes. It also retains the
four valid pilot sessions and earlier stopped collection costs separately.
One earlier timeout has unknown usage; it is not filled with zero or pooled
into the valid comparison. Monetary billing is unmeasured.

## Problems found and corrected

The frozen heuristic misclassified an own-task relative glob and literal `rg`
exclusion options as outside reads. Four original rows retain their original
strict failures and costs. A separate [immutable-trace audit](../../examples/catalog_benchmark/results/catalog-efficiency-scope-audit.json)
clears those findings without changing physical predicates, usage or original
verdicts. Its outcome is not substituted into the primary ratios. Independent
host quality checks passed 7/9 baseline and 5/9 candidate Group A sessions.

One baseline video passed the independent image check but had that audit
failure. The other five videos failed the frozen per-frame visibility test.
Inspection of candidate raw frames found a real capture timing defect: some
nonempty RGB buffers represented the preceding captured physical frame. At
frame 25, the red sphere centroid matched step 50 while the manifest labelled
step 52. A correct frame count alone had not established pixel/pose alignment.

The final worker pauses physics, flushes rendering once per due camera batch,
checks unchanged physical step/time and then reads RGB. `video_inspect` reports
barrier receipts separately from nominal cadence. Three new SDK runs passed
**450/450 native frames** and all original 720-step physical predicates under
the unchanged checker. See [capture validation](../../examples/catalog_benchmark/results/capture-sync-validation.json).
These are new machine-driven validation runs, not additional model comparisons.
Older clips without the receipt remain marked `unrecorded`; their nominal
source clocks are not silently recertified.

## Protocol and reproducibility

The [protocol](../../examples/catalog_benchmark/protocol.json),
[tasks](../../examples/catalog_benchmark/tasks.json), and
[exact declarative inputs](../../examples/catalog_benchmark/frozen-inputs/manifest.json)
are public. Selected model payloads, cache seeds, private bindings and raw
client sessions are excluded. The [benchmark guide](../../examples/catalog_benchmark/README.md)
describes the required staged dependencies and commands. The legacy comparison
package is distributed separately with the preview release; its historical
source identifier is not a public Git commit to archive.

Each version/task/repetition used a fresh session, private state and equivalent
staged source access. Warm tasks copied the same seed inventory. Both versions
used CPU PhysX, 60 Hz, seed 42 and the same hardware/runtime identity. This was
not an all-source cold-download experiment. The host verified actual source
hashes, every saved physics step and native/decoded video pixels. Agent prose
and agent-supplied pass flags did not establish success.

A four-session pilot preceded expansion and its reviewed report hash was pinned.
Full sessions had 420 seconds, 2,000,000 reported input-plus-output tokens and
16,000 output tokens each; no automatic retry replaced a row. Usage limits act
on observed completed turns, so an in-flight request can exceed them. They are
not hard provider billing caps. The fixed task repetitions were completed; no
extra video attempts were added to improve the original score. Subsequent
repairs and release qualification are separate evidence.

Complete all-attempt transfer bytes, GPU/model-wait phase telemetry and billing
were unavailable and remain null. Known download subtotals do not establish
zero traffic. Setup and host-verifier time are recorded separately from client
wall time. Earlier client-context and proxy-forwarding collection failures are
retained as stopped cohorts, not relabelled as plugin capability failures.

Three repetitions on one shared GPU host, fixed tasks and one model alias cannot
establish unfamiliar-user generalization. Physical quality comes first; this
study supports added capabilities and identifies repair work, while a
cross-task token advantage remains unproven.
