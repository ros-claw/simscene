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
or filesystem sandbox; the interface does not accept arbitrary submitted programs.

For the optional USDCraft SDK, use `usdcraft_sdk_guide_plate_v1` with numeric
`length_m`, `width_m` and `thickness_m`; inspect and prepare the result for its
actual role. Probe a separately installed reviewed SDK with
`simscene generate probe --backend usdcraft-sdk --python <python> --checkout
<clean-checkout> --output <new-runtime.json>` and set
`usdcraft_generation_runtime` in the V2 configuration. Python, third-party
dependencies and local job storage must be trusted. Regeneration from a
portable lock requires the same template, runtime intent and output hashes.
The tested static guide uses an explicitly declared replacement box proxy;
generation and preparation are not a physical pass.
Length is 0.05–2 m, width 0.02–0.8 m and thickness 0.002–0.08 m;
thickness must be smaller than length and width. For measured preparation
parameters, source hashes and the two-size comparison, inspect the
`examples/usdcraft_sdk_guide/assets.lock.json` and `case.json` on demand. Resolve
`examples/` against the plugin root; a copied project skill records that root in
`build-scene/.simscene-plugin-root`.
This case uses the accompanying `check_pair.py`, not a built-in `run_verify`
case type. Run it with Python configured to import the plugin's `simscene`
package and USD bindings. Freeze binding markers before running both scenes;
examine the actual output and complete input/evidence locks.
