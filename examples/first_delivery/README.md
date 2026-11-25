# First delivery · one gravity drop

Use an installed development package that includes this example. The fixed input
is one GSO scan of a fondant box. The scene uses editable SimScene boxes for its
worktop, stand and floor. The model is fetched on demand with its source notice.
The prepared 120 mm size and 0.12 kg mass are experimental parameters.

## Run on the simulation host

Use a Python with USD bindings, the tested Isaac Sim 6.2.0-rc.14 runtime,
Node.js 22.23.2 with npm, and FFmpeg with libx264 and zscale. Supply paths to an
installed portable plugin and the matching wheel. Use a directory you own for
this example's state and cache.

~~~sh
export PLUGIN=/absolute/path/to/installed/simscene
export WHEEL=/absolute/path/to/rosclaw_simscene-0.2.0.dev2-py3-none-any.whl
export SIMSCENE_ISAAC_PYTHON=/absolute/path/to/isaac-sim/python.sh
export WORK="$PWD/first-delivery-local"
export SIMSCENE_HOME="$WORK/state"
export SIMSCENE_CACHE="$WORK/source-cache"
export SIMSCENE_V2_CONFIG="$WORK/v2.json"
export SIMSCENE_GLTF_TRANSFORM_PREFIX="$WORK/decoder"
export PYTHONPATH="$PLUGIN/server/vendor"

mkdir "$WORK"
python3 -m simscene.cli asset setup-decoder --output "$SIMSCENE_GLTF_TRANSFORM_PREFIX"
python3 -m simscene.cli asset probe
python3 "$PLUGIN/experiments/run_first_delivery.py" --wheel "$WHEEL" --output "$WORK/output"
~~~

Setup and probing are reusable within this environment. Repeat the last command
with a new output directory for another run. An interrupted invocation with a
saved physics request can use the same output directory, wheel and flags plus
`--resume`. Add `--collect-only` during budget reserve to query and wait on
existing jobs. Preparation that was interrupted before the saved physics
request needs a new output directory. Missing runtime details are recorded with
the failing MCP request in `mcp-calls/`.

## Read and review the results

- `scene.json` and `case.json` contain the applied scene and frozen case.
- `physical-check.json` checks measurable drop, direct worktop contact, full
  bounds containment and two seconds of settling, with input and output hashes.
- `first-delivery.mp4`, its `.edit.json` and `video-inspection.json` contain the
  native 4-second, 1080p30 clip, original run mapping and decoded samples.
- `delivery.json` records engineering checks and leaves visual review pending.

Play the complete MP4 and check that the falling box, contact and settled result
are visible. Save a JSON review with `reviewer`, `decision` (`accept` or
`change_needed`), the `video_sha256` in `delivery.json` and
`reviewed_windows`. Cover playback seconds 0–0.5 and 2–4 with entries containing
`start_s`, `end_s` and a concrete `observation`. You can use a single 0–4
entry after reviewing the whole clip.

~~~sh
python3 "$PLUGIN/experiments/run_first_delivery.py" --output "$WORK/output" --review "$WORK/review.json"
~~~

The reviewed receipt binds the declaration to the checked movie and can reach
`ready_for_submission`. The eventual submission belongs to the client or host
that requested the work. This example verifies a fixed asset and configuration.

## Qualified host-assisted Codex route

From the source checkout, a host with a configured Codex CLI login can use
the first-delivery qualification driver. Use a fresh attempt directory and
the same runtime setup as above.

~~~sh
python3 experiments/qualify_first_delivery.py --plugin "$PLUGIN" --wheel "$WHEEL" \
  --output "$WORK/qualification" --model YOUR_CODEX_MODEL
~~~

The host admits one discovery turn, runs the installed MCP workflow outside
model turns, and admits a separate visual review only after physical and media
checks pass. It preserves observed token usage and writes a submission only
within the wall and token limits. The allowance governs client turn admission
and observed use. Reports cannot enforce unreported in-flight provider usage.
Visual qualification uses two ordered frame strips tied to the checked video.

The export destination should be on a local filesystem that supports hard
links. After worker or host failure, use the job record as the completion
authority. An uncertain status leaves any remaining files available for
diagnosis.
