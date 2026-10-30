# Experimental robot streams and physical evidence

For reactive planning around known static primitive obstacles, a follower can
set `avoid_obstacles` to their scene IDs and `obstacle_margin_m` to a finite
clearance between 0 and 0.1 m. Only distinct static collision-enabled boxes
and spheres are accepted. This mirrors those shapes into cuMotion's planning
world; it is not swept-path certification or a substitute for the separate
discrete collision audit. The floor, grasped object and near-contact surfaces
should not be added indiscriminately as obstacles, since that can make the
target unreachable. Inspect the actual monitored run and handle timeouts.
The per-move `max_joint_speed` is a completion/settling threshold, not a hard
speed limit. The follower's global speed parameter is an RMPflow soft cap;
neither setting certifies collision clearance or physical safety.
If a move times out after reaching its position tolerance, inspect measured
joint speed and the required consecutive `settle_steps`. A shorter settling
interval is a candidate to test, not proof of stability: rerun and check the
physical result and collision audit without weakening the acceptance case.
An individual move phase may set `rmp_max_joint_speed` to override that soft
cap for the phase, provided the follower also sets a global `max_joint_speed`.

For example, an addition is `{"op":"add","id":"box1","object":{"kind":"box",
"size":[0.2,0.2,0.2],"position":[0,0,0.1]}}`; put `id` on the operation
and use `kind` inside the object. An update uses `{"op":"update","id":"box1",
"changes":{"position":[1,0,0.1]}}`.
Bind a conveyor with `{"op":"bind_conveyor","id":"belt","speed_m_s":0.1,
"direction":[1,0,0]}`; the target must be a static box surface. A separate
box surface can be placed over a visual conveyor asset, but check alignment,
contact and the resulting movement in an actual run.
A gravity-fed chute can be composed from a tilted, collision-enabled static
box and optional side rails, with scheduled dynamic objects spawned above its
upper end. Check that each object actually contacts the chute and reaches the
moving belt in the simulator; a scheduled spawn on the belt alone is not a
verified feeder. Recheck the combined feeder and robot workspaces after adding
it to a larger scene.
Keep sorting-bin walls clear of the full passing workpiece footprint, accounting
for rotated wall geometry, object width and lateral drift. Check that each
robot can reach its drop waypoints. If moving a bin, move its whole physical
geometry, corresponding drop waypoints and independent case bounds together;
verify the resulting clearance, reach and sorting in an actual run.
If missed items need recovery, place a colliding tray floor below and partly
under the conveyor's downstream edge, with side and downstream walls that do
not obstruct the belt. Verify its placement in the rendered scene and use a
separate physically simulated missed item to check that it leaves the belt,
contacts the tray and settles inside; a decorative box alone does not prove
recovery.
For a compatible acquired Kawasaki RS007L/RG2, Franka Panda, or UR10 short
suction asset, `robot_prepare_profile` can generate experimental controller
files from the selected local USD and installed Isaac configuration. Poll
`job_status` and use its `model_directory`; verify frames and actual motion,
since generating a profile does not certify asset compatibility or safety.
`robot_suggest_configuration` can propose a starting pose follower from that
profile and the intended world base pose; it does not plan a complete task.
For the compatible Franka Panda profile, this suggestion includes a scene-local
experimental finger-drive limit of 20 N and finger friction of 1.0. The
`gripper_physics` setting is explicit, applies only to the exported scene,
and leaves the selected source USD unchanged. The specified relative joint
and rigid-body paths must exist in the selected asset; validate the grip and
object behavior in a real run. These values are not a general guarantee for
other grippers, objects, loads or geometries.
`robot_plan_pick_cycle` proposes a per-model cycle for approximately 4 cm
cubes, using `$item` and `$slot` for expansion by `scene_plan_stream`. It
assumes the matching gripper and a TCP drop position; it does not solve paths
or prove reachability, collision clearance, or a successful grasp.
Provide world-coordinate `workspace_min` and `workspace_max` on tracking and
wait phases to reject objects that leave the intended pickup area before the
controller chases them. This guard is not a trajectory collision check.
Set `self_collision_enabled: true` in a follower to request Isaac articulation
self collisions; check the returned runtime setting. This alone does not prove
that every geometry pair or penetration is covered by contact reports.
`self_collision_exclusions` can name specific pairs of relative rigid-body
paths for mechanically connected parts; each exclusion reduces collision
coverage and must be justified against that exact asset.
`diagnose_overlaps: true` requests expensive discrete scene queries for that
robot's collision shapes. Query hit counts include expected connected parts
and grasping, use convex-hull approximations, and do not measure penetration;
inspect `overlap_diagnostics` and page `overlap_counts` with `run_contacts`.

Boxes, spheres and USD assets can specify a `material` mapping with `color`,
`roughness`, `metallic`, `opacity` and `emissive` to apply a USD Preview
Surface override. Material overrides can replace an asset's original appearance.

Headless scenes have no implicit lighting. A light defaults to distant; combine
a soft ambient `{"kind":"light","intensity":300,"light":{"type":"dome"}}`
with an oriented distant key, then observe every camera and tune exposure for
the actual stage. Sphere and rectangular lights are available for localized
fill using `light.type` of `sphere` or `rect`, plus `radius_m` or `width_m`
and `height_m`; `light.color` and `light.exposure` are optional. Renderer,
materials and exposure affect the actual appearance, so inspect the output.

A camera may set `record_fps` to a divisor of 60 up to 30 to record a fixed
simulation-time MP4 on the simulation host. Set `preview_fps` to a divisor of
60 up to 10 for live image polling with `scene_observe`; `run_observe` can poll
the latest sampled state while a run is active. `run_video_chunk` retrieves a
finished recording. These are not a low-latency video stream.
A camera can set `camera_orbit` to, for example, `{"center":[0,0,0.5],
"radius_m":2,"height_m":1,"duration_s":8,"turns":1}`. Its time-sampled
pose circles and looks at the center, then holds the final pose; it overrides
the static camera pose. Check sampled camera poses and rendered frames in the
actual runtime before claiming the motion worked.
`simulation_pause` and `simulation_resume` request cooperative timeline
control; poll `job_status` for acknowledgment. Saved-scene edits do not
change an already running job's frozen stage; start a new run to apply them.
Simulation jobs on the same host and account run one at a time. A job may
remain `queued` until the previous simulator exits; poll it instead of
repeatedly starting equivalent jobs. A queued job can also be paused or
cancelled, and a paused queued job does not occupy the simulator slot. If a
new scene revision makes an earlier diagnostic unnecessary, request
`job_cancel` and poll until its cancellation is confirmed before relying on
the replacement run.
Use a stable `request_id` for retries of the same `simulation_start` request;
the server returns the original job for the same parameters and rejects reuse
with different parameters. Choose a new request ID for a distinct run.
If `job_status` reports `stalled`, the process is still alive but has not
produced an observation for five minutes; inspect its log and latest state,
then cancel or investigate as appropriate rather than claiming completion.
Dynamic boxes and spheres may use `spawn_step`, `mass_kg` and `class_label`.
Experimental sequences may wait for a dynamic object using `wait_object`.
`scene_plan_stream` expands a list of classes into scheduled boxes and
per-robot cycles; each class route provides a robot ID, wait window and
phase template, using `$item` in object or required-object fields. Review its
proposed operations and apply them with the returned base revision. The plan
does not establish reachability, safe paths, routing success or throughput.
If observed items bunch up or pass a busy station, `scene_plan_interleave`
can propose a different explicit class order and interval while preserving
the order within each class. Review the schedule and all robot timings, apply
the proposal, regenerate the physical case and run again; the planner does not
predict that the new ordering will work.
If the user asks several stations to operate simultaneously, check the
completed stream verification's `parallel_steps`; an overall physical pass
alone does not establish overlap. Require at least 60 consecutive physics
steps of all requested robot cycles overlapping, unless the user specifies a
different duration. If overlap is missing, `scene_plan_synchronize` can use
the completed, intact run and its pinned stream case to propose an order and
interval from observed spawn-to-tracking delays. Supply all stream item IDs,
review and apply its operations, regenerate the case, allow enough simulation
steps for the last object, and rerun. Recheck both `parallel_steps` and every
physical and collision check. A longer interval can improve overlap: upstream
items may need extra travel time before the later items reach nearer stations.
The proposal uses one observed run, so it does not guarantee any result.
The route keys are exact: for example, a route has `{"robot_id":"arm",
"wait":{"axis":"x","minimum":0.4,"maximum":0.5,"max_steps":12000},
"cycle":[...]}`. Use the `cycle` array returned by `robot_plan_pick_cycle`;
do not rename `wait` to `wait_window` or `cycle` to `phases`. Place each wait
window near the reachable pickup position, not across the whole belt. If a
cycle uses `$slot`, supply a `slots` array with one drop position for every
item of that class. For a continuous stream schedule multiple items in each
class. Allow enough steps for the last spawn to travel from the actual source
to its station at the chosen belt speed, complete its cycle and settle.
The `wait.max_steps` is measured from when that wait phase starts, not from
when the part arrives. Estimate the first part's belt travel time from the
actual feeder exit to each pickup window, add chute travel and settling time,
convert to physics steps and leave a margin. In particular, a long chute can
make the farthest arm's first 12,000-step wait expire just before the part
arrives. Inspect the actual observed positions and controller timeout rather
than treating a zero process exit as a completed simulation.
For an existing stream, `scene_plan_retime` proposes new spawn times for an
explicit list of IDs while retaining their order and first spawn. It returns
operations and the base revision; update the conveyor speed separately and
allow enough simulation steps for the final item to reach its station.
`scene_plan_swap_routes` can propose swapping two single-class routes with
equal item counts. Review the destination bins and their labels after the swap.
`scene_plan_translate_group` proposes translating an explicit group of IDs;
optionally supply `move_targets: {"robot_id":"arm","center_xy":[x,y],
"radius_m":r}` to translate absolute waypoints in that area. Review the
returned phase indices, recheck reachable poses and inspect the actual run.
These planners do not mutate the scene until their operations are applied and
do not certify collisions, reachability, complete paths or task success.
For multiple objects in one bin, a route can provide explicit world-coordinate
`slots`; a move phase with `position: "$slot"` and optional `slot_offset`
expands to the next slot for that class. Inspect clearance and capacity before
using this proposal.
For a standard supported pick cycle on a +X conveyor, `scene_plan_stream_case`
can propose a physical evidence case using explicitly inspected inner bin
bounds, for example `bins: {"red":{"min":[x0,y0,z0],"max":[x1,y1,z1]}}`,
and a `forbidden_objects` list containing the belt and relevant obstacles.
Review those bounds and obstacle IDs, then pass the returned `case` directly
to `simulation_start` with `archive_verified_objects: true`. The case is
snapshotted before simulation and is bound to the current scene content;
regenerate it after edits. The checker uses measured contacts, lift, release,
containment, settling and retraction, and only verified items are reclaimed.
A scene-derived case can support honest live counts, but it is not an
independent acceptance case and does not certify full collision-path safety.
For long runs use `run_contacts` to page recorded contacts, and treat a
`contacts_truncated` result as incomplete evidence.
When checking supported Kawasaki RS007L, Franka Panda or UR10 models,
`scene_plan_collision_audit` proposes model-specific settings and mechanical
pair exceptions for the given robot IDs, including flattened downloads whose
generated profile points to that same asset. Inspect the exact assets and every
exclusion. Include every robot referenced by the stream case, even when only
one route changed; otherwise the audit cannot cover the whole case. Apply the
proposed operations, then regenerate the scene-derived
stream case and add the proposed `collision_policy` to that case before
starting the run. Check `collision_audit` in `run_verify`; missing coverage or
unexpected overlap must fail the check. This expensive discrete per-step
audit uses convex-hull approximations; it excludes the specified mechanical
pairs and assigned grasps, and cannot certify swept volumes or real robots.
With case-checked object archiving enabled, sampled `verified_counts` reflect
only objects checked and archived against the pinned case, not a final success
rate. A scene-derived case is not independent acceptance; use a separately
frozen case and the ledger for independent acceptance outcomes.
A `counter` with `counter: {"source":"spawned"}` displays observed spawn
counts; `{"source":"verified_archives","class_label":"red"}` displays
only case-checked archived red objects and remains hidden when no
archive case is active. Counters use three digits by default and show dashes
on overflow. A static non-colliding box with `indicator: {"robot_id":"arm"}`
shows that follower's observed controller phase: waiting amber, active green,
complete blue, error red. Controller phase is not proof of physical success.
Robot contact records can include the minimum separation at reported PhysX
contact points. They do not prove the absence of unreported interpenetration.
Use `run_verify_lock` to recheck recorded input hashes; a passing lock check
does not certify the whole runtime or the physical task.
When an independent acceptance case exists, pass its server-side path to
`simulation_start` to snapshot it before running, then use `run_verify` on the
completed job. A single-case pass is not a multi-seed or full collision audit.

Call `scene_validate`; its current checks are schema checks, not collision,
reachability, or robot-control certification. Use `simulation_start`, poll
`job_status`, and use `scene_observe` for each named camera in the completed
run. Inspect actual rendered images and sampled physics positions, revise the
scene when evidence supports an improvement, and run again. Explicitly report
unverified capabilities, failed jobs, missing evidence, and approximate or
unsupported mechanisms; do not infer a successful physical task from a state
machine or fabricated counts. Use `scene_export` when a USD file is requested.
