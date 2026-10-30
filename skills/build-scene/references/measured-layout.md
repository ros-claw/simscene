# Measured asset layouts

`scene_measure(scene_id, ids)` returns world bounds, dimensions and bottom-center
anchors, using the same unit/up-axis conversion and selected variants as USD
export. Position means the imported root origin; it need not be at the center.

On a support object declare e.g.:
```json
{"support_surfaces":{"worktop":{"min_xy":[-1,-0.4],"max_xy":[1,0.4],"z_m":0.9,"exclude":[{"min_xy":[0.7,0.2],"max_xy":[1,0.4]}]}}}
```
Coordinates are normalized local metres, after unit/axis conversion, before
the object's world pose. Inspect geometry to establish the worktop height and
usable region. Tray interiors and shelf boards need separate explicit regions;
outer bounds do not establish support. Horizontal yaw rotation is supported;
tilted support regions require another stability model and are rejected.

```json
{"op":"place_on","id":"part","support":"bench","support_surface":"worktop","offset_xy":[0.2,0],"gap_m":0}
```
Offsets are relative to the region center in support-local XY. The measured
bottom-center is placed on the region; a corner-based conservative bounds check
rejects overhang and excluded rectangles. Optional `orientation_wxyz` sets world
orientation before measuring. `avoid_ids`, `clearance_m`, and world metre
`keepout_bounds:[{min:[x,y,z],max:[x,y,z]}]` reject reserved-space intrusion.
This is geometric placement, not a dynamic stability proof.

`arrange_grid` uses `ids`, `support`, optional `support_surface`, `columns`,
`gap_m` (between cells), `offset_xy`, optional `vertical_gap_m`, and the same
clearance fields. Row/column dimensions come from measured footprints.
`arrange_line` supports imported and rotated models, with a world bbox-center
`origin`, world `axis`, and center `spacing`; old unrotated primitive behavior
retains its root-origin convention. `align` uses `ids`, `axis`, `edge` of
min/max/center, and `value_m`. For explicit group translation and robot waypoint
edits use `scene_plan_translate_group`, review operations and rerun.

Arrange a tray on a bench first, then the parts inside its explicit interior.
Reinspect supports after rotations or relative moves. Use observed robot and
held-object activity to reserve working volumes, and visually inspect critical
camera sightlines; AABB clearance alone cannot certify visibility or safety.
Non-colliding props still must remain outside visible motion paths. Add any
new collision-enabled fixture near the task to the physical checks.

`asset_physics:"visual_only"` explicitly imports a prop as static visual
geometry, removing rigid/collision/articulation schemas and disabling joints in
the composed scene, without changing the source. This is not rigid-body/grasp
adaptation. Leave controller assets at their default `preserve` policy.
If root unit/axis metadata is missing or demonstrably incorrect, `asset_metrics`
can record explicit `meters_per_unit`, `up_axis`, and an inspection `reason`.
Do not guess units from a filename; retain source observations and the reason
with the scene. Measured layout and export both use these explicit metrics.

An imported asset can contain lights. If native preview reveals a spotlight or
embedded illuminator overwhelming a task, inspect the prim and explicitly set
`asset_lights:"disabled"` on that asset. This authors light intensity0 in the
composed scene; original source files and robot physics remain unchanged.
The default is `preserve`; do not disable unrelated lighting indiscriminately.
