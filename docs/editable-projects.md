# Editable local projects

`experiments/export_run_project.py` packages an intact completed run as a new,
editable local project. It checks the original input and output locks, copies
the selected asset dependencies and frozen SimScene runtime, writes relative
asset references, and preserves the source run and evidence hashes. Original
evidence stays separate from edits and replay results.

From a configured source checkout:

```sh
PYTHONPATH=src python3 experiments/export_run_project.py /absolute/run/directory /absolute/new/project
```

The destination must be new. It contains `scene.json`, `scene.usda`,
`run_project.py`, `project.json`, a frozen `runtime/`, selected `assets/` where
used, and the frozen `case.json` when the source has an acceptance case. Asset
geometry and textures remain subject to their upstream licenses.

Use a Python environment with SimScene's host dependencies and OpenUSD Python
bindings; Isaac runs through its own configured launcher. For the workstation
used in the sugar-chain development, the explicit host interpreter is
`/usr/bin/python3.10` and the Isaac launcher is
`/data/omniverse/isaac-sim-6.2.0/python.sh`.

The bundle can be moved to another directory. Validate the editable schema and
USD composition there first:

```sh
/usr/bin/python3.10 /absolute/moved/project/run_project.py --check-only
```

This command creates an imported scene and exports USD. It does **not** run
physics or establish task success. For a complete clean replay:

```sh
CUDA_VISIBLE_DEVICES=0 SIMSCENE_ISAAC_PYTHON=/data/omniverse/isaac-sim-6.2.0/python.sh /usr/bin/python3.10 /absolute/moved/project/run_project.py
```

The launcher creates new state and run directories under the project, retains
the original physics horizon and seed, and invokes the stock checker for
supported cases. It waits while a job is queued, running, paused, or reported
as `stalled` with a live worker. Inspect that run's worker log to distinguish
slow shader/startup work from a process failure. A paused run requires resume
or cancellation through the job interface.

`--scene-file`, `--case-file`, `--steps` and `--isaac-python` support deliberate
edits and diagnostics. A shortened horizon or changed case is a separate run;
it cannot substitute for the original complete-task replay. A challenge may
also require independent supplemental checks beyond the launcher's stock
case result.

Cases without a legacy `source_scene_sha256` binding are passed by file path,
preserving their exact bytes and SHA256, including formatting. This matters for
paired runs that must use an independently frozen case. For legacy cases tied
to the original scene hash, importing a new scene needs a new hash binding: the
launcher saves a separate case under `state/`, prints both case paths and hashes,
and leaves the original `case.json` untouched. That explicitly rebound case
does not satisfy a challenge requiring the original exact case hash.

Some selected materials are explicitly supplied by the Isaac runtime rather
than the asset package. `project.json` records those direct runtime-provided
dependencies. A replay still needs a compatible Isaac installation and the
source evidence retains the complete asset/runtime integrity records.
Exporting an editable project does not bundle an Isaac installation or prove
that arbitrary asset licenses permit publication.

For a lightweight editable recipe without copied asset binaries:

```sh
PYTHONPATH=src python3 experiments/export_scene_recipe.py /absolute/run/directory /absolute/new/recipe
PYTHONPATH=src python3 experiments/acquire_recipe_assets.py /absolute/new/recipe/assets.lock.json --cache /absolute/asset-cache --catalog-output /absolute/new/recipe/catalog.json
PYTHONPATH=src python3 experiments/apply_scene_recipe.py /absolute/new/recipe/recipe.json --scene-id RecipeRebuild --asset-catalog /absolute/new/recipe/catalog.json --save-directory /absolute/new/recipe/rebuilt
```

The recipe preserves ordinary objects, including compound rigid bodies,
passive joints, visual attachments, cameras, presentation and observation
settings. Selected assets use `asset://` bindings and a separate content lock;
reacquisition fails if their pinned files change or dependencies are unresolved.
Asset licenses still apply. Authored local USD and controller/model scenes need
the full project exporter. Applying a recipe creates a new scene in the
configured local scene store and saves its resolved operations and scene JSON;
it does not simulate it, copy an acceptance case, or establish task success.
Use the full project for a recorded horizon/seed and complete physics replay.

The v40 acquired-asset preflight moved a project before opening it, verified
all 19 USD/texture dependency files remained under the new directory, and
completed schema/export validation. That limited preflight was not a physics
replay; each delivered challenge's report must separately record its actual
new-directory full replay.
