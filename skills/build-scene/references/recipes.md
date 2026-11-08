# Editable role recipes

List available recipes with `simscene recipe list`. `scene_compile_recipe`
reads the current scene and returns `base_revision`, ordinary `operations`,
requirements, ports and warnings. It makes no edits or runtime commands. Apply
the whole batch with one `scene_apply` and a unique request ID. A revision
conflict requires rereading/recompiling; avoid replaying a stale placement.

`gravity_drop_v1` requires `payload` prepared as `rigid_prop_v1` and `support`
as `static_fixture_v1`. Each binding contains only `asset_path` and the pinned
`asset_binding`. Choose the support's measured named `support_surface` and set
`origin_m`, `count`, `spacing_m`, `drop_height_m`, optional normalized payload
orientation and world `keepout_bounds`. Compilation checks the rotated full
payload footprint, excluded support rectangles and the drop sweep. A larger
asset, raised table or extra instances changes the proposal and still needs a
physical trial. Geometric clearance is not a dynamic stability guarantee.

`passive_door_bridge_v1` expands the existing editable hinge-panel module.
Parameters include `origin`, metric length/width/thickness and raised angle.
It is unlatched and falls under gravity. To claim a triggered bridge, add a
real retainer and payload handoff at its returned ports, then verify the contact
and locked-door negative control. Do not replace this mechanism with a timed
pose update. See [passive production](passive-production.md) for domino modules
and first-failed-handoff diagnosis.

Optional `asset_generate` accepts a shipped fixed template and structured
parameters, not arbitrary programs. Its completed generated AssetRef enters
the same plan/prepare/verify workflow. The generator needs an explicitly
configured independent runtime. Generation resource limits are not a network
or filesystem sandbox; external program execution is unavailable.
