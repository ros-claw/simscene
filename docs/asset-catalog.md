# Online catalog and prepared assets

The V2 workflow adds six MCP tools: `catalog_search`, `asset_plan`,
`asset_prepare`, `catalog_discover`, `scene_compile_recipe` and `asset_generate`.
The original 46 tools retain their interfaces. Source availability, static preparation, and successful
physical execution are separate results.

## Select a source and search metadata

```bash
simscene catalog sources
simscene catalog validate
simscene catalog refresh abo-glb
simscene catalog search 'notebook' --source abo-glb --limit 8
simscene catalog search 'industrial workbench' --source nvidia-usd-search
```

Experimental sources require explicit selection until their integration gates
are accepted. The first ABO search retrieves its bounded pinned metadata index;
`refresh` explicitly refreshes that index. Neither downloads its model library.
Search returns bounded summaries and links to detailed records. The
NVIDIA adapter requests no inline previews. Opening a preview is a separate
operation. Search service failures are reported as unavailable/partial results.
An index transfer that exceeds the configured search deadline also reports a
timeout; it does not publish a partial index. Retry or explicitly refresh it
when the source recovers. Cursor pages retain the original query's cost under
`budgets.metadata_bytes`; use `budgets.request_metadata_bytes` and
`request_preview_bytes` for per-call transfer accounting. Cached cursor pages
make no network requests.

ABO is a community conversion of Amazon Berkeley Objects; preserve its source
identity and CC-BY notices. NVIDIA search indexes upstream libraries with
different terms: an asset's license can remain unknown even when search works.
A blocked plan explains unresolved licensing, access, codec, or budget facts.
Do not treat the registry as a redistribution grant.

## Configure the preparation runtime explicitly

The verified GLB pipeline uses Isaac Sim's asset converter and an isolated
meshopt predecoder. It does not install packages during search or conversion.
The current pinned predecoder requires Node.js `22.23.2` and npm. Its lock and
module hashes are checked, including transitive packages.

```bash
simscene configure --isaac-python /path/to/isaac-sim/python.sh
simscene asset setup-decoder --output "$PWD/.simscene-converter"
export SIMSCENE_GLTF_TRANSFORM_PREFIX="$PWD/.simscene-converter"
simscene asset probe
```

Setup uses `npm ci --ignore-scripts` in a new directory. Failures retain their
logs and partial installation; use another empty directory when retrying.
`asset probe` explicitly starts a queued SDK application, observes its actual
converter/USD versions, and saves a local capability record. It takes no
physics steps. Planning subsequently reads that record without starting Isaac.
Changing the toolchain invalidates old plans. The current converter policy is
verified against Isaac Sim `6.2.0-rc.14`, USD `0.25.11`, and asset converter
`6.1.0`; other installations need their own compatible policy verification.

The simulation host needs USD Python bindings for scene export and dependency
inspection. The client can run remotely and receive images, state, and video;
model files and conversion tools reside on the simulation host.

## Freeze the selection and physical assumptions

Save an exact `ref` returned by search as `selected.json`. Hugging Face
selections require a complete 40-character commit SHA. For example, a rigid
recipe can be saved as `rigid.json`:

```json
{
  "source_physics_policy": "reject_if_physics",
  "scale_mode": "fit_longest",
  "target_longest_extent_m": 0.15,
  "mass_kg": 0.12,
  "mass_note": "Experimental 150 mm prop; not manufacturer mass or dimensions",
  "proxy_tolerance_m": 0.002
}
```

```bash
simscene asset plan --ref selected.json --profile rigid_prop_v1 \
  --parameters rigid.json --budget-bytes 16777216
simscene asset prepare PLAN_ID --request-id first-local-prop
simscene asset status PREPARATION_JOB_ID
simscene wait --job PREPARATION_JOB_ID --receipt prepare-completed.json
```

Planning freezes source metadata, profile parameters, observed target,
converter policy, and separate transfer/unpacking/staging budgets. Unknown
dependency sizes remain unknown. Preparation retrieves only the selected model
and its closure. Missing dependencies cannot qualify as complete. Failed
requests retain their consumed transfer bytes. Repair publishes a new package
while reusing verified files and preserving the old package.

Reusing a request ID returns its original job, including a failed job. Use a
new request ID for a deliberate retry. Jobs persist independently of the MCP
process. An uncertain interrupted launch is reported without automatically
launching another process. Cancellation remains pending until a safe checkpoint
or confirmed converter termination.

## Use the prepared package and verify physics

A completed job returns `root`, `manifest_path`, `manifest_sha256`, bounds,
local body mappings, and `runtime_validation.status = not_run`. A cache hit
reuses preparation; it does not reuse a physical acceptance verdict.

Use the returned paths in an ordinary scene object:

```json
{
  "kind": "asset",
  "asset_path": "/simulation-host/package/main.usda",
  "asset_binding": {
    "manifest_path": "/simulation-host/package/manifest.json",
    "manifest_sha256": "COPY_THE_RETURNED_SHA256"
  },
  "dynamic": true,
  "position": [0, 0, 0.25]
}
```

The rigid body is inside the imported instance, commonly
`/World/OBJECT_ID/Asset/Body`. Scene export resolves the actual body, visual,
and collider paths; observations and contacts use those mappings. The wrapper
is not a second rigid body. Bound objects reject overrides that would invalidate
their prepared identity; change the recipe and prepare again instead.

Profiles support passive visual props, measured static fixtures, single convex
rigid props, admitted native single-DOF articulations, explicit open-container
proxies and light-only HDRI packages. Concave shapes can be rejected. Convex hulls
are checked with disclosed surface sampling and absolute/relative error caps;
this is a measured admission test, not proof of exact geometry. Mass, friction,
and restitution are experimental assumptions. Animated, skinned, articulated,
and arbitrary codec inputs are not silently converted into rigid props. Native
articulations use their own preserving profile; containers require an explicit
measured opening and wall/floor proxy. See the [native role guide](../skills/build-scene/references/native-assets.md)
and [selected runtime evidence](validation/catalog-capabilities.md).

For a gravity/contact test, freeze a `simscene.rigid_asset_smoke.v1` case before
starting the simulation. It checks complete observations, the actual body,
specified contacts, full bounds containment, and two seconds of settling.
Optional `required_contact_actors` requires direct contacts with each listed
ramp, baffle, or receiver. Removing a required collider should change the
physical result. `simscene verify --run RUN_DIRECTORY` reads the evidence and
does not control or repair the scene.

Runs snapshot complete prepared packages and pin their manifests and runtime
material dependencies. USD references are relative inside each package.
Source-cache eviction therefore cannot break a frozen prepared snapshot.
Keep source attribution and asset terms with redistributed projects; code
licensing does not transfer to downloaded models.

## Budgets and configuration

V2 settings live in `~/.config/simscene/v2.json`, or the file selected by
`SIMSCENE_V2_CONFIG`. Legacy settings remain compatible. Defaults include:

| Budget | Default |
|---|---:|
| Search summaries | 8 items, maximum 20; 12 KiB page |
| Providers / search deadline | 3 / 12 seconds |
| Metadata index | 32 MiB |
| Selected asset transfer | 1 GiB |
| Scene transfer budget for orchestration | 2 GiB |
| Unpacked / staging | 4 GiB each |
| Prepared cache capacity | 4 GiB |

Cache capacity is independent of network/staging limits. Scene orchestration
must subtract actual bytes from each serial acquisition, including failures;
preparation has no scene ID and does not invent a scene-wide account. Large
file inventories and traces stay in linked manifests and job records.

Catalog records distinguish declared, inspected, and runtime-verified facts.
Neither a dataset name nor the number of research candidates establishes
integration support. Cross-task token or speed gains require comparable real
usage measurements.
