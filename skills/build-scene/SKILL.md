---
name: build-scene
description: Discover online simulation assets, compose editable scenes with measured support relationships, run Isaac Sim and improve the result from camera and physical observations.
---

Use `environment_probe` to establish the available backend. Configure a supplied
Isaac launcher or non-secret host defaults with `environment_configure` when
needed. Default discovery is the hosted NVIDIA USD Search; there is no full
library download or index deployment prerequisite. Search metadata/previews
first, acquire selected assets only, and keep the assets on the simulation host.

Use `asset_search` with short object descriptions. Inspect candidates and preview
with `asset_thumbnail`; prefer a hit's `thumbnail_image_key` where provided.
Check captions, match signals, source and actual object identity: a scene that
contains a tool is not a standalone tool, and indexed captions can be wrong.
Preserve the query and selected hit in the delivery records. If a desired model
is absent, search related categories and explain the concrete substitute.
`huggingface_search_datasets` / `huggingface_list_assets` extend discovery;
acquisition requires a pinned full commit SHA and a selected USD path.

Call `asset_inspect` before `asset_acquire`, then poll `job_status`. Check the
returned dependency status; use `result.root` as `asset_path`. Do not treat
unresolved packages as usable. `resolved_with_runtime` means the configured
Isaac installation supplies listed materials, not a standalone portable model.
Inspect selected assets locally for units, axes, variants, physical schemas and
bounds. Respect asset licenses. Evicted selected assets can be restored from
retained content fingerprints; changed source content requires a new selection.
Wait for cache acquisitions to finish before run snapshots.

Use `scene_open`, `scene_get`, and atomic `scene_apply` with current revision and
unique request ID. Kinds: box, sphere, asset, camera, light, counter. Positions
are metres, orientation is normalized wxyz. Example addition:
`{"op":"add","id":"part","object":{"kind":"box","size":[.1,.1,.1]}}`.
Update uses `changes`; IDs belong on operations. Handle revision conflicts by
reading the scene. Never omit a requested unsupported behavior silently.

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
