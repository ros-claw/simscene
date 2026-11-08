# Typed gravity support loads

`simscene.structural_loads.v1` is a read-only kernel used only by the explicit
`simscene.passive_network.v2` profile. Legacy network v1 and the independent
mechanism kernel retain their existing predicates. This extension inventories a
gravity-loaded support/friction pad; it supplies no activation, household type,
activity seconds, calibrated normal force, friction force, impulse or tension.
It never authors a joint, releases a body or changes a simulation.

## Public API and declaration

`validate_declarations(declarations)` validates and returns a nonempty mapping
of 1–16 pad body IDs. `bind(spec, declarations, path_bodies, quiet_limits)`
raises `ValueError` for unsupported declarations or geometry and returns a
JSON-safe static context with `body_ids`, `loads`, `path_bodies`,
`quiet_limits` and `declarations_sha256`. It admits only those explicit pad IDs;
their graph neighbours gain no exemption.

```json
{
  "pad": {
    "kind": "gravity_loaded_support_pad",
    "guide_joint_id": "pad_slide",
    "support_body_id": "tray",
    "support_motion_event": "tray_moves",
    "pad_part_index": null,
    "support_part_index": 0,
    "gravity_direction_world": [0, 0, -1],
    "thresholds": {
      "seating_steps": 2,
      "contact_tolerance_m": 0.002,
      "maximum_penetration_m": 0.001,
      "guide_limit_margin_m": 0.01,
      "guide_frame_tolerance_m": 0.0001,
      "maximum_support_tilt_degrees": 2
    }
  }
}
```

These are generic synthetic example values, not a scene prescription. Every
threshold must be frozen before formal observations. A primitive Box uses a
null part index; a compound uses an explicit zero-based colliding Box part.
The pad has exactly one colliding Box. Other noncolliding visual parts may
exist. The selected support is an actual dynamic task-path body and selected
colliding Box, rather than a world shelf, visual attachment or second load pad.

`evaluate(run, spec, declarations, binding_context, events, journal, dt)`
returns a report with `passed`, explicit checks, per-step geometry, errors and
scope. It fails closed on missing/malformed evidence; it does not replace the
network's global passive, causal, quiet, control, terminal or timing checks.
The caller must gate every positive and stopping-control mode on this report.
`formal_stage_accepted` is always false: this helper alone cannot accept a stage.

## Static boundary

Both bodies are initially present dynamic colliders with explicit positive
authored mass. Active/kinematic motion, followers, conveyors, force/surface
velocity declarations and unsupported passive physics are rejected. Only metric
Z-up coordinates and the pinned backend's world −Z gravity profile are supported.
Object IDs must not alias the same exported prim path.

Exactly one authored joint may reference the pad, even when an extra joint is
disabled. It is an enabled, undriven world-to-pad prismatic joint. Its free axis
is parallel to gravity (either sign; absolute dot at least `1-1e-8`), frames
align within 0.001 degrees and the pad is away from both guide limits by the
declared margin. This profile cannot classify fixed pads, a guide clamped along
gravity, extra dynamic connections, a guide carrying the initial load at a limit,
or a body held by another joint. Legacy metric-joint Box restrictions still apply.

The pad's complete initial bottom footprint must lie on the selected rectangular
support with the following conservative minimum edge margin in that part frame:

```
pad.maximum_motion_m + support.maximum_motion_m
    + 2 * guide_frame_tolerance_m
```

This initial full-footprint requirement is not partial/AABB overlap and is not
weakened for a particular layout. Both faces oppose gravity within the declared
tilt (at most five degrees). Initial penetration stays within its explicit bound;
the seating gap cannot exceed the pad's frozen quiet translation budget. The
contact tolerance cannot exceed one quarter of either selected Box thickness.

The network binds `support_motion_event` to exactly the real support body. It
also requires `seating_steps + 2 <= initial_hold_steps`; initial seating is a fixed
predeclared budget of 1–600 original steps, not a detected successful settling
time or activation event invented for the pad.

## Original-step evidence

The unchanged mechanism `timeline` and `strict_initial_state` checks are reused:
one complete original task clock, tensor t0, all dynamic pose/velocity maps,
absolute boundaries and complete joint observations. No step is sliced,
interpolated, rebased or replaced. Missing/truncated contact capture fails.

Loaded joint metadata must show exactly one enabled, undriven world prismatic
for the pad, with the declared body endpoint. Cooked positive mass, local COM,
principal-frame quaternion and positive-definite inertia are required
for both pad and support, from the recorded PhysX tensor readback. The reported
mass must match the authored value. Symmetry must agree within the worker's
readback tolerances (1e-5 relative, 1e-8 absolute); exact rational principal minors
of its symmetric part avoid floating overflow/underflow in the definiteness
test. The pad COM lies
strictly within its sole collider. Reported kinematic/disabled-gravity settings
fail. The result does not independently measure a force or gravity vector.

Initial and every subsequent reported guide coordinate/anchors/error are checked
against measured poses and frozen authored frames, including rotational frame
alignment. The readback inventory establishes loaded type, enabled state,
endpoints and lack of drives. Axis/limit values are the frozen authored model,
not extra runtime measurements: independent static USD/configuration review,
pinned source and original file/evidence locks remain necessary.

For each original step, the pad bottom quadrilateral is transformed to the
support part frame and clipped against all four exact represented rectangle
boundaries using `Fraction`. Closed boundary contact remains overlap. This
eliminates a rotated AABB/vertex shortcut. Upstream quaternion transforms and
distances use finite normalized floating arithmetic; exact clipping does not
prove renderer, collision solver or between-step continuity equivalence.

While supported, the pad remains within its t0 quiet translation/rotation
budgets, the selected faces remain near horizontal and compatible in height,
and the world guide remains strictly interior. The support plane's height at
the fixed guide axis stays within the support's quiet translation budget;
horizontal withdrawal is permitted. After seating, **every supported step**
requires its own nonempty callback for the actual selected pad/support collider
paths. A compound path is `/World/body/part_N/Shape` (or its descendant);
a primitive path is `/World/body` (or its descendant). Missing collider identity,
another support part, wrong callback boundary, nonpositive count, nonfinite
reported separation or penetration beyond the declared bound fails. At least
two steps must certify the load. Sleeping objects without callbacks cannot be
certified by filling gaps with a previous/aggregate contact.

The supplied journal's pad records must exactly equal the original per-step
records, including multiplicity and original absolute callback boundaries.
No `first_contact` activation time or persistent contact is synthesized. Contact
on any body other than the named support—including a static surface or another
pad—fails throughout the entire run, including after support loss. A callback
certifies contact identity, not a measured contact normal or load magnitude.

The earliest geometrically disjoint projected step retires the load only if
the real support motion event has already occurred on the original clock and
the support has actually exceeded its own quiet pose budget. Premature loss,
missing event and reentry fail. After retirement, the disconnected pad may reach
its own prismatic limit; that phase is explicitly not credited as support load.
All steps still require coherent passive guide evidence and no unrelated contact.

## Custody and software scope

The caller remains responsible for original sealed input/output locks, exact
frozen case bytes, loaded-stage/configuration inspection, passive source hashes,
runtime/device settings and matched isolated controls. In-memory telemetry is
synthetic/untrusted unless those outer checks establish custody. No body is
admitted merely because a material name, category label, observed successful
timing or narrative calls it structural.

This is a pre-formal generic proof extension. It changes neither user motion
floors nor existing mechanisms, acceptance volumes, time masks, energy rules,
quiet/control thresholds or stability rules. No candidate runtime observations
were read in developing or freezing its synthetic tests.
