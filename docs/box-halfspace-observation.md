# Original recorded box in declared static halfspaces

`experiments/box_halfspace_observation.py` is an additive, read-only geometry
observer outside the frozen plugin and whole-home v3 examiner. It does not
replace the stock/v3 physics, terminal, stability, controls or timing checks.
It never launches a simulator/GPU, applies commands, rewrites a pose, rebases
samples, crops a window, interpolates data or substitutes a later entry.

The helper checks a real, initially present, dynamic `kind: box` against an
independently declared static convex volume. Every original measured strict
sample0 and task sample `1..N` is required. It reuses the unchanged ce05
`timeline` and `strict_initial_state` checks, including the complete relative
and absolute clocks and tensor maps. Missing, duplicated, reordered, partial
or rebased observations make the geometry query incomplete. The physical box
dimensions and complete box/receiver root configurations are bound to the
declaration. The receiver must be authored static collision geometry, with no
scheduled spawn, pose follower or conveyor.

The strict JSON contract has schema `simscene.box_halfspace_observation.v1`
and exactly these fields:

| Field | Meaning |
| --- | --- |
| `schema` | The schema above |
| `case_sha256` | SHA256 of the exact original case file bytes |
| `physics_dt_s` | The original locked positive timestep |
| `box_body_id`, `receiver_id` | Distinct actual physical root IDs |
| `box_size_m` | Exact authored full box dimensions; no replacement size |
| `box_configuration_sha256`, `receiver_configuration_sha256` | Canonical SHA256 of each whole original `spec.objects[id]` mapping |
| `planes` | 4–32 independent-static-declaration plane records |
| `static_review_sha256` | Exact byte SHA256 of the independent STATIC nominal review |
| `geometry_validity_scope` | Exactly `independently_declared_static_halfspaces` |

A plane is exactly `id`, `normal_world`, `offset_m`. IDs must be nonempty and
distinct. Its closed interior is `dot(normal_world, point_world_m) <= offset_m`.
Normals must be finite and unit within a 1e-12 squared-norm validity bound;
they are used unchanged and are never silently normalized. The bound validates
the input convention; it adds no membership tolerance. World means the
original run's world metre axes. The future independent static review supplies
the plane parameters; this generic tool supplies no candidate coordinates.

`canonical_sha` uses sorted JSON keys, compact separators and rejects nonfinite
JSON numbers. Snapshot-local acquired visual paths are not ignored or remapped:
the two declared roots here are actual box/static collision geometry roots,
not a visual asset configuration. A changed initial placement, size, physical
setting or other root field requires a new independently reviewed declaration
before the next formal snapshot. This does not authorize changing any old case.

Before reading the observations, exact rational geometry validates the volume.
The normal matrix must have rank three. Its recession cone must have no
nonzero direction: with full normal rank it is pointed, so any nonzero cone
would have an extreme ray along one of the two signs of an independent normal
pair's cross product. All such candidates are checked. Feasible vertices are
then enumerated from every independent plane triple and checked against every
constraint; four affinely independent feasible vertices are required. Empty,
unbounded, lower-dimensional, malformed or unsupported volumes return
incomplete. No numerical optimizer tolerance or guessed enclosing AABB is used.

Each recorded quaternion is checked by the frozen pose/clock reader. The
rotation matrix divides by that quaternion's exact squared norm. This is the
orientation represented by its original finite components, not a rewritten
observation. All eight signed local half-size corners are transformed once per
sample with rational arithmetic. Shared integer denominators cache those
corners and each static plane; **every** corner/plane test is still performed.
The optimization is tested against naive Fraction dot products. Membership
uses zero inside tolerance: a negative exact signed margin fails even if a
rounded display value is tiny. Display margins/corners are approximations;
exact rational margins and signs are retained with minimum-margin witnesses.

The first boundary whose complete eight-corner box belongs is fixed as
`first_complete_entry`, including step0 if applicable. All later original
boundaries are examined. **Any** later nonmember boundary is listed in
`escape_steps` and rejects `membership_supplement_passed`, even if a later
entry is retained for the rest of the run. The per-face minima after that
earliest entry include the entry itself and every remaining original step,
with the worst step/corner/position witness. Every step also retains its eight
corners and worst plane margin. The preceding original boundary is reported
without inventing a continuous crossing time.

This is a sampled-boundary observation, not between-step continuity. Convex
halfspace membership does **not** prove that the declared region equals the
modeled receiver's interior, visible mesh or physical collision cavity. The
static review's bytes are bound, but the helper does not authenticate the
reviewer's geometric judgment. `modeled_receiver_equivalence` is always
`not_established_by_this_helper`, `between_step_continuity` is always
`not_established`, `stability_assessed` is always false and
`formal_house_accepted` is always false. A moving/spinning box can satisfy
membership; the existing stock/v3 suite alone owns stability/physics acceptance.

If original per-step callback records are complete and valid, the first task
app-update observation containing actual box/receiver contact data is reported.
Its raw callback absolute counters are preserved; a callback may refer to the
preceding boundary. This is not an activation or continuous contact timestamp.
Aggregate historical `first`/`last` contact values are never used. Missing,
truncated, unknown or malformed callback data make the contact subreport
incomplete, with `first_contact: null`; a separately labeled first *observed
available* record can remain. This optional contact limitation never becomes a
fabricated contact, and does not turn membership into physical acceptance.

The file-level command requires the exact original case/contract/review and
an independent static binding freeze. The freeze is a mapping with
`schema: simscene.box_halfspace_freeze.v1`, timezone-aware `frozen_at_utc` and
`files_sha256` pinning the absolute resolved case, contract, review and helper
paths. Its recorded date must precede the original `run-lock.created_at_utc`.

Two additional inputs are the original run-lock and evidence-lock SHA256
values. **They must come from an already retained independent sealed-run
ledger or full verifier report** (for example the eventual suite's individual
run report). Do not freshly hash the same files merely to fill those CLI
arguments. The helper checks the supplied exact byte anchors, but cannot
authenticate where arbitrary hash strings came from. Local hashes/dates are
not external signatures or timestamp attestations.

The unchanged db21 locked reader verifies all original inputs/outputs, assets,
worker snapshot, requested-step/seed identity and the exact snapshotted case
bytes. This tool asks that case to parse as a mapping; it does not reinterpret
or certify the case's physical semantics. The original stock checker still
owns those semantics. Full original run/evidence/spec/result/case hashes and
external contract/review/freeze hashes are checked before/after observation
and retained in the report. No reserialized case is substituted.

Example invocation with independently retained pins and caller-declared paths:

```bash
PYTHONPATH=src /home/dell/.local/share/simscene/venv-v31/bin/python \
  experiments/box_halfspace_observation.py \
  --run /sealed/original-run --case /declared/original-case.json \
  --contract /declared/halfspaces.json --static-review /declared/static-review.md \
  --freeze /declared/halfspace-freeze.json \
  --run-lock-sha256 "$RETAINED_RUN_LOCK_SHA256" \
  --evidence-lock-sha256 "$RETAINED_EVIDENCE_LOCK_SHA256" \
  --output /new-reports/geometry-observation.json
```

Output must be outside the sealed run and is created exclusively. Exit0
requires complete geometry, verified original file custody and earliest entry
with no later recorded exit. It never accepts a whole task. In-memory
`evaluate` cannot certify file provenance and explicitly reports that limitation.

Budgets are 32 planes, 20,000 task samples plus the original t0, at most
5,120,256 corner/plane tests, and one million optional callback records. Volume
validation examines at most 4,960 plane triples and 496 normal pairs (both
signs). An unsupported step/plane/volume/pose never silently becomes complete.
The helper holds one original raw run, not a suite of raw runs. The unchanged
file-proof reader has its intrinsic whole-JSON parsing costs; these operation
bounds do not promise a peak RSS or runtime for multi-gigabyte evidence.
