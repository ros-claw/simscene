# Native joints, containers and illumination

Use explicit catalog source IDs when the role requires an optional provider:
`usdcraft` for the admitted native USD manifest, `polyhaven` for the configured
HDRI IDs. Default discovery combines NVIDIA search, ABO and GSO. Central offers
additional owner locators, with individual package/licensing admission still
required. Source admission never grants every model a physical pass.

`articulated_prop_v1` preserves an existing canonical metre/Z-up single-DOF
graph. Use `source_physics_policy: preserve_valid`, `scale_mode: preserve`,
`collision_method: preserve`, and explicit `proxy_tolerance_m`. Unsupported
topology, missing mass and joint/inertia scaling fail rather than synthesizing
a hinge. The scene asset requires `dynamic: true` and its exact two-key prepared
binding. Native auto-computed inertia is checked through actual cooked readback.

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
