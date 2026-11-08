# Optional Sand3D generation

The optional backend runs the shipped `guide_plate_v1` and `open_receiver_v1`
templates. The guide takes `length_m`, `width_m` and `thickness_m`. The receiver
takes interior width/depth/height and wall/floor thickness in metres; its five
walls leave the top open. It generates metre/Z-up native USD,
records template/parameters/toolchain/output hashes, and returns a
local immutable AssetRef. Arbitrary program text, remote Python and unknown
template IDs are rejected before execution.

Install the reviewed commit in a **separate** environment. The base MCP remains
Python 3.10 compatible; do not install Blender into Isaac's interpreter.

```bash
uv venv --python 3.11 /your/new/sand3d-env
uv pip install --python /your/new/sand3d-env/bin/python \
  'sand3d @ git+https://github.com/Sandflow-ai/sand3d.git@0d589a5ba568fd72c8da97f8d039918650608a42'
simscene generate probe --python /your/new/sand3d-env/bin/python \
  --output /your/new/sand3d-runtime.json
```

Save the resolved dependency lock for the installation. The observed local
combination was Python 3.11.15, Sand3D 1.6.2 at the pinned commit, and bpy
4.5.15 LTS. Other combinations require their own probe and physical validation.
The probe verifies the installed distribution's actual VCS commit and records
its source fingerprint. An unreviewed or changed runtime fails closed.

Add `"generation_runtime": "/your/new/sand3d-runtime.json"` to the separate
V2 configuration selected by `SIMSCENE_V2_CONFIG`. Absence of this optional
backend does not disable catalog search. Starting generation never installs
dependencies or accepts external code.

```bash
simscene generate start guide_plate_v1 --parameters dimensions.json \
  --request-id my-guide-first
simscene generate status gen-RETURNED_ID
```

MCP provides `asset_generate(recipe_id, parameters, request_id)`. Durable jobs
survive client reconnects; reusing a request reattaches, and changed parameters
with that request fail. An uncertain launch is not automatically rerun.
Cancellation is acknowledged at a safe checkpoint; a pending request is not a
completed cancellation. Failed attempts and backend logs remain in the job.

The generator has actual CPU, address-space, file-size, open-file and wall-time
limits. It executes reviewed shipped templates in a subprocess. These limits
are **not** a filesystem or network sandbox; external-program execution is
unavailable. Generated source artifacts and job evidence are retained outside
the source cache and must be included when accounting for total storage.

The completed AssetRef resolves through the ordinary `asset_plan` and
`asset_prepare` path. Sand3D's authored bodies are not presumed simulation-ready:
the guide's static role explicitly replaces source physics with a measured box
proxy. The preparation records that approximation. A generated file or completed
preparation has no physical pass. Validate its actual contact and support role,
then change a dimension and validate the new preparation and layout again.
Same-parameter generation was byte-identical in the tested pinned runtime;
this is a measured narrow result, not a universal Blender determinism promise.

Prepare the receiver with `container_v1` and an explicitly measured
`container_proxy`, including the intended probe dimensions. The profile checks
the empty cavity and source-surface agreement before authoring five collision
walls. It must still pass an actual drop, opening-passage and settling test;
adding a closed top is a separate negative control. No automatic container
recognition or deformation/load-capacity guarantee is made.
