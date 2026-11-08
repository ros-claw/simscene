# Editable scene recipes

Recipes compile measured roles and bounded parameters into ordinary scene
operations. They do not download assets, edit the scene, drive physics or grant
an acceptance result. List them with `simscene recipe list`.

`gravity_drop_v1` accepts a prepared `payload` (`rigid_prop_v1`) and `support`
(`static_fixture_v1`). A role binding contains `asset_path` and exactly the
two-key `asset_binding` from preparation. The compiler verifies package hashes,
uses the normalized visual bounds, rotates the entire payload footprint, checks
the named support region and exclusions, and rejects drop sweeps intersecting
explicit world keepouts. It supports one to eight independent instances.

```json
{
  "prefix": "cell",
  "support_surface": "top",
  "origin_m": [0, 0, 0.5],
  "count": 2,
  "spacing_m": 0.025,
  "drop_height_m": 0.25,
  "payload_orientation_wxyz": [0.5, 0.5, 0.5, 0.5]
}
```

Use `scene_compile_recipe(scene_id, recipe_id, parameters, bindings)` through
MCP, or compile files without editing:

```bash
simscene recipe compile gravity_drop_v1 --parameters parameters.json \
  --bindings roles.json --scene scene.json --output new-plan.json
```

Apply the returned `operations` as one `scene_apply` batch at `base_revision`.
The output carries exact preparation requirements, ports and `recipe_hash`.
Changed dimensions, support height, quantity or preparation pins change the
proposal. A revision conflict fails the ordinary transaction without partially
placing objects. Recompile against the current scene before retrying.

`passive_door_bridge_v1` exposes the existing primitive hinge-panel compiler
through the same interface. It accepts metric door parameters, `origin` and
orientation, and returns input/output/retainer ports. Its panel is unlatched;
add a real retainer if a previous action must trigger it. No scheduled release
is inserted. This recipe is separate from imported native articulated assets.

Measure the final scene with `scene_measure`, freeze a new case, and run a local
positive and appropriate negative control. Geometric fit does not establish
settling, contact, load capacity or causality. Compilation remains
`physics_tested: false` even when a previous instantiation passed.
