# Original independent examination custody, version 1

`experiments/independent_examiner_custody.py` prepares the next formal version's
original independent examinations. It never starts a simulation, edits a scene,
changes a case, substitutes a physics report or changes any f7/clock4 predicate.
No actual report was queried while this wrapper and its synthetic tests were
prepared. Its generic freeze must precede the **original formal snapshot**;
old CASE1 cannot be converted retrospectively. Its failed original examination
and blocked clock stay preserved.

The unchanged authorities remain installed v41, original full f7 and clock4.
The retained-reader and retained-suite freezes provide only accepted-reference
byte-closure and clock-custody checks. The wrapper does not assert P3/P4 delivery
acceptance, even when one original examination passes. Do not use it until the
independent new static bindings and explicit formal release exist.

## Read-only review of retained aggregation v1

The independently reviewed retained-suite source SHA is
`3d81f7fa13fc58f1bf0877e3be5feee51ef8e019503317683074ef4599d4ff70`;
its root joint freeze SHA is
`49e59c434bdb6a3af181e2395372fb62a37258037b405dc9e869ff28363e7f17`.
The review found no defect requiring a new aggregator version. It retains direct
original function identities and the literal original final-gate AST block,
eight complete original accepted reports, all five original clock4 certificates,
input/output/source/asset closures, original mask prefix checks, exact allowed
variant changes, all thirteen runtime fields, chronology/inventory, native video
and distinct editable replay. The full stock CSV remains unchanged; the physical
CSV is its byte-identical prefix and the original user clock must agree with the
original clock4 prefix metrics. This review queried source/tests/freeze only,
never candidate reports. The root's 701-test CPU result is generic regression,
not acceptance evidence for a candidate.

## Invocation configuration

Use a separate independently pinned JSON file for each original evaluation. Its
SHA is recorded in the owned invocation/launch record, not silently refreshed if
the file changes. Schema `simscene.independent_examiner_invocation.v1` has exactly:

```text
schema mode role run_directory contract_path static_review_path freeze_path
software_freeze_path output_directory additional_files reference bounded_clock
custody_freeze
```

All paths are absolute local paths with no symlink traversal. `mode` is the
original positive/no_trigger/broken_rope/locked_door mode. Positive `role` is the
independently recorded main_positive_1/main_positive_2/main_positive_3/variant/
replay role. A control's role equals its mode. The output directory must be new
and outside every sealed-run subtree, including the current and reference runs.

`custody_freeze` is `{path, sha256}` for this wrapper's independent generic
manifest. It pins this source and all original orchestration dependencies. Its
timestamp must precede the original run-lock snapshot. `additional_files`
contains the explicitly frozen additional dependencies, such as a variant
declaration. All old bindings remain immutable; do not point a new invocation
at a modified old case.

For a positive, `reference` is null and `bounded_clock` is exactly:

```text
{case_path, inner_path, outer_path, contract_path, review_path, freeze_path}
```

These are the six independently predeclared clock4 paths. For a stopping
control, `bounded_clock` is null and `reference` is exactly:

```json
{
  "run_directory": "/ABS/prior-main1-original-run",
  "examination_record": {
    "receipt_path": "/ABS/prior-main1/independent-full-report-receipt.json",
    "receipt_sha256": "PRIOR_INDEPENDENT_LEDGER_SHA"
  },
  "clock_certificate": {
    "path": "/ABS/prior-main1/clock4/certificate.json",
    "sha256": "PRIOR_INDEPENDENT_CLOCK_LEDGER_SHA"
  }
}
```

All expected hashes must come from the **already retained independent** ledger,
complete report/receipt and complete clock certificate. Never hash arbitrary
current files just to fill an expected-hash argument. The accepted reference
must be the same version's `main_positive_1`; a later repeat, variant, failed
positive, root metadata inventory or a self-reference is insufficient. The
reference's full report and original run/evidence/result anchors are taken from
that prior receipt/report, then revalidated against the original bytes.

## Original f7 phase

Run only after the named original formal run has a complete nonpartial seal and
the preceding original decisions permit this step:

```bash
custody_worktree=/home/dell/simscene-worktrees/filtered-geometry-measure
PYTHONPATH="$custody_worktree/src" /home/dell/.local/share/simscene/venv-v31/bin/python \
  "$custody_worktree/experiments/independent_examiner_custody.py" evaluate \
  --config /ABS/independent-invocation.json \
  --config-sha256 PINNED_INVOCATION_SHA
```

This is a potentially long CPU invocation. Use an owned detached subprocess
supervisor with `start_new_session=True`, a separate owned stdout/stderr log,
recorded PID/start, exact invocation/config hashes and durable exit/RSS receipt.
Do not let an ordinary interactive tool-session timeout terminate it. Check the
recorded PID before recovery; do not run duplicate full examinations. A CPU
interruption is not a new physics run or permission to relabel/retry physics.
Choose a fresh output directory for any necessary CPU recovery, retaining the
interrupted invocation/partial outputs.

Before original f7, the wrapper checks every pinned custody/prejob dependency,
the entire installed/source software freeze, all actual snapshotted worker
package hashes, original input/asset/runtime closure, and all originally locked
output bytes. The pre-evaluation output check is prospective consistency, not
an accepted enumeration or physical decision: the full original f7 always runs
and proves its own complete evidence and all physical predicates.

For a control, before calling f7 it additionally:

1. Fully revalidates the already accepted MAIN1's original independent receipt,
   report and closed bytes through the frozen retained reader.
2. Validates its complete original clock4 and all static/source/mask provenance
   through the frozen retained-suite clock function, without changing masks.
3. Releases the full reference report, retaining only bounded identity/proof
   metadata.
4. Exclusively and durably writes `reference-before-proof.json` and the exact
   `simscene.independent_reference_prebinding.v1` file. Its anchors come from the
   prior independently retained receipt/report/clock, not fresh root metadata.
5. Writes `evaluation-start.json` after the prebinding, then calls unchanged
   `f7.verify_one` with the exact original control mode and reference directory.

After f7, it first preserves the **complete original returned report**, including
failure, using original `save_run_report`. It checks the same current/source/
locked closure again. A control also fully revalidates the identical accepted
reference and its clock again, records `reference-after-proof.json`, and requires
all original reference identities and prebinding bytes to remain identical.

Only then does it publish the original independent receipt atomically and
exclusively. Positive receipts use v1; control receipts use v2 with original
evaluation start, prebinding and unchanged postcheck. The exact schemas match
the frozen retained-integrity protocol. Controls never acquire a positive clock.
A failed positive receipt keeps `accepted_for_clock_query=false`. The receipt
always keeps `P3_accepted=false` and `P4_accepted=false`.

Finally it atomically publishes `examination-record.json` containing exactly
`{receipt_path, receipt_sha256}`, and `evaluation-complete.json`. The examiner
must retain that record's identity in the independent chronological ledger
**before** a separate clock query. No old control receipt is rewritten or given
a retrospective reference proof. Once the examination directory exists,
dependency changes or exceptions preserve a durable failed execution diagnostic
and any original returned full report; earlier preflight rejections remain in
the owned launch log/exit receipt. Neither can publish an accepted examination
record.

## Separate original clock4 phase

Only a positive with an already retained accepted original f7 receipt can enter
this phase. The record identity is read from the retained independent ledger,
not freshly manufactured from a proposed receipt:

```bash
PYTHONPATH="$custody_worktree/src" /home/dell/.local/share/simscene/venv-v31/bin/python \
  "$custody_worktree/experiments/independent_examiner_custody.py" clock \
  --config /ABS/independent-invocation.json \
  --config-sha256 PINNED_INVOCATION_SHA \
  --record /ABS/examination-record.json \
  --record-sha256 PRIOR_RETAINED_RECORD_FILE_SHA
```

Use the same durable supervision rules. This invocation rechecks original
custody and closure, then calls unchanged original clock4 once on the **full
original unsliced run**. Its full-report/run-lock/evidence-lock arguments come
only from the already retained independent receipt. It does not rebase,
interpolate, retime, alter flags or substitute a later entry.

It preserves the complete original certificate at `clock4/certificate.json`,
rechecks dependencies and receipt/report bytes, then records a separate
`clock-custody-receipt.json`. Failure remains failure; no later-entry substitute
or automatic retry exists. Retain the resulting original certificate identity
in the independent ledger before it can serve as a future control reference.

Further formal starts remain manually gated on **both** original f7 acceptance
and complete original clock4 acceptance. Keep the kit's order: three main runs,
three controls, variant, distinct full editable-project replay. The frozen
full-suite or explicitly named retained-report aggregation still performs all
final eight-run gates. A clock or an individual positive alone does not release
the complete delivery. Preserve a global all-version index including original
CASE1 failure; use a separate exact-case attempt ledger for the new case.

## Tests and limits

Synthetic tests verify exact full-report bytes, positive v1/control v2 receipts,
prebinding-before-original-call ordering, original anchor use, complete before/
after reference revalidation, missing/failed references, changed current or
reference dependencies, strict separate clock gating, exception retention,
exclusive output publication and rejection of post-snapshot custody versions.
They explicitly mock the tiny fixture's physical contract validator, the
expensive original f7 call and reference geometry-clock decision; real original
byte closure and original report serialization run. No synthetic fixture is
claimed as P3 evidence, and production exposes no bypass.

All reader budgets, supported JSON case scope and trust limitations are those
of the unchanged retained-integrity v1. Local recorded chronology is not an
external timestamp signature. No GPU, task actuation, physical source change,
scene coordinate selection or old-case modification is part of this tool.
