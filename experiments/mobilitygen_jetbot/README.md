# Experimental MobilityGen Jetbot probe

This standalone tool runs a fixed Jetbot route and a matched zero-command
control. It is **not** connected to `scene_apply`, `simulation_start`, the
SimScene job registry, or a general robot motion API. It has been exercised
only on the specific Isaac Sim 6.2 RC build and single NVIDIA Jetbot asset
locked here. It does not establish obstacle avoidance, automatic mapping,
arbitrary robot compatibility, or physical-robot safety.

The tool freezes its case and code, copies eight verified USD files into a new
output directory, and runs both modes through the existing per-user SimScene
GPU queue. The stage uses CPU PhysX; headless Isaac can still use a GPU.
Both simulations perform 30 settling steps and then exactly 600 task steps at
1/60 s. The positive follows a fixed straight 0.8 m route on an explicitly
defined flat occupancy map. Once the 0.08 m goal threshold is reached, it
holds zero wheel targets through the remaining steps. The control uses the
same setup and horizon with wheel targets always zero.
The scene explicitly authors `TGS` and `enableExternalForcesEveryIteration`;
the worker records USD readback after setup. This is not an independent
readback of the internal PhysX solver configuration.
The frozen case seeds Python's `random` and NumPy with `20261116`; the metadata
records both seeds. This does not claim that every Isaac or PhysX internal
source of nondeterminism is controlled.

The case's `asset_relative_path` preserves the original probe's path as
provenance; this tool resolves the actual input from `--asset` and verifies
the copied files against `asset-lock.json`.

The source Jetbot has two caster physics material relationships that USD
cannot resolve through their instance references. The worker explicitly
deinstances those two scene prims and restores their bindings to the existing
source-authored material; it records the changes. It also changes both source
wheel drives from unlimited effort to an experimental 1 N·m maximum in the
scene, then reads native PhysX drive type, maximum effort, stiffness and
damping before and after the task. Both native angular drive damping values
must be 1.0 within 0.00001; the source USD damping is about 0.017453294 in
its authored angular units. The source USD files are not modified.
These repairs and the drive-target adapter are part of this experiment, not
claims about the stock MobilityGen example. The effective PhysX caster
friction was not independently read back from a native tensor.

Each sample includes the native chassis pose, center-of-mass linear and angular
velocity readbacks, wheel positions and velocity readbacks,
commanded and native-readback wheel velocity targets, physics-step callback
count, goal distance, map status and observed contact actor pairs. A paired
checker verifies the fixed route, native drive values, initial pose and raw
state agreement, step continuity, wall bounds, raw contact actors against
flags, the complete horizon and terminal zero targets. During the task, every
sliding 60-step window must contain at least one ground contact for each wheel;
this does not establish uninterrupted contact, force direction or no
penetration. The positive must progress at least 0.3 m along the fixed route
while a wheel target is nonzero and show sampled position changes on both
wheels. This is a timing association, not proof that the command caused the
motion. Short-angle changes are observational: inferring total rotation would
require the unverified assumption of no unobserved full turns between samples.

The velocity fields are preserved as **raw readbacks**. Diagnostic experiments
found systematic differences between reported velocities and finite differences
of link/COM positions, orientations and wheel positions, including after the
solver change reduced those differences. The paired audit consequently reports
`native_velocity_consistency: not_verified`. Bounded or matching initial raw
readbacks do not prove the robot was stationary. Zero wheel targets, including
at the end of the run, do not establish that the wheels or chassis stopped.

## Requirements and acquisition

* A Linux Isaac Sim installation whose `VERSION` is exactly
  `6.2.0-rc.14+release.52805.02189a84.gl`; selected installed MobilityGen,
  controller and MDL source hashes, including the launcher itself, must also
  match `runtime-lock.json`.
  This pins selected files, not the entire simulator or all transitive MDL
  dependencies. The local Isaac installation and binaries remain a trusted
  boundary, not a fully authenticated environment. Other Isaac versions are
  rejected pending their own tests.
* An exact local copy of the eight Jetbot files listed in `asset-lock.json`.
  Do not add them to the repository. NVIDIA-provided assets and MDL files use
  the [Isaac Sim Additional Software and Materials License](https://docs.isaacsim.omniverse.nvidia.com/latest/common/license-isaac-sim-additional.html),
  not the Apache license of the example Python sources.
* The existing SimScene `src/simscene/worker/gpu_queue.py`. An alternative
  location can be passed with `--queue-script`, but its hash must match the
  pinned queue. A changed queue or tool file requires explicit requalification
  and a new lock; the tool does not silently update either.

If the asset is not already available, this optional command fetches only the
eight pinned objects to a **new directory outside the repository**. The total
is 31,942,504 bytes; the hard budget is 48 MB total and 35 MB per object.
Each URL, response, size and hash is checked and recorded in `fetch-log.jsonl`.
Failures leave their own evidence and require a fresh output directory.

```bash
python3 experiments/mobilitygen_jetbot/fetch_assets.py --output /path/to/new-jetbot-assets
```

## Run and verify

From the repository root, provide the local Isaac launcher, the root USD of the
locked asset, and a **new output path outside the repository**:

```bash
python3 experiments/mobilitygen_jetbot/run_pair.py \
  --isaac-python /path/to/isaac-sim/python.sh \
  --asset /path/to/new-jetbot-assets/jetbot.usda \
  --output /path/to/new-jetbot-pair
```

Use `--queue-script /path/to/gpu_queue.py` if this tool is copied away from the
SimScene repository. `SIMSCENE_GPU` may select the Isaac device; the queue is
still the host's per-user cooperative lock. The launcher waits for each run;
it is not a durable detached job. Both modes are attempted even if one fails.
It never reuses an existing output path. `runs/positive/` and `runs/zero/`
retain logs, queue exit receipts, metadata, and partial telemetry on failure;
each run receives an evidence lock immediately after it exits, including
`result.json` and any missing files. A failed or incomplete run is marked
partial. `audit.json` records the pair verdict and evidence hashes. These
local SHA-256 locks detect later changes but are not signatures and do not
establish authenticity against an actor able to alter both data and locks.
`runtime/` and
`assets/` are snapshots of the locked inputs, not source edits.

An independent read-only recheck can use the saved verifier and, if the Isaac
installation moved, a launcher at a new path with matching pinned files:

```bash
python3 /path/to/new-jetbot-pair/runtime/audit_output.py /path/to/new-jetbot-pair \
  --isaac-python /path/to/isaac-sim/python.sh
```

## CPU checks

```bash
cd experiments/mobilitygen_jetbot
python3 -m unittest -v test_contract test_evaluate test_sixty test_pair test_fetch \
  test_review_regressions test_new_guards test_redirect test_reaudit
```

The checks cover asset path/hash failures, runtime locks, native finite effort
and target readback, incomplete or discontinuous samples, collision flags,
terminal zeroing, paired input mismatches, evidence tampering, launcher
identity, and a redirect that must not contact its target. CPU
tests alone do not establish that an Isaac simulation ran successfully.
