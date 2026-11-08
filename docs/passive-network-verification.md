# Passive network verification

`simscene.verification.passive_network` checks an independently frozen network
against complete recorded physics observations. It accepts measured motion,
physical contact callbacks and passive constraints. It never starts physics,
edits a scene, releases an object, applies a force or fills a missing sample.

The public case schemas are `simscene.passive_network.v1` and the explicit
typed-load extension `simscene.passive_network.v2`. A passed network
contract covers its declared physical chain, counts, timing and controls.
Asset discovery, the semantic review of household identities, native video
quality, project export/replay and separate P1 mechanism contracts remain
distinct acceptance work. No P2 or P3 scenario is frozen by this module.

## Python API

```python
from simscene.verification.passive_network import (
    validate_case, bind_case, evaluate, verify_run, verify_suite,
)

# Before preparing a formal run, check both the contract and its source IDs.
validate_case(case)
bind_case(case, positive_scene_spec)

# Unit tests or inspection of already loaded observations. This checks data,
# without certifying saved-file provenance or accepting a formal stage.
report = evaluate(result, spec, case)

# Read a complete sealed directory and its snapshotted case.
positive = verify_run(positive_directory)
broken = verify_run(
    broken_directory,
    mode="broken_rope",
    reference_run=positive_directory,
)

# Formal network acceptance requires all controls named by the frozen case.
suite = verify_suite(positive_directory, {
    "no_trigger": no_trigger_directory,
    "broken_rope": broken_directory,
    "locked_door": locked_door_directory,
})
```

`evaluate` accepts dictionaries and returns `formal_stage_accepted=False`.
`verify_run` additionally verifies input/output locks, the worker snapshot,
the case bytes, requested duration and actual seed. A positive run alone
retains `formal_stage_accepted=False`. `verify_suite` sets it only for a P2/P3
network whose positive and required isolated controls all pass. That field
refers to this network contract, not the complete project challenge.

A control requires a positive reference. The structural scene comparison is
reported independently of positive success; an unsuccessful reference still
prevents paired acceptance. Every paired run must have identical worker,
seed, duration, timestep, device, runtime/queue launcher paths and hashes,
runtime version, GPU selection and controller/archive flags.

When either run records `mechanism_configuration.geometry_settings`, both
must record exactly the same dictionary. This includes the SDK cylinder
approximation setting, its availability and binding-derived setting path.
It records the analytic/convex primitive policy observed by that worker;
equality does not establish a cause for a cart failure. Older runs with no
such field retain an explicit policy-not-recorded scope.

The standalone CLI only reads evidence. Keep the large JSON result outside
the immutable run directory:

```bash
PYTHONPATH=src python -m simscene.verification.passive_network /evidence/positive \
  --case /contracts/network.json > /reports/positive-check.json

PYTHONPATH=src python -m simscene.verification.passive_network /evidence/broken \
  --mode broken_rope --reference-run /evidence/positive \
  > /reports/broken-check.json

PYTHONPATH=src python -m simscene.verification.passive_network /evidence/positive \
  --control no_trigger=/evidence/no-trigger \
  --control broken_rope=/evidence/broken \
  --control locked_door=/evidence/locked \
  > /reports/network-suite.json
```

## Paired acquired asset snapshots (v40)

Run creation copies acquired assets to different absolute paths in each run.
Those paths may compare equal for an isolated control only through file-level
verification. `evaluate` and the immutable P1 `mechanism.evaluate` continue to
compare their input dictionaries exactly; adding untrusted metadata to those
dictionaries grants no exception.

New `asset-lock.json` snapshot records pin `snapshot_integrity_version: 1`,
`snapshot_lock_sha256`, the exhaustive `snapshot_files` inventory, and
`snapshot_mdl_runtime_files`. The run lock pins that asset lock. Verification
requires regular, nonsymlinked files, exact inventory coverage (including no
unlisted extras), and each payload file's relative path, size, SHA256 and
optional source URL. It also rechecks the package metadata SHA. Package
metadata and asset-lock provenance fields compare exactly, except for the
cache metadata's old absolute `root`; selection instead comes from the
run-pinned root bound to that exact object's `asset_path`. Equal downloaded
archive hashes alone never establish equal repaired content.

After both complete input/output locks pass, each supported USD payload layer
is freshly reloaded and its dependency closure scanned. Every resolved layer
and resource must belong to the complete snapshot inventory. Only the named
`OmniPBR.mdl`/`OmniGlass.mdl` runtime roots already recognized by the runtime
classifier may be supplied externally by that run's explicit SDK launcher.
Their paths and byte hashes are checked. All acquired and runtime MDL files
are also scanned recursively for relative imports, absolute imports and
`using` declarations. Absolute module names resolve only in that SDK's
`kit/mdl/core/mdl`; local imports resolve beside their module. Every external
module/resource gets a launcher-relative size/SHA256 pin in
`snapshot_mdl_runtime_files`, including standard-module shim files. The
compiler implementation behind standard shims remains part of the recorded
runtime. No ambient MDL search path or unknown external dependency is allowed.
MDL comments and `anno::thumbnail` editor metadata are excluded from material
resource discovery; the complete module bytes remain hashed. Unsupported
syntax, missing material resources, USD tools or dependency proof fail closed.

Only an exactly matching acquired identity permits a clone of the reference
spec with the corresponding `asset_path` replaced. The current spec, original
reference file and complete observations remain unchanged. Every nonpath
field still reaches the original structural comparator: material/variant,
attachment, transforms, physics and the isolated intervention must match.
Reports expose mappings, identity hashes and failure reasons under
`paired_asset_snapshots`. Existing records without the new proof retain
legacy input-integrity behavior and get **no relocation exemption**.

The same file-level proof also covers nested P1 assertions using their full
original telemetry. Public `case_runner`/CLI/MCP standalone mechanism dispatch
uses `mechanism_adapter.verify_run`, which checks the frozen case, complete
locks, all 13 paired runtime fields and geometry policy, then delegates to the
unchanged `mechanism.evaluate`. Its report distinguishes adapter
`checker_sha256` from `reused_mechanism_sha256`. Direct legacy
`mechanism.verify_run` and `experiments/mechanism_check.py` remain the immutable
P1 implementation and retain exact raw-path comparison. Historical P2 runs
are accepted with their archived checker version; this change revises no
numeric predicate, P1 contract or previously frozen case.

## Frozen case schema

Publish the case hash before formal simulation. Supply exactly the same case
bytes to the positive and controls. Run locks separately pin each scene spec;
a shared case must not contain a positive-only `source_scene_sha256`.
Choose thresholds from the intended physical meaning, measurement resolution
and independently inspected geometry, before observing a formal success.

| Field | Contract |
| --- | --- |
| `schema` | `simscene.passive_network.v1`, or explicit `simscene.passive_network.v2` for typed gravity support pads. |
| `profile` | `pilot`, `P2` or `P3`. A pilot never accepts a formal stage. |
| `require_strict_initial_state` | Must be `true`; source `observation.strict_start` must also be `true`. |
| `trigger_id`, `release_step` | One colliding dynamic sphere, scheduled at the declared step. All other dynamic bodies exist initially. |
| `events` | Named measured motion rules, described below. |
| `handoffs` | Directed physical paths connecting measured events. |
| `tiles` | Exact tile IDs, semantic label, long axis, tilt cutoff, minimum count and one activation event per tile. |
| `household_categories` | Meaningful household identities tied to actual dynamic roots and measured transmitting paths. |
| `minimum_household_categories` | Minimum number of categories that actually transmit. |
| `quiet_limits` | Per-body `maximum_motion_m` and `maximum_rotation_degrees`, measured from the restored t0. |
| `initial_hold_steps` | Required observed pre-trigger interval. Must be at least two steps and no larger than `release_step`. |
| `maximum_joint_anchor_error_m` | Global error limit for every enabled observed joint. |
| `contact_window_tolerance_steps` | Frozen tolerance for event-window contact witnesses. |
| `rope_body_ids` | Exact capsule-link IDs. Rope motion cannot supply activity time. |
| `mechanism_cases` | Optional mapping from assertion name to a complete frozen `simscene.mechanism.v1` contract, evaluated on the full original telemetry. |
| `structural_loads` | Required nonempty mapping only in v2; see [typed gravity support loads](structural-loads-verification.md). Rejected in v1. |
| `terminal` | Actual sugar dimensions, measured receiver interior and stability limits. |
| `activity` | Frozen task stages/ROIs/speed floors plus all four timing limits. |
| `controls`, `required_controls` | Explicit isolated interventions and their expected upstream/downstream behavior. |
| `description` | Optional prose describing the scenario. |

Unknown fields and unsupported event conditions are rejected. The complete
synthetic example in `tests/test_passive_network.py` demonstrates the schema;
it is a CPU fixture, not a scene recipe or a frozen acceptance scenario.

Version 2 preserves the v1 task, timing, passive motion, quiet, contact and
control requirements. It additionally inventories and verifies a narrowly
typed gravity-loaded pad on an existing task body. It does not admit arbitrary
unconnected dynamics. The pad gains no task event, household identity or
activity time. Its actual support contact, free gravity guide, cooked mass and
every original observation must satisfy the additional read-only check in
every positive and stopping control. New software and case hashes must be
frozen before new formal runs; existing v1 evidence keeps its original version.

## Motion events

All event origins use the measured strict t0. A scheduled sphere is absent
there, so an optional displacement event for that sphere starts at its first
measured presence. `trigger_release` itself uses the exact recorded spawn.

```json
{
  "drawer_open": {
    "conditions": [{
      "kind": "joint_coordinate",
      "joint_id": "drawer_slide",
      "coordinate": "position_m",
      "relative_to_initial": true,
      "minimum": 0.08
    }]
  },
  "weight_falling": {
    "conditions": [{
      "kind": "body_displacement",
      "body_id": "weight",
      "direction_world": [0, 0, -1],
      "minimum_m": 0.01
    }]
  }
}
```

`body_displacement` uses full XYZ distance when `direction_world` is omitted,
or a signed projection onto that normalized direction when supplied. Bounds
are `minimum_m` and optional `maximum_m`. A signed negative-direction event
may instead use a negative maximum.

`joint_coordinate` supports `position_m` for a prismatic joint and
`angle_degrees` for a revolute joint. It requires
`relative_to_initial=true` and a positive minimum or negative maximum.
The measured body is the joint's `body1`. Multiple conditions form a
conjunction, and each condition must require nonzero physical motion.

`box_leaves_support` measures complete separation from a moving support:

```json
{
  "kind": "box_leaves_support",
  "body_id": "sugar",
  "support_id": "spoon",
  "support_region_local": {"min": [0.05, -0.03, 0], "max": [0.15, 0.03, 0.03]},
  "minimum_relative_travel_m": 0.02,
  "clearance_m": 0.001
}
```

The box and dynamic colliding support must exist at t0, and the support must
be its actual incoming physical-handoff body. Initially all eight box corners
must fit the independently measured support region; an actual nonempty
support–box callback is also required before the trigger. On each sample,
the checker transforms every box corner and center into the support's current
measured local frame. The box's local bounding intervals must be wholly
separated from the support region on at least one axis, beyond the declared
clearance, and its relative center must travel the declared minimum. A center
outside while one corner still overlaps fails. Rigidly carried rotation or
translation cannot masquerade as release. The local-axis separation rule is
conservative for rotated boxes: ambiguous overlap fails rather than guessing.
Reports retain initial corners, original contact witnesses and per-step
relative geometry. Ordinary conditions still use the unchanged P1 predicates.

Optional `hold_steps` and `stability` use the existing mechanism event
calculator. Stability names a measured body and positive `max_motion_m`
and optional `max_rotation_degrees`. `after_event` and `not_before_step`
are forbidden: an early activation must remain visible and fail ordering.

Three names are reserved and derived from the frozen contract:

- `trigger_release`: the unique scheduled sphere release.
- `terminal_entered`: the first observation containing all eight sugar corners.
- `terminal_stable`: the first qualifying stable window, with a separate
  confirmation step.

## Physical handoffs

Every handoff declares `id`, `source_event`, `target_event`, a distinct ordered
`body_path`, parallel `links`, and `maximum_lag_steps`. Optional
`guard_events` must measure bodies on that same path and occur in their
declared order between its source and target. Equal steps reflect sampling
resolution; a reversed order fails. All task events must be reachable from the trigger through
an acyclic event graph. Every physical path must also reach the sugar.

A contact handoff between two bodies has `links=[{"kind":"contact"}]`.
It requires an actual nonempty contact-data callback for those actor roots
inside the frozen event window. A longer path may contain contact hops, but
each such hop must name its own `source_event` and `target_event`, measuring
the adjacent bodies. An earlier source or unrelated contact does not qualify.

A constraint hop has:

```json
{
  "kind": "constraint",
  "joint_id": "cord_to_drawer",
  "maximum_anchor_error_m": 0.008
}
```

The joint must be an actual enabled fixed or spherical connection between the
adjacent path bodies. Its observed anchors must remain within the frozen
limit throughout transmission. Free axes of prismatic/revolute joints are
not treated as an unqualified force-transmission shortcut; use their signed
coordinate events with actual contact or cable paths.

## Embedded mechanism assertions

`mechanism_cases` is a mapping such as `{"wrapped_cable": {...}}`, where the
value is a **complete** `simscene.mechanism.v1` contract. The outer frozen case
hash pins every nested threshold, role, segment, axis and geometry bound. Each
assertion also reports a canonical payload hash for inspection. Changing a
nested threshold in an independently sealed control still fails the common
frozen-case check.

The network calls the unchanged P1 kernel with the complete original result
and spec. It never slices samples, shifts time, reassigns roles or changes a
trigger. Nested `trigger_id` and `release_step` must equal the network values.
P1 wheel/spoon direct-trigger contact obligations still apply; a contract that
does not fit the full chain must fail, rather than be silently weakened. Extra
body/joint role keys are rejected.

A wrapped cable assertion may identify its grounded dynamic free pulley as a
structural component. Its weight, drawer and every capsule segment must
already belong to the declared force path. The pulley has an actual enabled
world-grounded revolute joint. Successful P1 geometry proves wrap, slack/taut,
travel and wheel motion; the network additionally requires a genuine per-step
rope–pulley callback during the measured taut-to-drawer-open interval. The
pulley does not need a fictitious pulley-to-drawer event, and is never attached
to the cable by an invented constraint. A direct-rope assertion cannot admit
or certify a pulley. Structural components cannot add household categories
or activity seconds. Every dynamic component needs frozen quiet limits, and
the no-trigger control must cover it.

Every positive embedded assertion must pass. In a `broken_rope` control, only
an assertion whose `joints.drawer_end` equals the isolated disabled joint is
evaluated in P1 `detached_drawer` mode, using the complete reference spec.
Other assertions in stopping controls receive the explicit status
`skipped_stopping_control`; no positive completion is claimed. Global
no-trigger, locked-door, upstream-motion, downstream-quiet and missing-sugar
outcomes remain mandatory. A suite containing any rope assertion requires its
matching passed detached assertion, even if a different cut also stopped the
network. `embedded_mechanism_controls_complete=False` prevents acceptance.
Multiple cable assertions therefore need compatible explicitly declared
drawer-end control coverage; this version has one `broken_rope` control slot
and rejects an incomplete set rather than inferring extra counterfactuals.

## Contact observation boundaries

The source must request `observation.record_contact_pairs=true` and record a
list on every physics sample. A record includes `actor_paths`,
`collider_paths`, `body_ids`, positive callback `count`, and original
`first_callback_absolute_physics_step`/`last_callback_absolute_physics_step`.
Collider paths may be absent in an SDK header, represented by `null`; actor
roots must still resolve to known physical objects. Unknown actors, forged
collider ancestry, missing lists, nonfinite separation values and inconsistent
counters fail provenance checks.

The current producer can deliver contact callbacks at the counter boundary
preceding the completed sample. The checker preserves that raw boundary and
the observation step. It never relabels a callback as a newly observed
activation, interpolates contacts between `first` and `last`, or invents a
middle timestamp. Handoff reports retain their actual callback witnesses.
Terminal contact is reported as an observation/boundary bracket.

## Tile and household counts

`tiles` requires `ids`, `class_label`, `up_axis_local` (`X`, `Y` or `Z`),
`initial_upright_max_degrees`, `tipped_min_degrees`, `minimum_tipped` and
`activation_events` mapping each ID to its distinct motion event. The optional
boolean `require_final_tilt` adds a final-pose obligation. It is mandatory
`true` for P3; P3 also requires `minimum_tipped == len(ids)` so every declared
ID succeeds. Pilot/P2 cases without the flag, or with explicit `false`, retain
the original first-crossing predicates.

Every tile must be a labeled colliding dynamic box, with its actual longest
dimension along the declared local axis. Measured quaternions determine that
axis's angle from world vertical. Yaw does not count as falling. A tile counts
once, only if it first crosses the tilt cutoff after the trigger; reports give
initial, maximum and final tilt for every named tile. Books, rope and unnamed
objects never supplement the count.

When `require_final_tilt=true`, every declared tile must additionally meet the
same frozen `tipped_min_degrees` cutoff in the last complete physics sample.
A tile that crosses90 degrees and rebounds to20 degrees retains its historical
crossing count but fails the final obligation. Reports keep
`actual_tipped_tile_count` separate from `actual_final_tipped_tile_count` and
give each tile's `final_tilt_passed`. The extra check applies to every named
ID even when a pilot/P2 crossing minimum is smaller. No interpolation, maximum
angle or video frame substitutes for the final measured quaternion. Existing
P2 contracts without this flag are not reinterpreted; archived P2 verifier
versions and their evidence remain intact.

Each household category declares `description`, `body_ids`, `class_labels`
and `activation_events`. Bodies and semantic labels cannot be reused under
new category names. A qualifying root must actually activate, receive a
successful physical transmission and pass it to a different neighbor.
Attached decorative USD meshes and passive structural parts do not become
extra household categories. Meaningful identities require manual independent
review before freezing; pins, supports and renamed variants do not create
additional household kinds.

Put the semantic label on the actual compound/primitive physics root. A
`rigid_attachment` visual asset is excluded from physical counts. Its mesh can
provide visual identity while measured proxy colliders provide physics; that
proxy approximation must remain explicit in delivery. Active imported asset
physics is outside this version's calibrated strict-root contract.

## Sugar and activity timing

The terminal contract declares `body_id`, `receiver_id`, actual `size_m`,
`interior_local={min,max}`, `hold_steps`, `maximum_motion_m` and
`maximum_rotation_degrees`. The sugar is a physical box. The receiver is a
static colliding container, and the bounds are its independently measured
interior in the receiver's local frame.

Every rotated sugar corner must fit. After its first complete entry, the sugar
must remain contained through the rest of the run and establish the stable
window, then remain stable. A center-only hit, transient passage through the
cup, equal first/last poses hiding an excursion, or a later escape fails.

`activity` contains only `stages` and `limits`. It reuses the central event
table with `measure_activity`. The main window is fixed from
`trigger_release.onset` to `terminal_entered.onset`; waiting for the stability
confirmation cannot lengthen it. All durations use original simulation time.

Stages declare the existing helper's `id`, `purpose`, `start_event`,
`end_event`, `roi_world={min,max}` and explicit `bodies` motion floors.
`start_time` may be `onset` or `confirmation`; `end_time` is `onset`. Each
body's phase must end at one of its own physical handoffs. Rope links,
decorative objects and unlisted components cannot provide activity. Both
neighboring measured centers must be inside the ROI. Simultaneous valid
sources produce one per-step flag and count once. Cameras, encoding time,
replays, residual spin and intervals after task completion do not extend it.
An ordered local guard of that same handoff may end a phase earlier, for
example when the sugar has completely left the spoon's support region.

A motion source may add `direction_world`, a unit XYZ vector, together with
its positive `minimum_speed_m_s`. That linear branch uses
`dot(current_position - previous_position, direction_world) / dt` instead of
the 3D speed norm. Backward progress and motion orthogonal to the direction
cannot buy time. For example, a guided cart can declare its forward rail
direction so vertical bobbing does not count as travel. An optional
`minimum_angular_speed_degrees_s` remains a separate branch; omit it when
angular jitter must not qualify. Sources without a direction retain 3D motion
for genuinely multidirectional travel or tilting. The read-only wrapper
filters the existing helper's eligible intervals and recomputes their union;
it retains the base metrics and signed per-step diagnostics for audit. Event,
handoff, ROI and clock checks still apply.

For moving-support event gates, the unchanged P1 activity helper supplies an
upper bound on physical motion inside the real release-to-entry window.
The network wrapper then filters those same original observations by its
full measured event table, original ROIs and signed progress. No synthetic
timestamps, coordinates or samples are passed to the helper. Reports expose
`base_helper_upper_bound_metrics`, the actual event-gated `base_3d_metrics`,
and the final projected union. An early support loss remains visible and
fails ordering; it is never delayed with an after-event or time gate.

| Formal profile | Minimum actual tiles | Minimum span | Minimum action | Occupancy and idle | Terminal stability |
| --- | ---: | ---: | ---: | --- | --- |
| P2 | 50 at at least 60 degrees | 20 s | 20 s | Explicit frozen limits | At least 120 steps, at most 2 mm and 2 degrees |
| P3 | Every declared ID, at least200; crossing and final tilt at least60 degrees | 50 s | 45 s | At least 0.85; at most 2 s idle | Same stability floor |

P3 also requires at least six transmitting household categories. The case may
make these limits stricter. A pilot may use smaller synthetic or development
targets and never claims formal stage acceptance.

## Isolated controls

Every control declares `downstream_body_ids` and `upstream_event_ids`. The
downstream set must cover the graph descendants of the intervention and have
explicit quiet limits. Quiet means bounded XYZ displacement and angular change
from the same restored t0, throughout the complete control run. Required
upstream motion must still occur, downstream task events must remain absent,
and the sugar must never enter its terminal volume.

| Mode | Exact permitted scene change | Additional fields |
| --- | --- | --- |
| `no_trigger` | Delete only the scheduled sphere object. No spawning remains. | No upstream task event; all task bodies remain quiet. |
| `broken_rope` | Set only one enabled declared cable joint's `enabled` to `false`. | `joint_id`, `cut_handoff_id`; its real source event must still activate. |
| `locked_door` | Set only the declared revolute joint's lower/upper limits equal to its frozen authored initial angle. | `joint_id`, `door_body_id`, `locked_angle_degrees`, `cut_event_id`; incoming source events must still activate. |

Only `scene_id`, revision and request history metadata are ignored when
comparing specs. Body transforms, geometry, mass, physics settings, visual
attachments, cameras, presentation and unrelated joints must all remain
identical within the pair. A lock that moves the door away from its authored
initial angle is rejected as an actuation. A disabled cable joint must be a
declared hop of the claimed transmission path.

P2 requires its no-trigger control and, when it contains cable links, the
broken-rope control. P3 requires all three. Missing controls prevent a formal
suite result; any supplied failed control also fails the suite. No control is
executed or constructed by this evaluator.

Quiet tolerances must be smaller than the corresponding displacement or
joint-angle task activation. A permissive quiet budget cannot hide an early
qualified movement, including when a later event requires several held steps.
