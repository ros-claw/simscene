# Optional USDCraft SDK guide-plate generation

`usdcraft_sdk_guide_plate_v1` creates a metric guide plate with the
project's shipped USDCraft SDK template. This backend is optional and uses a
separate Python installation; the existing Sand3D recipes and runtime keep
their original configuration. It accepts only numeric dimensions, not Python
programs, arbitrary model paths, or downloaded scripts.

## Runtime setup

Prepare an editable checkout of the official
[USDCraft repository](https://github.com/NVlabs/USDCraft) at the reviewed
commit `46fec187bdce40845c30863a56143047edc4a263`, and install it in an
independent Python 3.12 environment. Its `pyproject.toml` specifies Python
`>=3.12,<3.13`, `usd-core>=26.5,<27`, and the other SDK dependencies; installation
may be substantial. Do not point the probe at an unreviewed replacement.
For example, after checking out the reviewed commit:

```sh
python3.12 -m venv /absolute/path/to/usdcraft-venv
/absolute/path/to/usdcraft-venv/bin/python -m pip install -e /absolute/path/to/USDCraft

simscene generate probe --backend usdcraft-sdk \
  --python /absolute/path/to/usdcraft-venv/bin/python \
  --checkout /absolute/path/to/clean-USDCraft-checkout \
  --output /absolute/path/to/new-usdcraft-runtime.json
```

The checkout must have no added files or directories, including Git-ignored
files, except `.git`, an optional root `.venv`, and Python `__pycache__`
directories. A separate clean checkout can be selected with `--checkout`; when
omitted, the probe looks for the editable installation's local source path. The
output path must be new. Add the following key to the existing SimScene V2
JSON configuration, or to the file selected by `SIMSCENE_V2_CONFIG`:

```json
{"usdcraft_generation_runtime": "/absolute/path/to/new-usdcraft-runtime.json"}
```

The probe records the Python executable hash, SDK checkout path and commit,
the full committed checkout's source hash, USD version, and versions of
selected dependencies. Each committed file, including code and resources, is
compared to its Git blob rather than trusting Git's index or status flags.
Unexpected files and package import origins that shadow the reviewed checkout
are rejected. The observed runtime is checked before and after generation.
Dependency versions are recorded, but dependency package contents are not
individually hashed. A changed runtime requires a new probe and a new generation
identity.

The backend starts Python with `-S`, so `.pth` files and `sitecustomize` do not
run at startup. Dependencies must be directly importable from the selected
virtual environment's site-packages without startup hooks. A fresh private
bytecode cache prevents use of checkout `__pycache__` files. Generation has a
private job cache and temporary directory, a 180-second timeout, and process
resource limits; cancellation or timeout stops the SDK process group. Python,
third-party packages and local job storage remain trusted: dependency import
can execute code. These controls are not a filesystem or network sandbox.

## Generate and prepare

An MCP call can start a durable job:

```json
{
  "recipe_id": "usdcraft_sdk_guide_plate_v1",
  "parameters": {"length_m": 0.5, "width_m": 0.18, "thickness_m": 0.015},
  "request_id": "guide-plate-05"
}
```

Call `asset_generate` with those fields and poll `job_status` using its returned
job ID. Reuse the request ID when reconnecting to the same request. Alternatively,
save the `parameters` object to `dimensions.json` and use:

```sh
simscene generate start usdcraft_sdk_guide_plate_v1 \
  --parameters dimensions.json --request-id guide-plate-05
simscene generate status JOB_ID
```

Dimensions are in meters. The allowed ranges are length 0.05–2, width 0.02–0.8,
and thickness 0.002–0.08; thickness must be smaller than both other dimensions.
Defaults are 0.5, 0.18, and 0.015 respectively. The completed result provides
`asset_ref` for the ordinary `asset_plan` then `asset_prepare` flow. Select an
explicit preparation profile and physics policy, inspect the plan, and poll
the preparation job. See [asset catalog and preparation](asset-catalog.md).
The `sdk_report_path` and `sdk_report_sha256` in each generation result identify
that job's own check/compile evidence. The generated manifest freezes the
contract version, template hash, parameters, observed toolchain, exported USD
hash, and stable check results. Repeated identical generation reuses the same
published manifest without rewriting it.

The native USD contains a rigid body, mass and collider. The template assumes
650 kg/m³ for mass calculation; this is a modeling assumption, not measured
material evidence. A preparation policy can replace that source physics. For
example, `static_fixture_v1` with `source_physics_policy: replace_visual_only`
and `collision_method: box_proxy` creates an explicit static approximation.
Generation and preparation do not themselves demonstrate physical behavior;
run and assess a separate frozen Isaac simulation for the intended use.

## License and validation scope

The project-authored template and reviewed USDCraft repository are identified
as Apache-2.0. Retain the pinned upstream [LICENSE](https://github.com/NVlabs/USDCraft/blob/46fec187bdce40845c30863a56143047edc4a263/LICENSE),
[NOTICE](https://github.com/NVlabs/USDCraft/blob/46fec187bdce40845c30863a56143047edc4a263/NOTICE),
and [third-party notices](https://github.com/NVlabs/USDCraft/blob/46fec187bdce40845c30863a56143047edc4a263/THIRD_PARTY_NOTICES.md)
with redistributed material as applicable.

On 2026-11-16, the adapter was exercised with USDCraft 1.0.0 at the above
commit, Python 3.12.13 and `usd-core` 26.5. SDK check and compile, closed USD
inspection, and identical-input repeat generation passed for 0.5 m and 0.7 m
plates. In a frozen Isaac Sim 6.2 CPU test, a CCD-enabled ball fell beyond the
short static box proxy and settled on the longer proxy. The example was also
regenerated and prepared in a new directory, then both scenes were run and
checked again. See the [editable example](../examples/usdcraft_sdk_guide/README.md).
These checks cover only those dimensions, preparation and use; they do not
establish a general physics guarantee.

Version 3 USDCraft SDK generation intents can be exported and rebuilt with the
normal portable prepared-role recipe workflow. Before launching regeneration,
the selected backend, trusted template and frozen runtime intent must match the
lock. The new preparation must reproduce the locked source file; its physics
case is frozen and checked anew. Earlier experimental generation contracts are
retained as existing prepared assets but are not silently promoted to v3.
