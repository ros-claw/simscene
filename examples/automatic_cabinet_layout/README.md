# Automatically placed props and a native cabinet hinge

This editable example places two ABO notebooks and a GSO box on a primitive
worktable, alongside a USDCraft lift-up cabinet with its original two-link,
single-hinge structure. The three prop positions came from the optional
`scene_synthesizer` planner with seed 42 and an explicit cabinet-door keepout.
The cabinet is driven by a declared schedule; this is not a contact-triggered
or passive causal chain. The 0.12 kg rigid-prop masses are experimental.

One 600-step Isaac Sim 6.2.0-rc.14 run passed the frozen core case and the
supplemental checks in this directory. The cabinet's measured native joint
readback reached approximately 1.36 rad, and the three imported props made
direct table contact and settled. This establishes only that specific layout,
preparation, case and run; different assets or placements need new checks.
The first preview failed because its table and floor lacked collisions; the
recipe explicitly enables them.

The three selected models are not included. `assets.lock.json` records their
individual source revisions, file hashes, acquisition and preparation
parameters and license declarations: USDCraft's selected cabinet is
Apache-2.0; the selected ABO and GSO conversions declare CC-BY-4.0. Check the
actual source and attribution terms before use. Acquisition obtains the
selected models and required dependencies, not the entire datasets.

## Rebuild and verify

On a simulation host, install SimScene, USD bindings and FFmpeg. Set these
paths **before** probing the runtime, so the probe and asset preparation use
the same state directory. Use an empty, writable output directory outside the
checkout. The separate GLB decoder is required for this example's ABO and GSO
models; its Node.js prerequisites are in [asset preparation](../../docs/asset-catalog.md).

```bash
export SIMSCENE_HOME=/your/new-layout/state
export SIMSCENE_CACHE=/your/selected-source-cache
export SIMSCENE_V2_CONFIG=/your/layout-v2.json
export SIMSCENE_ISAAC_PYTHON=/your/isaac-sim/python.sh
mkdir -p /your/new-layout
simscene asset setup-decoder --output /your/new-layout/decoder
export SIMSCENE_GLTF_TRANSFORM_PREFIX=/your/new-layout/decoder
simscene asset probe

python3 experiments/acquire_recipe_assets.py examples/automatic_cabinet_layout/assets.lock.json \
  --cache "$SIMSCENE_CACHE" --catalog-output /your/new-layout/bindings.json
python3 experiments/apply_scene_recipe.py examples/automatic_cabinet_layout/recipe.json \
  --scene-id cabinet_layout --asset-catalog /your/new-layout/bindings.json \
  --asset-lock examples/automatic_cabinet_layout/assets.lock.json \
  --save-directory /your/new-layout/applied
python3 experiments/freeze_recipe_case.py examples/automatic_cabinet_layout/case.json \
  --bindings /your/new-layout/bindings.json \
  --asset-lock examples/automatic_cabinet_layout/assets.lock.json \
  --output /your/new-layout/frozen-case.json
simscene run --scene cabinet_layout --steps 600 --seed 42 \
  --case /your/new-layout/frozen-case.json
simscene wait --job JOB_ID --receipt /your/new-layout/run-receipt.json
python3 examples/automatic_cabinet_layout/check.py \
  --run /your/new-layout/state/runs/RUN_ID --output /your/new-layout/check.json
```

Use the returned job and run IDs. This recipe includes two native 1080p/30fps
cameras; rendering takes additional GPU time and disk space. The case template
is frozen against the newly acquired package hashes before the run; rebuilding
the scene or the case does not reuse the earlier physical verdict. `check.py`
also verifies run/evidence locks, native DOF readback, original joint and mass
attributes, direct support, sampled keepout, contacts and settling. It requires
the original prepared source file retained in the selected package. The checker
requires the full example case re-frozen against the run's bindings; it refuses a
case with omitted components or weakened thresholds.

The saved recipe already contains ordinary final placement operations, so its
reconstruction does not need `scene_synthesizer`. To generate a new layout,
install the optional isolated backend and use the documented
[`scene_plan_layout`](../../docs/scene-layout.md) workflow. Save the new plan,
apply it to the current revision, update the case if necessary, and run a new
physical trial. Fixed-seed repeatability in one environment is not a promise
that arbitrary layouts are collision-free or stable.
