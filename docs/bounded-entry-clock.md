# Bounded entry clock, additive v1

`experiments/bounded_entry_clock.py` is an external, read-only supplement. It
does not change v41, ce05, v4, any old geometry helper, a case, a mask or a
simulation. Its public schema is `simscene.bounded_entry_clock.v1`. Generic
code/tests/policy must be frozen before candidate queries; the actual case,
inner/outer geometry, static review and contract must be independently bound
and chronologically frozen before formal snapshots.

Let `I` be a certified collision-free subregion inside the receiver's declared
physical cavity `C`, and `O` a necessary outer enclosure, with independently
proved static premises `I ⊆ C ⊆ O`. The declared stock receiver region `B` must
be an inward-certified subset of `I`. These premises are not established merely
by an AABB, an asset name, a successful entry, or this program.

At original recorded boundaries, earliest whole-box memberships obey
`E_O ≤ E_C ≤ E_I`. The original accepted stock mask ends at `S`; the program
requires `E_I ≤ S`, without extending that mask. For **every** integer endpoint
in `[E_O,E_I]`, it tests the exact original prefix `[release,endpoint)` against
the same case limits: span at least 50 seconds, net purposeful union activity
at least 45 seconds, occupancy at least .85 and maximum idle at most two seconds.
Stricter original case floors remain unchanged and must match the new contract.
No original flag is reclassified, synthesized, added, moved or credited twice.
Checking only the two endpoint clocks is insufficient: occupancy can fail at an
intermediate endpoint while both bounding endpoints pass.

The result separates these verdicts:

* `geometry_queries_complete`: all required original boundaries/corners queried.
* `bounded_timing_floors_passed`: every possible original prefix meets every floor.
* `physical_entry_no_escape_complete`: the observed bounds collapse to one
  step, and the earliest inner membership has no later exit in any original
  sample. An unknown early entry followed by escape/reentry is never replaced
  by a later convenient entry.
* `supplemental_complete`: timing and the collapsed entry/no-escape scope both
  pass. Noncollapsed bounds never complete this supplement, even if all timing
  prefixes pass. No transit-proof exception is implemented in this version.

These statements concern original recorded boundaries, not unobserved motion
between frames. Stability is not inferred from membership. The unchanged stock
and v4 reports remain responsible for all passive physics, causality, terminal
hold/stability, 200 final tips, semantic categories, controls and full-suite
acceptance. `formal_house_accepted` is always false here. A full delivery still
requires the original suite and this stronger supplement, not substitution.

## Geometry and static review

The inner and outer declarations use the unchanged
`simscene.box_halfspace_observation.v2` contract, including exact box/receiver
root configuration hashes, actual box size, case bytes, timestep, static-review
hash and 4–32 finite unit-normal halfspaces each. The frozen helper checks bounded,
feasible, full-dimensional volumes and all eight corners of every original t0
and task sample using its exact rational recorded-quaternion arithmetic.

This program also proves `I ⊆ O` using exact vertices, and `B ⊆ I` using all
vertices of the stock region. It inverts the exact affine receiver map underlying
the stock `rotate(conjugate(q))` rule, rather than silently replacing an
almost-unit authored receiver quaternion with another normalized transform.
Actual stock terminal flags and earliest stock entry are independently compared
against the full original telemetry. The runtime `E_I ≤ S` coverage check also
rejects any arithmetic/boundary discrepancy that would need later missing masks.
Nothing relaxes an anchor, entry, penetration or physical tolerance.

A static review must have scope `independent_static_inner_outer_entry_bounds`,
reviewer role `independent_examiner`, `passed: true`, explicit true premises
`inner_inside_physical_cavity` and `physical_cavity_inside_outer`, the exact
`case_sha256`, canonical `inner_planes_sha256`/`outer_planes_sha256`, a nonempty
`physical_cavity_definition` and a nonempty `files_sha256` closure of its static
geometry/proof inputs. Source files are checked before and after evaluation.
The independent examiner must actually justify the premises. A bounded
polytope or a declaration flag does not itself prove a cavity model.

For a physical cup, a possible static proof is a central column that avoids
all native wall/rim/floor/handle solids, capped by independently certified mouth
geometry, paired with a necessary outer cavity enclosure at the same physical
mouth. The original guarded prism proof remains intact. Native analytic cylinder
supports, composed transforms and explicit rounding bounds are needed; a cage
mesh/AABB alone cannot prove that the column is collision-free or define the
actual pocket. This generic document selects no candidate coordinates/footprint.
If the resulting observed entry bounds do not collapse, the tool fails complete
scope rather than fitting a column to the observed landing path.

## Clock contract and original reports

The exact clock-contract fields are `schema`, `case_sha256`,
`inner_contract_sha256`, `outer_contract_sha256`, `static_review_sha256`,
`physics_dt_s`, `limits` and
`physical_entry_scope: "collapsed_observed_bounds_only"`. Inner and outer
contracts must bind the same physical roots, dimensions, case, clock and review.
The review binds canonical plane arrays rather than contract hashes, avoiding
a circular review/contract hash dependency.

The original full v4 individual positive report must already be accepted and
retained by the independent verifier. Its exact SHA and the original
`run-lock.json`/`evidence-lock.json` hashes are mandatory custody anchors supplied
from that retained independent report ledger—for example the suite's
`individual_report.sha256` record. **Do not freshly hash the input files merely
to fill the required CLI arguments.** A local hash is not an external signature.

The program checks the full report's v4 code/kernel identity, case hash, original
directory/lock/result hashes and masks. It then verifies all original input/output
locks with the unchanged reader, complete strict timeline and t0, exact original
physical configurations and original stock terminal flags. Full physical case
semantics are delegated to that already accepted, exact retained full v4 report;
the additive reader only accepts a P3 mapping and never substitutes for stock.
The independent report and source files remain unchanged throughout.

The full report is loaded **alone**, reduced to required masks/metadata and
released before original raw telemetry is loaded. Only one raw run is parsed;
inner/outer queries reuse it, then return geometry/clock summaries without raw
samples. This avoids simultaneous expanded report/raw-run retention. The input
report itself is still parsed by the standard JSON reader; this is not a measured
whole-house RSS guarantee or a streaming parser. Original reports/masks remain
complete on disk. Bounds are at most 20,000 original task steps and 32 planes per
region; the inherited geometry helper's callback-observation budget is separate
from its complete geometric query. First-contact observations are not used as
entry or activity timestamps.

The pre-job freeze schema is `simscene.bounded_entry_clock_freeze.v1`, with
`frozen_at_utc` strictly earlier than `run-lock.created_at_utc`, and exact absolute
`files_sha256` entries for the original case, inner/outer/clock contracts, review,
this helper, the frozen halfspace v2 helper and frozen v4 fidelity helper. This
is auditable local chronology, not a signed external timestamp.

```sh
PYTHONPATH=/path/to/frozen-v41/src python experiments/bounded_entry_clock.py \
  --run /path/to/sealed-original --case /path/to/original-case.json \
  --inner /path/to/inner-contract.json --outer /path/to/outer-contract.json \
  --contract /path/to/clock-contract.json --review /path/to/static-review.json \
  --freeze /path/to/prejob-freeze.json --full-report /path/to/retained-v4-report.json \
  --full-report-sha256 RETAINED_REPORT_SHA --run-lock-sha256 RETAINED_RUN_LOCK_SHA \
  --evidence-lock-sha256 RETAINED_EVIDENCE_LOCK_SHA --output /outside/run/new-report.json
```

The CLI uses an exclusive output file outside the sealed original and never
overwrites prior evidence. Exit zero requires both verified file integrity and
complete additive scope. CPU tests are synthetic geometry/mask/custody
counterexamples, not actual full-verifier physics evidence.
