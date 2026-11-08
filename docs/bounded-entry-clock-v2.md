# Bounded entry clock v2

`experiments/bounded_entry_clock_v2.py` is the separately frozen successor to
v1. It accepts `simscene.bounded_entry_clock.v2` and requires a retained full
v5 fidelity report (orchestration version 5) and its exact frozen code hash.
Frozen v1 remains unchanged and continues to require its original v4 report.
The inner/outer geometry contracts retain
`simscene.box_halfspace_observation.v2`; the frozen v41 reader, strict clock,
all source/evidence locks and actual physical/geometry kernels are unchanged.

All geometry, volume inclusion, earliest-entry, original-mask/prefix metrics,
floor comparisons and collapsed-bound/noescape predicates are identical to v1.
Tests compare complete function ASTs; the evaluation function differs only in
the displayed stability-authority version label. Report-version/hash checks
explicitly require v5 rather than silently reinterpreting a v4 report. The only
reason for this new report authority is v5's narrow recognition of canonical
USD joint breaking-threshold defaults; see
[whole-home-examiner-v5.md](whole-home-examiner-v5.md).

The [complete v1 contract/custody/CLI description](bounded-entry-clock.md)
continues to apply, with the new executable/schema and v5 report substituted.
The original accepted report hash and original run/evidence lock anchors must
come from independently retained verifier records, never fresh hashes made
merely to fill arguments. Static case/inner/outer/clock/review/code files must
be frozen before the original formal job snapshot.

`I ⊆ physical cavity ⊆ O`, exact `B ⊆ I ⊆ O`, every original corner/step,
every possible original prefix endpoint, unchanged 50/45/.85/2 floors and strict
`first_inner ≤ stock_end` coverage remain mandatory. Timing-only success does
not complete physical entry/noescape scope: observed bounds must collapse and
the earliest inner membership must never later exit. No alternate transit
proof is implemented. Stability, between-step continuity, full-suite physics
and delivery acceptance are not inferred; `formal_house_accepted` stays false.

Memory ordering is unchanged: reduce/release the full retained report before
loading the single full original run. V1's 7,800-step varying3D 26+6-plane
benchmark and resource-audit limitations remain relevant by identical geometry/
prefix code, not as a newly measured whole-house memory guarantee. New v2
file-custody and fresh-process CLI fixtures exercise the new report identity.
There are no GPU jobs, runtime actuation or candidate outcomes in these tests.
