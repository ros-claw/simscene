# Automatic measured layout

This development branch adds `scene_plan_layout`, an optional MCP planner for
one horizontal support and up to eight existing objects. It proposes regular
`place_on` operations, leaving the scene and the original USD assets unchanged.
The v0.2.0-dev.1 release predates this tool.

## Set up the separate backend

Install [NVIDIA scene_synthesizer](https://github.com/NVlabs/scene_synthesizer)
version 1.15.0 in its own Python environment on the machine running the
SimScene MCP server. Do not install it into the Isaac Sim Python environment:

```bash
python3 -m venv /absolute/path/to/layout-env
/absolute/path/to/layout-env/bin/python -m pip install 'scene-synthesizer==1.15.0'
export SIMSCENE_LAYOUT_PYTHON=/absolute/path/to/layout-env/bin/python
```

Pass `SIMSCENE_LAYOUT_PYTHON` into the MCP server environment, including when
starting it from a client. The base SimScene environment still needs USD Python
bindings to measure imported models. Search, other MCP tools and existing
manual placement do not require this optional backend. Installation downloads
Python packages, not a model library. The backend is never installed automatically.

## Plan and apply

First add the objects and the support to a scene. Imported objects, supports,
and named obstacles must use locally present, hash-verified prepared packages.
Imported supports require a `static_fixture_v1` or `container_v1` collider;
inspect the geometry and declare a named `support_surfaces` region in local
metres. A static box can use its top directly; when placing dynamic objects on
it, explicitly set `collision: true`. Dynamic props and the support also need
enabled collision shapes and must not exclude each other. Instanced imported
supports and compounds with attached visuals are not supported by this planner.
Measure and reserve moving-door, robot and other
activity regions explicitly. For example:

```json
{
  "scene_id": "workshop",
  "ids": ["notebook", "box_1", "box_2"],
  "support": "bench",
  "support_surface": "worktop",
  "seed": 42,
  "clearance_m": 0.02,
  "gap_m": 0.001,
  "avoid_ids": ["fixed_fixture"],
  "keepout_bounds": [{"min": [0.2, -0.4, 0.7], "max": [0.6, 0.1, 1.4]}]
}
```

Send this object to `scene_plan_layout`. If `bench` is a primitive box with no
named region, omit `support_surface`. The response contains the seed, backend
and dependency versions, an identifying `plan_sha256`, support relationships,
`base_revision`, and normal scene `operations`. Apply the entire batch using
`scene_apply` with the returned scene and revision. A revision conflict rejects
the batch; plan again against the current scene. A saved operation list can be
reapplied to an equivalent starting scene without re-running the sampler;
verify the source and resulting scene in that environment.

The worker seeds the upstream and NumPy random generators in a fresh process.
The returned identity records the scene inputs, all installed Python package
versions, Python, platform and the observed GEOS version. A repeated seed was
checked in separate processes on one environment; package versions do not pin
every native library or guarantee identical results across machines. The
`verified_prepared` source entries include each manifest hash and profile.
The planner verifies the local package, and scene edits and runs recheck their
bindings. Fixed model files and package hashes belong in the project’s normal
asset lock and run snapshot.

## What the proposal checks

The worker uses conservative boxes from measured render bounds, samples on the
declared region, and checks footprints, edge clearance and explicit exclusions.
SimScene independently rechecks the proposed operations before returning them.
Object orientations stay as supplied. Obstacles and keepouts are conservatively
projected to support-local XY regardless of height; this can reject feasible
placements. Unlisted objects and moving-door sweeps are not inferred. Infeasible
packing, missing dependencies and unsupported backends fail instead of silently
placing partial results.

Render bounds are not the collision geometry or a stability certificate.
`physics_tested` remains false. Check actual USD bindings, collider clearance,
joint travel, contacts, and settling in a fresh Isaac run using a frozen case.

## Motion envelopes for two pinned examples

The installed examples provide source-specific profiles
`usdcraft_lift_cabinet_v1` and `usdcraft_two_drawer_v1`. Their recorded
owner-local geometry comes from the selected source's zero-state child bounds,
including its collision geometry. The hinge uses a conservative full-turn
cylindrical enclosure, including intermediate positions; the drawers use the
entire native slider limits along the transformed native axes. These envelopes
can reject feasible placements and do not account for future parent drift or
constraint failure. They are not automatically inferred for arbitrary joints.

After acquiring and preparing the matching asset, save the current `scene_get`
result to a new JSON file. For an installed portable package, use its matching
vendored SimScene code and the host's USD Python bindings:

```bash
PYTHONPATH="$SIMSCENE_PLUGIN_ROOT/server/vendor" python3 \
  "$SIMSCENE_PLUGIN_ROOT/experiments/check_motion_clearance.py" \
  --scene /your/current-scene.json --owner cabinet \
  --profile usdcraft_lift_cabinet_v1 --output /your/new-keepout.json
```

With no `--object` arguments the result is `not_checked`: its `keepout_bounds`
are inputs to `scene_plan_layout`, not an acceptance verdict. Use
`clearance_m: 0.05` in the planner. After applying at the returned revision,
save a fresh `scene_get` result and repeat the command with `--object box`
and one `--object` for each other external prop, writing a new output file.
`clear` means only those render bounds cleared the qualified geometry;
`conflict` names the object and joint. The owner is excluded from its own
keepout. Unknown sources, changed native joint/collider metadata, unsafe owner
overrides and missing geometry fail instead of being reported as clear. The
result pins the scene content and revision, profile, and prepared manifest.

The primitive-box support's declared region must be on and within its actual
top; invalid support height or extent is rejected before sampling. A declared
region on an imported support still requires inspection of its actual prepared
colliders. Neither a clear keepout nor a valid support replaces a fresh physical
run, observed contacts or stability checks.
