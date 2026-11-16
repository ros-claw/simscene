# Two independently observed USDCraft drawers

This editable example selects only `ds_R022_02`, a USDCraft cabinet with three
native rigid links and two prismatic joints. The source USD's geometry,
collision shapes, masses, limits and friction are preserved. The experiment
adds scheduled force drives: the lower drawer reaches 0.25 m while the upper
one is held near closed, then the upper reaches 0.35 m while the lower is held.
A control removes only the upper drawer's second scheduled drive. Both runs use
the same frozen acceptance case. In the tested control the lower drawer still
moved, while the upper remained near 0.0011 m.

The data records every physics step, including path-keyed native PhysX joint
position and velocity, link poses and cooked centers of mass. The verifier
checks the independent native and frame-derived measurements, joint limits,
locked rotations, scheduled command readback, and run and evidence locks. A
separate paired mode checks that the control removes only the second drive and
that the observed control motion changes as expected. This
example does not claim passive triggering, general two-joint support, or robot
interaction. A cabinet using a different graph, units, joint type or drive must
be inspected and physically tested separately.

The tested source is the one-file dependency closure of 40,680 bytes at pinned
revision `92f4e908415d7532a02661d6502ab49dc3aa33f9`; the asset payload is not
included in this repository. The licensed source metadata and file hash are in
`assets.lock.json`. Preserve upstream attribution and notices. The two-slider
physical test used Isaac Sim 6.2.0-rc.14, PhysX CPU, 60 Hz and seed 42. A
640×360 2 fps diagnostic recording is distinct from physical acceptance.

## Rebuild on a simulation host

Install this development version, the documented USD Python bindings and
FFmpeg. Configure the compatible Isaac launcher and probe the preparation
runtime as described in [asset preparation](../../docs/asset-catalog.md). Use
new writable locations outside the checkout, and point `SIMSCENE_V2_CONFIG` to
your own configured index, preparation directory and probe result.

```bash
export SIMSCENE_HOME=/your/two-drawer/state
export SIMSCENE_CACHE=/your/two-drawer/cache
export SIMSCENE_V2_CONFIG=/your/two-drawer/v2.json
export SIMSCENE_ISAAC_PYTHON=/your/isaac-sim/python.sh
export SIMSCENE_PHYSICS_DEVICE=cpu

python3 experiments/acquire_recipe_assets.py examples/usdcraft_two_drawer/assets.lock.json \
  --cache "$SIMSCENE_CACHE" --catalog-output /your/two-drawer/bindings.json
python3 experiments/apply_scene_recipe.py examples/usdcraft_two_drawer/recipe.json \
  --scene-id two_drawer --asset-catalog /your/two-drawer/bindings.json \
  --asset-lock examples/usdcraft_two_drawer/assets.lock.json \
  --save-directory /your/two-drawer/applied
python3 experiments/apply_scene_recipe.py examples/usdcraft_two_drawer/recipe-control.json \
  --scene-id two_drawer_control --asset-catalog /your/two-drawer/bindings.json \
  --asset-lock examples/usdcraft_two_drawer/assets.lock.json \
  --save-directory /your/two-drawer/control-applied
python3 experiments/freeze_recipe_case.py examples/usdcraft_two_drawer/case.json \
  --bindings /your/two-drawer/bindings.json \
  --asset-lock examples/usdcraft_two_drawer/assets.lock.json \
  --output /your/two-drawer/frozen-case.json
simscene run --scene two_drawer --steps 600 --seed 42 --case /your/two-drawer/frozen-case.json
simscene run --scene two_drawer_control --steps 600 --seed 42 --case /your/two-drawer/frozen-case.json
simscene verify --run "$SIMSCENE_HOME/runs/POSITIVE_RUN_ID"
simscene verify --run "$SIMSCENE_HOME/runs/CONTROL_RUN_ID" \
  --mode missing_second_joint_drive --reference-run "$SIMSCENE_HOME/runs/POSITIVE_RUN_ID"
```

Replace both IDs with the returned run IDs. The control is expected to fail the
single-run *positive* verifier because the second command and motion are
intentionally absent. Paired mode requires matching frozen inputs, source and
runtime, checks both evidence locks, and confirms that the first stage still
works. An arbitrary failed run cannot pass it. MCP clients can use `run_verify`
with the control `job_id`, mode `missing_second_joint_drive` and the positive
`reference_job_id`.
