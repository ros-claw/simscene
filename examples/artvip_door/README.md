# ArtVIP door with explicitly prepared physics

This small editable example selects one pinned ArtVIP door, prepares a local
derived USD, drives its single native hinge open and closed, and checks the
actual joint and body observations. It does not download the ArtVIP dataset.
The selected USD and three dependencies totaled 68,676 bytes in the measured
cold acquisition. Search reads metadata only; the exact transfer depends on
the selected revision and cache.

The original links have no authored total mass. Their seven colliders do have
source physics-material densities, so this example's experimental 12 kg frame
and 8 kg door **override those density contributions**. The source's
acceleration drive has unbounded effort; this recipe neutralizes it and uses
separate bounded scheduled force commands. These are experimental assumptions,
not manufacturer values, and do not preserve the original drive behavior.
The package retains the unmodified source, complete repair report, and a
per-collider list of the source densities affected. A different object or
revision needs a new inspection, recipe and physical test.

One 600-step Isaac Sim 6.2.0-rc.14 trial passed the frozen driven case with
native DOF and body-frame readings at every step. A separate otherwise identical
trial removed the drive commands: it completed the physics steps, the door
stayed near its initial angle, and the driven case failed for the expected
missing motion and commands. This tests a scheduled drive and a no-drive
counterfactual; it does not establish passive contact triggering or certify
other ArtVIP assets. The [pinned dataset card](https://huggingface.co/datasets/X-Humanoid/ArtVIP/blob/d22f2095bc9db29fdd4b60f4a3c4f8177e1f5e9e/README.md)
declares Apache-2.0; a separate object-specific notice has not been established.
Preserve source attribution and applicable notices. Model payloads are not
included in this repository.

## Rebuild on a simulation host

Install this development version of SimScene, USD Python bindings and FFmpeg;
configure a compatible Isaac Sim runtime and run `simscene asset probe`. Use
new, writable directories outside the checkout. `SIMSCENE_V2_CONFIG` should
identify your local index, prepared cache and probe record, as described in
[asset preparation](../../docs/asset-catalog.md).

```bash
export SIMSCENE_HOME=/your/artvip-example/state
export SIMSCENE_CACHE=/your/artvip-example/cache
export SIMSCENE_V2_CONFIG=/your/artvip-example/v2.json
export SIMSCENE_ISAAC_PYTHON=/your/isaac-sim/python.sh

simscene catalog search door --source artvip
python3 experiments/acquire_recipe_assets.py examples/artvip_door/assets.lock.json \
  --cache "$SIMSCENE_CACHE" --catalog-output /your/artvip-example/bindings.json
python3 experiments/apply_scene_recipe.py examples/artvip_door/recipe.json \
  --scene-id artvip_door --asset-catalog /your/artvip-example/bindings.json \
  --asset-lock examples/artvip_door/assets.lock.json \
  --save-directory /your/artvip-example/applied
python3 experiments/freeze_recipe_case.py examples/artvip_door/case.json \
  --bindings /your/artvip-example/bindings.json \
  --asset-lock examples/artvip_door/assets.lock.json \
  --output /your/artvip-example/frozen-case.json
simscene run --scene artvip_door --steps 600 --seed 42 \
  --case /your/artvip-example/frozen-case.json
python3 examples/artvip_door/check.py \
  --run /your/artvip-example/state/runs/RUN_ID --output /your/artvip-example/check.json
```

Replace `RUN_ID` with the returned run ID. The included recipe uses one
640×360, 2 fps diagnostic camera; the separate 1080p30 source recording was
captured from a new run and has its own frame table. The checker verifies the
frozen case, run and evidence locks, source-to-derived physics graph, mass
provenance, 601 native joint readings, and fixed-parent stability. A successful
prepare or a generated video alone is not a physical verdict. For a no-drive
control, retain the same prepared package and scene, remove the two mechanism
commands, and require the positive driven case to fail because the scheduled
motion did not occur; inspect the actual recorded motion and inputs as well.
