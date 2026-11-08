# Passive mechanisms and measured motion

Use ordinary scene operations. A `joint` object contains `joint` with `type`
`revolute`, `prismatic`, `spherical`, `fixed`, or `d6`; `body1` names an initially
present dynamic body. `body0` names another dynamic body or is null for world.
`local_pos0/1` are metres; `local_rot0_wxyz/local_rot1_wxyz` are normalized
quaternions. For a world endpoint its local frame is a world frame. Axis is
`X`, `Y`, or `Z`. Paired lower_limit/upper_limit are degrees for revolute and
metres for prismatic. `enabled=false` disables just that physical joint.

D6 requires `dof_limits` with all six keys: `transX`, `transY`, `transZ`,
`rotX`, `rotY`, `rotZ`. Each value is `"free"`, `"locked"`, or a finite
`[low,high]` with low < high. Translation is metres; angular bounds are degrees
strictly inside ±180°. Use `"locked"` rather than `[0,0]`: USD locking uses a
low > high sentinel, which the plugin authors explicitly. Free axes have no
LimitAPI. For a passive articulated cord, declare all three translations
locked and finite twist/swing ranges; joint X is the twist axis. Capsules use
local Z, so deliberately map the joint frames to the intended material axis.
Do not borrow global Euler components as joint coordinates. Two D6 swing limits
form a pyramid, not a spherical cone. Hard angular limits are an articulated
model approximation, not calibrated cord bending or torsional stiffness.
Loaded USD mode/limit readback and per-step relative frame translation and
quaternion are available. Reported overall swing is not either individual
pyramid coordinate; a physical native trial is required to establish enforcement.
Strict D6 observations derive frames from the same saved PhysX body-tensor
sample; `pose_source` distinguishes this from the standalone USD fallback.
These are body-frame calculations, not an independent SDK joint-angle getter.
Keep this model experimental until real connected/cut trials pass. Existing
spherical rope cases do not certify a new D6 model.

Use the explicit [D6 model and verification contract](passive-d6-joints.md)
for a bounded capsule cord: standalone `simscene.mechanism.v2`, or exactly one
cord inside `simscene.passive_network.v3`. Keep the original slack, contact,
quiet, timing and isolated-control thresholds. Declaration/readback admission
does not prove initial angular compatibility or native angular enforcement;
freeze that static proof and perform the actual paired rope test separately.

Body poses and joint frames define the initial coordinate. No drive, target,
motor, scripted downstream release, or force callback is added. A joint can
hold a body against gravity without consuming actuator energy; stability,
friction and motion still require actual simulation. Joint frames require an
unscaled rigid frame: use a compound body when a legacy box/sphere has
nonuniform root scale. Generic imported-joint inspection reports existing
joint paths, endpoints, local frames, limits and drives; imported joints do
not become suitable passive mechanisms merely by being present.

A `compound` body uses `parts` (1..128). Each part is box/sphere/cylinder/capsule
with local metric position, orientation, size, optional material/color and
collision flag. There is one dynamic body and mass on the unscaled parent;
child shapes remain rigidly connected. Make actual visible handles, paddles,
bearings and supports; inspect clearances and initial overlap.
Set `mass_kg` deliberately. The backend derives the centre of mass and inertia
from the collision geometry and total mass; visual attachments do not contribute.
Strict runs save cooked mass, local COM, principal-axis orientation and inertia
at the COM in rigid-prim axes under
`mechanism_configuration.mass_properties_by_prim_path`. Values are kilograms,
metres and kg·m². These are actual PhysX tensor readbacks, not a solid-material
calibration or a claim that the visual mesh has that mass distribution.
Use `scene_measure(..., include_overlap_candidates=true)` on nearby bodies
to review authored rendered AABB intersections before a trial. These are only
candidates: compound empty space and intended supports can overlap their
bounds. Confirm shape contacts from the actual per-step collision records;
even a few centimetres of sideways shelf intrusion can stop a long tile chain. Axial geometry
uses local Z and size=[diameter,diameter,total_length]; capsules include end
caps in total_length. Rotate the body or part to change the axis.

An acquired mesh can be a visual child of a physical compound. Add it as an
ordinary `asset` with `asset_physics: visual_only`, `asset_lights: disabled`,
`rigid_attachment: {body: "spoon_body"}`. For this attached asset only,
`position` and `orientation_wxyz` are local to that initially present dynamic
compound. Unit/up-axis conversion remains on the visual child; the parent
joint frame stays in metres. The USD hierarchy carries the mesh rigidly,
without a runtime follower or pose commands. `scene_measure` resolves its
authored world pose. Place/arrange its parent, or edit the child's explicit
local pose; attached visuals cannot be placement supports. Inspect and measure
the mesh before attaching it, align collision parts to its functional surfaces,
and disclose the proxy approximation. Compound parts can use `visible: false`
to hide collision proxies while retaining their actual physical shapes.
Acquisition locks, dependency snapshots and project exports retain these
ordinary asset objects. Imported joints are stripped only in this explicit
visual-only reference; source files remain intact.

Primitive/compound `physics` can set static_friction, dynamic_friction,
restitution, linear_damping, angular_damping, sleep_threshold,
solver_position_iterations, solver_velocity_iterations, enable_ccd,
contact_offset_m and rest_offset_m. Damping is passive energy loss, not a
position drive. `sleep_threshold=0` keeps delicate release mechanisms awake;
otherwise a resting body may remain asleep after a support slides away.
Contact offset must exceed rest offset. Keep offsets small relative to parts;
a default contact envelope can be larger than a sugar cube. CCD is enabled on
both scene and selected bodies, including scheduled initial spheres. Verify
it on the actual backend; a thin floor plus endpoint contact is not proof that
a fast body remained above the floor.

`scene_plan_rope` proposes real mass-bearing, colliding capsules with spherical
connections from a metric world polyline. Supply deliberate slack, radius,
segment length, linear density and optional start/end {body,local_position_m}
attachments. Review/apply returned operations. `self_collision=false` explicitly filters rope-to-rope collisions while retaining real external contacts; record that approximation. It never animates endpoints or
claims successful pulley routing. Keep initial nodes outside shelves and
inside a physical groove; retain failed trials. A straight distance constraint
is not a rope wrapping over a rotating pulley. If you choose a direct-rope or
ideal-guided substitute, label that physical model explicitly.

For formal passive runs use `set_observation` with
`observation={sample_interval_steps:1,strict_start:true,record_contact_pairs:true}`.
Strict startup performs one paused initial-state reset after SDK warmup, verifies
authored poses and zero velocities, and records the task-zero absolute clock.
No body state setters run during the task. A strict run currently requires
explicit passive primitive/compound bodies and excludes active robot controllers.
Runtime per-step contact records retain actual collider paths and raw callback
counters; callbacks occur before the SDK post-step counter increment.
It records every
actual physics step and fails on skipped steps. Runtime evidence includes
loaded passive settings, actual joint inventory and initial joint states;
per-step joints contain signed travel or unwrapped angle and measured world
anchors. Read these values; never use an observation callback to actuate a
mechanism. Angular/signed 3D motion can activate a preconnected object without
a new contact. Contact first/last summaries cannot reconstruct every middle
contact event; acknowledge insufficient temporal evidence.

Freeze conditions before formal runs. Verify geometry, signed motion, physical
contact/constraint links, event order and terminal containment independently.
Use a detached endpoint and a blocked mechanism to test necessary causal
links. To measure task duration, union original-time per-step task motion only
inside predeclared phases and activity regions. Do not count the camera,
finished wheel spin, residual rope jitter, replay speed changes or empty holds.
Missing observations invalidate timing. Packaged `run_verify` dispatches `simscene.mechanism.v1` cases. Supported
P1 mechanisms are rope/drawer, wheel/door/bridge, and spoon/sugar. A positive
rope case needs a matched `detached_drawer` run with `reference_job_id` for causal
acceptance; a positive run alone does not prove the rope necessary. Full-room
counting and timing acceptance require a separately frozen whole-room case.
Pin the case to each run and preserve input/output
locks, failed attempts, negative controls, source captures and software version.


For a multi-room passive chain, read the [frozen network contract](passive-network-verification.md).
`run_verify` infers `simscene.passive_network.v1`; stopping controls use
`mode=no_trigger|broken_rope|locked_door` plus the positive `reference_job_id`.
Call `run_verify_passive_suite` with the positive job and a mapping of required
control job IDs before accepting a P2/P3 stage. A positive run alone has not
established counterfactual necessity. Freeze tile IDs, meaningful transmitting
household types, task events/regions and motion floors before formal runs.
A directional linear source uses `direction_world`; a cart's vertical bobbing
or backward motion must not count as forward progress. Structural cable, wheel
and guide motion is excluded from task time. Embedded P1 mechanism contracts
run on the complete unchanged telemetry and retain their trigger/t0 obligations.

Inspect connected mechanisms in their resting state as well as during transfer.
A loaded sliding plate can jam on a nearby cable, and a guide that also locks a
wheel chassis's height can overconstrain its ground contacts. Separate passive
horizontal and vertical freedoms where the physical mechanism requires them;
document an ideal rail constraint and verify actual wheel contact/rotation.
Use real geometry and passive constraints for gates and stops. Observation and
verification callbacks must never release a downstream body.
