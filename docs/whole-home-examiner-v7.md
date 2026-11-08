# External examiner v7: original journal reconstruction

This explicit pre-formal correction preserves v6 source, tests, failures and
freeze. No candidate result was queried. Static source review found that frozen
network 0ed9 reports a contact **summary** (`passed`, `record_count`, `errors`,
`scope`), while the external helpers require the original complete journal
(`passed`, `records`, `errors`, `scope`). Treating the summary as the journal
would raise an error. Earlier synthetic unit/regression passes did not exercise
this real report shape and are not evidence of file-level integration success.

V7 changes only this file-level orchestration. After unchanged stock file
verification and complete original locked-data reading, it reconstructs one
`p.contact_journal(original_run, original_spec)`. It requires exact supported
inventories/types, a valid original journal, and equality of its exact summary
projection with the untouched stock summary. All fields must match. No aggregate
record is invented. Missing early-failure summaries or disagreements produce an
explicit failed result preserving the complete stock report; they never gain
acceptance. The same full journal object is passed to auxiliary, cart, composed
mechanism and bridge helpers. No extra raw run is retained across suite runs.

The explicit schemas are `simscene.whole_home_fidelity.v5` and
`simscene.whole_home_suite.v5`, orchestration version 7. The separately frozen
composition helper d6ba5b is byte unchanged. Every v6 physical helper function
and exact composition inventory/DAG/activation-window predicate is unchanged.
The stock kernel, installed v41, all 105 source/1080 installed files, ce05,
structural-load helper, old cases, source scenes and physical thresholds remain
unchanged. All original 200/final60-degree, six transmitting categories,
50/45/.85/2 activity, three controls, strict t0, 121-sample **and** actual
2-second hold, whole cube, variant, repeat, replay and native-video requirements
remain. See the frozen v6 policy for the complete composition and control scope.

Regression covers a real stock-summary shape with actual synthetic per-step
callbacks, one original reader invocation, original run/spec object identity,
the same journal object delivered to all four helper paths, unchanged raw P1 and
stock reports, absent/mismatched summary fields, unknown/type changes, invalid
original callbacks and durable failed results. Custody and the stock pass in
the orchestration fixture are explicitly mocked; it is not house physics proof.

`bounded_entry_clock_v4.py` pins this new authority and accepts only an
independently retained orchestration-7 full positive report. Its schema is
`simscene.bounded_entry_clock.v4`. Geometry, exact inclusion theorem, original
mask prefix metrics, all four unchanged timing floors, first entry/noescape and
mandatory observed-bound collapse are identical to clock v3; only report pin,
schema/version checks and stability-authority label change. Old clocks remain
immutable. No new local timestamps, reports or self-computed lock hashes count
as independent custody anchors.

Freeze these new generic files before actual candidate runtime queries; freeze
the independently reviewed static case/contracts before any formal snapshot.
This change does not authorize publication or assert any P3/P4 success.
