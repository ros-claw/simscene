# Capture and editing interface

Apply global configuration through `scene_apply`:
```json
{"op":"set_presentation","presentation":{"profile":"technical_showcase_1080p","capture":{"anti_aliasing":"dlss_quality","depth_of_field":false,"motion_blur":false,"exposure_mode":"manual","exposure_ev":0},"output":{"codec":"h264","crf":18,"preset":"medium","pixel_format":"yuv420p"},"budget":{"max_cameras":2,"max_recording_bytes":8589934592,"min_free_bytes":2147483648},"diagnostics":{"png_seconds":0,"keyframe_interval_s":10}}}
```
Profiles: preview (640×360,2fps), technical_showcase_1080p (1920×1080,30fps),
technical_showcase_4k (3840×2160,30fps; budget permitting). A profile sets a
recording rate for every camera unless its `record_fps` overrides it. Remove
unused cameras before applying a two-camera profile. Existing scenes without
presentation keep 640×480 and explicit legacy rates.

`capture` can override resolution/fps, renderer (RealTimePathTracing or
PathTracing), and DLSS Quality or DLAA. Render settings are global; camera
resolution/optics/encoding can vary. Native output order is [width,height],
converted to the sensor's (height,width) internally. Even sizes, 64..4096.
`record_fps` divides 60 and is at most30. `preview_fps` divides60 and is at most10.

Camera object settings:
```json
{"kind":"camera","record_fps":30,"preview_fps":1,"camera":{"resolution":[1920,1080],"focal_length_mm":35,"horizontal_aperture_mm":36,"focus_distance_m":2,"f_stop":0,"clipping_range_m":[0.01,1000],"capture_window":{"start_step":2820,"end_step":3420}}}
```
Start/end must align with frame intervals. The start is exclusive: above records
steps2822..3420,300frames,10seconds at30fps. Video frame0 maps to simulation
47.0333s, not simulation0. Omit window for full-run recording. Capture manifest
rows include frame_id,camera_id,physics_step,sim_time_s,video_time_s,width,height
and optional raw_png. First PNG plus periodic keyframes are saved; diagnostic
full PNG capture is optional and limited to10 simulated seconds.

Lens lengths in mm convert to USD tenths of metre-stage units (mm/100), while
focus/clipping distances are metres. The horizontal aperture and resolution
set vertical aperture/aspect. Focal length changes FOV; focus distance and f-stop
control depth of field. Render DOF off forces USD f-stop0.

Recording budgets cover video/PNG/manifest outputs separately from asset cache.
A budget violation is a failed recording, never silent frame loss. Raw RGB
annotator bytes are display-referred sRGB; the encoder transforms transfer and
matrix to limited-range BT.709 SDR. Source/encoded visual comparisons must
account for that conversion and lossy compression.

The dev2 encoder requires FFmpeg's `zscale`: packed RGB is first rearranged to
planar GBR, then explicitly converted to BT.709. Representative/composed PNGs
are converted back to display sRGB. This avoids the old implicit RGB→YUV step
before a GBR override; compare matching frames, not differently timed previews.

`video_inspect(path, output_dir, representative_count, job_id, camera)` probes,
checks native frame provenance and writes decoded representative frames. Final
edited files have an adjacent `.edit.json` source/time map; inspect that in
addition to decoded footage. Codec tags alone do not prove native capture.

`video_export` accepts `font_file` for on-screen titles and records its SHA256.
CJK titles use the installed Noto CJK font when available; otherwise supply a
CJK-capable server-side font. Decode and inspect real text: an encode can
succeed while a missing font renders squares.

For editable camera motion use `camera_path:[{time_s:0,position:[x,y,z],target:[x,y,z]},...]`
with increasing times and two to200 nodes. The exporter authors USD camera
poses at60 timecodes/second; positions interpolate and rotations keep quaternion
sign continuity. Hold duplicate poses across action intervals and cut out
unwanted travel. A camera cannot use both camera_path and camera_orbit.

Red error materials can indicate a missing MDL module, even if USD references
resolve. Acquisition now also scans relative MDL imports and texture literals
under the same source-origin and cache bounds. Inspect shader errors and rerun
a native preview after repairs. Missing builtin OmniPBR is runtime-provided only
when the configured Isaac installation supplies that exact material. Do not
hide broken shaders by uniformly recoloring an imported asset.
