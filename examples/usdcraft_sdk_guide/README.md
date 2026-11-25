# Generated guide-plate support comparison

This example uses the optional USDCraft SDK backend to generate two instances
of the same guide-plate template: 0.5 m and 0.7 m long. Both retain the same
width and thickness. They are independently prepared as static fixtures with
explicit measured box collision proxies; their original generated rigid-body
physics is replaced in the derived preparation. A 40 mm ball is released at
the same position in each scene. It falls beyond the short plate and settles
on the floor; the long plate reaches underneath it and supports it.

The frozen case checks complete 360-step, 60 Hz observations, input and
output integrity, the selected generated-source hashes, CCD on the ball and
scene, the expected separate direct contact callbacks, settling, and a 2 mm
upper bound on reported penetration. Contact callbacks cannot exclude contacts
or penetration that the physics engine does not report. The generator's
assumed material density and the static box proxy are experimental; this is not
a strength or real-world safety test.

The matched physical test used Isaac Sim 6.2.0-rc.14 and CPU PhysX. One run of
each size passed; a separate new-directory regeneration and preparation is
also exercised by the commands below. Changing dimensions, supports, material
or runtime requires a new frozen case and actual simulation. The generated USD
is not included in the repository.

## Rebuild and verify

Set up and probe the isolated, reviewed SDK runtime as described in
[USDCraft SDK generation](../../docs/usdcraft-sdk.md). The lock fixes the
reviewed SDK commit, template hash, parameters, source-file hashes and the
recorded toolchain. A different runtime must be checked and explicitly
requalified rather than silently relabeling the old result. Also configure the
ordinary Isaac preparation runtime, FFmpeg and USD bindings. Use new directories
outside the checkout:

```bash
export SIMSCENE_HOME=/your/generated-guide/state
export SIMSCENE_CACHE=/your/generated-guide/cache
export SIMSCENE_V2_CONFIG=/your/generated-guide/v2.json
export SIMSCENE_ISAAC_PYTHON=/your/isaac-sim/python.sh
export SIMSCENE_PHYSICS_DEVICE=cpu

python3 experiments/acquire_recipe_assets.py examples/usdcraft_sdk_guide/assets.lock.json \
  --cache "$SIMSCENE_CACHE" --catalog-output /your/generated-guide/bindings.json
python3 experiments/apply_scene_recipe.py examples/usdcraft_sdk_guide/recipe-short.json \
  --scene-id sdk_guide_short --asset-catalog /your/generated-guide/bindings.json \
  --asset-lock examples/usdcraft_sdk_guide/assets.lock.json \
  --save-directory /your/generated-guide/applied-short
python3 experiments/apply_scene_recipe.py examples/usdcraft_sdk_guide/recipe-long.json \
  --scene-id sdk_guide_long --asset-catalog /your/generated-guide/bindings.json \
  --asset-lock examples/usdcraft_sdk_guide/assets.lock.json \
  --save-directory /your/generated-guide/applied-long
python3 experiments/freeze_recipe_case.py examples/usdcraft_sdk_guide/case.json \
  --bindings /your/generated-guide/bindings.json \
  --asset-lock examples/usdcraft_sdk_guide/assets.lock.json \
  --output /your/generated-guide/frozen-case.json
simscene run --scene sdk_guide_short --steps 360 --seed 17 --case /your/generated-guide/frozen-case.json
simscene run --scene sdk_guide_long --steps 360 --seed 17 --case /your/generated-guide/frozen-case.json
python3 examples/usdcraft_sdk_guide/check_pair.py \
  --short-run "$SIMSCENE_HOME/runs/SHORT_RUN_ID" \
  --long-run "$SIMSCENE_HOME/runs/LONG_RUN_ID" \
  --case /your/generated-guide/frozen-case.json --output /your/generated-guide/check.json
```

Replace both IDs with the returned run IDs. The checker requires the example
case freshly bound to the two rebuilt assets and checks the input/evidence
locks for both runs. It cannot turn a preview, SDK compilation or an old
result into a physical pass.
