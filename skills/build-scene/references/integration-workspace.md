# Fixed integration examples

Read `simscene://recipes/examples` or `simscene recipe list` to discover
model-free examples. These are fixed scene inputs, separate from the role
recipes accepted by `scene_compile_recipe`. The registry describes earlier
evidence for selected configurations; it is not a pass for a new run.

Choose the closest path:

* **Reproduce:** use `automatic_cabinet_layout` for the single-hinge USDCraft
  cabinet, two ABO notebook instances and one GSO box. The lock pins source
  revisions, preparation parameters and experimental 0.12 kg prop masses;
  the case and supplemental checks fix the earlier 600-step/60 Hz predicates.
* **Modify:** keep the selected source and role bindings, measure the actual
  support and motion keepout, then freeze a new case and run the changed scene.
  A changed asset, placement, drive or preparation cannot inherit an old pass.
* **Explore:** make a small physical test first. A manifest's joint count,
  generator output or geometrically feasible layout does not establish motion,
  support, stability or a contact-triggered event.

Other examples cover one explicitly repaired `artvip_door`, the scheduled
`usdcraft_two_drawer` with its missing-second-drive control, and the optional
`usdcraft_sdk_guide` two-size comparison. Their locks and case files record
the exact assumptions. They do not certify every object in those sources.

`integration_workspace` is an experimental two-drawer and independent GSO
payload pair with ABO props. The control removes all lower-drawer commands;
the upper drive and everything else remain matched. Its case uses native joint
readback, actual rigid-body poses, collision geometry, observed contact callbacks
and a frozen support region. Prepare the three pinned roles, freeze a fresh
case and run each recipe independently before invoking its `check.py`. A
contact callback does not certify the absence of all penetration, and the
scheduled joint drives are not passive triggers. New results require their own
physical and visual review.

The package root is the value in a copied project's
`build-scene/.simscene-plugin-root`; otherwise use the root that contains
`server/`, `skills/` and `examples/`. Each `examples/<id>/` contains the
listed lock, ordinary operations, case and checker. Source model payloads are
not bundled. Search metadata with `catalog_search`, then use `asset_plan` and
`asset_prepare` only for selected assets; retain the returned job IDs and
prepared bindings. Record transfer categories rather than assuming a warm
cache proves a cold download. Check per-asset license and missing dependencies.

For shell-capable clients, the installed package also contains the same small
helpers as the source tree: `experiments/acquire_recipe_assets.py`,
`experiments/apply_scene_recipe.py`, `experiments/freeze_recipe_case.py` and
`experiments/check_motion_clearance.py`. For an MCP workflow use
`apply_scene_recipe.py --operations-only --asset-catalog CATALOG.json
--asset-lock LOCK.json --save-directory NEW_DIRECTORY RECIPE.json` to resolve
the verified bindings without editing the scene. Submit the resulting
`resolved-operations.json` with `scene_apply` and its current revision.
Run them with the matching `server/vendor` first on `PYTHONPATH` and a host
Python with the required USD bindings. The acquire helper invokes the ordinary
durable jobs directly; a workflow specifically requiring MCP coverage must
perform and record those corresponding MCP calls instead. The helpers do not
turn preparation or scene construction into a physical acceptance.

For the USDCraft hinge or two-drawer examples, the registry names a specific
`motion_profile`. Save the current `scene_get` result and call the packaged
`check_motion_clearance.py` with that scene, owner ID, profile and a new output
path. The matching vendor directory must be first on `PYTHONPATH`. With no
`--object` arguments the result is `not_checked` and provides conservative
world `keepout_bounds`; pass those bounds to `scene_plan_layout` with 0.05 m
clearance. For the unchanged fixed cabinet pose, the example's larger
`supplemental-checks.json` `reserved_volume` also encloses that calculated
envelope; verify containment before reusing it to reproduce the original seed
and placement. After applying its operations, save the new scene and call the helper
again with each external object as a repeated `--object` argument. Stop if the
result is `conflict` or `error`; the owner is deliberately excluded. The result
pins the scene content and revision, the prepared source and the measured
profile. Changed joint or collider geometry is unsupported, not silently clear.

After applying operations at the current scene revision, measure the resulting
world bounds, preserve collisions and reserve the mechanism's working region.
Freeze the case against the new bindings before `simulation_start`, wait for
the same durable job, inspect real frames and observations, then run the
appropriate checker with the same installed package and USD environment.
Archive the case, inputs, physical result, video mapping and an actual visual
review. Scheduled commands are not evidence of contact-triggered motion.

For the fixed cabinet example, read `simscene://runtime/identity` from the
actual MCP session and save `{"runtime_identity": RESPONSE, "wheel_path":
"/path/to/the/builds/wheel.whl"}`. Keep the complete response, not just the
version. The portable installation's `server/build-info.json` records the
source commit, clean state and wheel digest. Isaac, layout and generator
runtimes have separate identities; the MCP interpreter is not the Isaac worker.

After a real inspection, an attributed visual review may be saved separately
with the video SHA256, `reviewer`, `decision` (`accept` or `change_needed`) and
`reviewed_windows` (start/end seconds and actual observation). Run installed
`experiments/assemble_integration_receipt.py --help` to combine the scene,
frozen case, run, recipe, identity, video, edit mapping and this review. The
helper reports missing, physical, media and visual states separately. It never
authors the visual review, signs evidence or proves a deadline. The presence
of a receipt is not itself a pass.
