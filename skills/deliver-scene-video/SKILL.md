---
name: deliver-scene-video
description: Plan cameras, record native simulation footage, inspect clarity and motion, and edit traceable videos of SimScene scenes. Use for real simulation video delivery, not synthetic or illustrated footage.
---

Read the scene/revision, subjects, actions, requested style, duration and budget.
Use the existing SimScene execution tools; recordings run on the simulation
host. A saved MP4 or successful encode alone does not establish good visuals.

Use `scene_measure` for subjects and explicit action-region bounds, then
`scene_plan_presentation` to propose overview/detail cameras. It returns scene
operations, not a finished visual design. Review existing cameras against the
recording budget, and preserve useful lighting and asset materials. Apply the
proposal with `scene_apply`, preview, and inspect with `scene_observe` before
committing to a long recording. Reframe around actions; avoid enlarging a distant
low-resolution overview into a grasp close-up.

Read [capture configuration](references/capture.md) for schema, optical units,
render presets, bounded recording and simulation-time windows. Formal delivery
defaults to native 1920×1080, 30 captured frames/simulation second, locked manual
exposure, depth of field and motion blur off. Keep 60 Hz physics. Render settings
are read back after stage/sensor startup and at completion; unavailable or
overridden requested settings must surface as errors.

First record a 5–10 second diagnostic action. Compare native raw PNG, composed
frame and decoded MP4 frame at 100% pixel scale. Inspect white/metal highlights,
material loading, silhouette, subject occupancy, contact and release visibility.
Use `video_inspect` with job_id/camera to bind a source clip to its run and check
dimensions and physics-frame continuity. It returns representative frame paths;
open them, and inspect a real moving sequence as well. Overall image sharpness
or pixel duplication alone is not an acceptance criterion.

Record the required full task with one or two cameras before adding more;
offline rendering may be slower than real time, but capture cannot skip
simulation moments. Check physical outcomes separately with `run_verify` and
input/evidence locks. Retain a continuous fixed-view source recording. Editing
does not turn an incomplete task into a passed physical case.

Use `run_presentation_events` to resolve semantic events from the frozen run
spec and actual transitions/spawns. Select shots by object IDs and observable
actions; never hard-code robot names, phase indices or assumed event seconds.
When an action spans several phases include approach, contact, lift, release
and settling as relevant. Same-run temporal overlap is required for claims of
simultaneous work. Events propose shot locations; they do not prove success.

`video_export` accepts real source segments with run_directory, camera,
start_sim_time_s, end_sim_time_s, optional speed and title. It checks capture and
run integrity, retains native cadence, and saves source hashes and the edit's
simulation/playback time map. Use native sources and explicit aspect-preserving
layout. Upscaling requires opt-in and is disclosed. A 6fps source cannot become
30 distinct captures per second through encoding. Label speed changes and
identify different runs in the segment records.

Inspect the final video's representative frames and moving clips, including
all key actions and cuts. Read the export map and actual ffprobe specifications;
review subtitles against measured run results. Deliver the editable scene,
MP4, continuous source references, raw/decoded keyframes, capture/render/encoding
settings, edit map and physical verification. Record unresolved visual issues,
failed attempts and anything not actually checked, including external player
transcoding when no platform upload was performed.
