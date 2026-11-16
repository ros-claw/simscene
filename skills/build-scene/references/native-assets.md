# Native joints, containers and illumination

Use explicit catalog source IDs when the role requires an optional provider:
`usdcraft` for the admitted native USD manifest, `polyhaven` for the configured
HDRI IDs. Default discovery combines NVIDIA search, ABO and GSO. Central offers
additional owner locators, with individual package/licensing admission still
required. `artvip` is an explicitly selected experimental source with one
curated `door002` candidate, not a full ArtVIP index. Source admission never
grants every model a physical pass.

`articulated_prop_v1` preserves an existing canonical metre/Z-up single-DOF
graph. Use `source_physics_policy: preserve_valid`, `scale_mode: preserve`,
`collision_method: preserve`, and explicit `proxy_tolerance_m`. Unsupported
topology, missing mass and joint/inertia scaling fail rather than synthesizing
a hinge. The scene asset requires `dynamic: true` and its exact two-key prepared
binding. Native auto-computed inertia is checked through actual cooked readback.

The curated ArtVIP door needs an opt-in `repair_explicit` preparation: its
source links have no authored total mass, seven colliders bind density-bearing
materials, and its source acceleration drive has unbounded effort. Supply and
record each experimental mass, affected material-density override and drive
neutralization in `native_physics_repairs` (`missing_masses_kg`,
`material_density_overrides`, `neutralize_drives` and a `reason`). Do not claim
those assumptions are source measurements or
silently apply them to another model; inspect its source first.
The selected object's exact repair assumptions and source pins are available
on demand in `examples/artvip_door/assets.lock.json` and its `case.json`.
Resolve `examples/` against the plugin root: for a skill copied into a project,
read the `build-scene/.simscene-plugin-root` marker; otherwise use the root
containing the `skills/` directory.

`articulated_prop_v2` preserves an admitted three-link tree with two finite-limit
scalar hinge/slider joints. It currently accepts `preserve_valid` source physics
only and rejects coupled, geared, mimic or tendon structures. Use the actual
manifest joint IDs and body paths, not the source joint count, and request
strict per-step observations. For the selected USDCraft two-drawer sample, use a
frozen `simscene.articulated_asset_two_joint.v1` case and `run_verify`; a
matched control omitting the second drive uses mode
`missing_second_joint_drive`, the control job ID and positive reference job ID.
The tested two-slider result does not certify other axes or assets.
The tested cabinet is `ds_R022_02`; inspect its pinned
`examples/usdcraft_two_drawer/assets.lock.json` and `case.json` when needed.
Replace template binding markers with the newly prepared manifest and source
pins before starting the new run.

For a driven trial, add ordinary object `mechanism.commands`:

```json
{"joint_id":"main","trigger":{"type":"at_step","physics_step":0},
 "target_position":0.5,"position_unit":"rad","stiffness":400,
 "damping":12,"max_effort":22}
```

Copy joint IDs/limits from the manifest. Application units are rad for hinges,
metres for sliders, with SI gains/effort; authoring handles the USD angular
conversion. This is an explicit scheduled drive, distinct from a physical
contact trigger. An empty command list preserves the source's existing drive
configuration. Read actual joint motion and links; a target alone is no result.
Primitive `kind: joint` remains the passive geometry API.

`container_v1` uses an explicit `container_proxy`: metric interior min/max,
wall/floor thickness, upward `opening_axis: +Z`, intended `test_object_size_m`
and `geometry_note`. Use `replace_visual_only` and `box_proxy`. The static
scene object preserves the prepared binding. Verify complete-object opening
passage, floor contact, containment and settling, with a closed-top control.
This is measured wall preparation rather than automatic container recognition.

`environment_v1` wraps a selected HDRI as a self-contained dome light. Its
parameters are bounded `intensity`, `exposure` and `texture_format: latlong`.
The scene asset has `dynamic: false`; keep its lighting preserved. It has no
body or geometric bounds, so exclude it from measured worktops/camera subjects.
Material-map metadata/acquisition does not imply a geometry preparation profile.

For the shipped `open_receiver_v1` generation template, use explicit cavity
and wall dimensions, then the same container preparation and control. For a
native prop, preserve original source materials; diagnose unresolved materials
from actual frames rather than recoloring everything to hide them.
