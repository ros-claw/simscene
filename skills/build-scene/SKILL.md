---
name: build-scene
description: Discover online simulation assets, compose editable scenes with measured support relationships, run Isaac Sim and improve the result from camera and physical observations.
---

Choose reproduction, modification or original construction first. Reproduce a
locked recipe directly; test changed interfaces locally; build new mechanisms
on a small bench before assembling the full scene. For editable parameter
modules, compact first-handoff diagnosis and machine-side waiting, read
[passive production](references/passive-production.md). Use its scripts when
they remove repeated geometry or log-reading work; unsupported cases remain
explicit rather than inheriting a previous example's physical pass.

Use `environment_probe` to establish the available backend. Configure a supplied
Isaac launcher with `environment_configure` when needed. Start with
`catalog_search`: it returns bounded metadata, critical gaps and detail links;
there is no full-library download or index deployment prerequisite. Read
[catalog selection](references/catalog.md) when choosing sources or encountering
empty results, license gaps, codecs or candidates from `catalog_discover`.

For imported physical objects, read [asset preparation](references/preparation.md).
Select an immutable AssetRef, plan its role, prepare only that selection, and
retain its manifest pin. A visual asset and an actual moving rigid body need
different preparation. Do not remove `dynamic` to hide an invalid body binding.
Legacy `asset_search` / `asset_inspect` / `asset_acquire` remain available for
reviewed native USD compatibility routes; their availability does not imply
that every asset is ready for the new preparation profiles.

Before writing repeated geometry, read [role recipes](references/recipes.md).
Compile a small editable batch, apply it at its returned revision, and locally
verify the changed interface. A compiled recipe is a construction proposal,
not a physical pass. Missing roles require compatible alternatives or explicit
preparation, rather than a silent primitive substitution for an imported actor.

Use `scene_open`, `scene_get`, and atomic `scene_apply` with current revision and
unique request ID. Kinds: box, sphere, cylinder, capsule, compound, joint, asset, camera, light, counter. Positions
are metres, orientation is normalized wxyz. Example addition:
`{"op":"add","id":"part","object":{"kind":"box","size":[.1,.1,.1]}}`.
Update uses `changes`; IDs belong on operations. Handle revision conflicts by
reading the scene. Never omit a requested unsupported behavior silently.

For passive hinges, sliders, compound household objects and physical segmented
ropes, read [passive mechanisms](references/passive-mechanisms.md). Keep the
backend experimental until actual paired mechanism trials pass.

For a passive force-path acceptance case, read
[network verification](references/passive-network-verification.md). A separate
gravity-loaded support pad requires the explicit v2 declaration and
[typed support evidence](references/structural-loads-verification.md); never
invent an activation or count structural motion as task progress. Freeze the
software, geometry, case and controls before formal runs, and retain their
original versions when extending the supported physical model.

For spatial composition, read [measured layout](references/measured-layout.md).
Measure imported models in their final orientation with `scene_measure`.
Declare usable support regions rather than treating an external bbox as a
worktop. Place/arrange objects with ordinary operations, review final world
bounds, and reserve working and camera sightline space. Separate static props
from colliding fixtures and dynamic task objects. Preserve original asset
materials by default; selective `material_overrides` use relative prim paths.

Headless stages need lights. Use an existing dome and a restrained key/fill
setup, then inspect highlights, textures and shadows from the actual cameras.
For formal video use `deliver-scene-video`, `scene_plan_presentation`,
`video_export` and `video_inspect`; everyday previews can stay inexpensive.
Do not infer appearance from a successful export or schema validation.

For supported robot profiles, tracking, streams, measured counters, route edits
and collision evidence, read [robot streams](references/robot-streams.md).
Those experimental mechanisms are calibrated to supported models and small
cubes; arbitrary industrial props are not automatically graspable workpieces.

Use `scene_validate`, start real simulation, poll status and inspect each camera
with `scene_observe`. Use measured state and contacts to correct layouts or
behaviors, then rerun. Saved edits do not modify a running frozen job. Jobs are
serialized per user/host; queued jobs are not launch failures. Use stable
`simulation_start.request_id` for retries and a new ID for a changed run.
`stalled` means the process is alive without recent observations; inspect its
log before continuing. Pause/resume and cancellation require acknowledgment.

For an acceptance case, snapshot it before running and evaluate with
`run_verify`. Recheck `run_verify_lock` and evidence integrity. Integrity,
controller completion and physical task success are distinct results. Report
actual passes, failures and unrun checks; preserve failed attempts. A fixed
scene's repeated seeds are not randomized-layout generalization evidence.
