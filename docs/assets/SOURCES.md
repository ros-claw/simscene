# Asset sources

Generated from [the packaged registry](../../src/simscene/catalog/data/sources.yaml). Edit that registry and regenerate this file; do not maintain a second source inventory.

Source admission and asset physics are separate. Enabled means an adapter passed a finite integration example. It does not certify every object, variant, profile, license or engine.

| Source | State | Default | Formats | Acquisition granularity | License scope | Last checked | Scoped local examples |
|---|---|---|---|---|---|---|---|
| [nvidia-usd-search](https://search.simready.omniverse.nvidia.com) | enabled | yes | USD | dependency_closure | unknown; per-asset review required | 2026-11-08 | 1 |
| [abo-glb](https://huggingface.co/datasets/codepawl/abo-glb) | enabled | yes | GLB | single_file | CC-BY-4.0; per-asset review required | 2026-11-08 | 1 |
| [gso-glb](https://huggingface.co/datasets/codepawl/scanned-objects-glb) | enabled | yes | GLB | single_file | CC-BY-4.0; per-asset review required | 2026-11-08 | 1 |
| [usdcraft](https://huggingface.co/datasets/nvidia/USDCraft-10K) | enabled | no | USD | dependency_closure | Apache-2.0; per-asset review required | 2026-11-08 | 1 |
| [polyhaven](https://polyhaven.com) | enabled | no | HDRI / material maps (selected IDs) | asset_package | CC0-1.0; per-asset review required | 2026-11-08 | 1 |
| [simready-central](https://nvidia-simready-central.hf.space) | audited | no | USD locators (metadata only) | dependency_closure | unknown; per-asset review required | 2026-11-08 | 0 |
| [projectsim-public](https://huggingface.co/datasets/projectsim/simready-assets) | audited | no | USD | asset_package | unknown; per-asset review required | 2026-11-08 | 1 |

## Lifecycle inventory

- **enabled**: nvidia-usd-search, abo-glb, gso-glb, usdcraft, polyhaven
- **audited**: simready-central, projectsim-public
- **candidate**: (none)
- **quarantined**: (none)
- **reference_only**: (none)

## Limits of the recorded examples

### nvidia-usd-search

Selected asset: `https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.2/Isaac/Props/PackingTable/packing_table.usd` at `metadata-sha256:c080da0578bd32decaa2dc3c423629f390722ff901cb0a00527d2ed43c080f27`.

- Bounded metadata search without model or inline-image acquisition.
- Selected immutable content closure through the existing legacy USD compatibility route.
- Bare-table member used as visual-only geometry with measured ordinary static proxy support.
- Limitation: The selected native table mesh has no claimed verified collision or dynamic-body capability.
- Limitation: Unresolved individual asset licensing continues to block the new NVIDIA asset_plan route.
- Limitation: No blanket asset-library physics, redistribution, or preparation guarantee is asserted.

Observed target: physx, 6.2.0-rc.14+release.52805.02189a84.gl, 0.25.11, linux-x86_64.

### abo-glb

Selected asset: `B01DN8TB5U` at `c7c8293fed3b7ab122ef5d7896521a187e0962d7`.

- Bounded pinned JSONL bootstrap and metadata search; warm searches require no HTTP transfer.
- The selected standard GLB prepared as a passive rigid notebook at 150mm longest extent and experimental 0.12kg mass.
- Four independently observed instances pass gravity displacement, specified ramp/baffle/floor contacts, complete target bounds, settling and frozen input/evidence checks.
- Limitation: Evidence covers this selected asset, profile, parameters, layout and observed engine only.
- Limitation: Repeated clean initialization establishes fixed-layout repeatability, not layout generalization.
- Limitation: No manufacturer mass, whole-dataset physics coverage, alternative GLB-variant support, or token/time advantage is asserted.

Observed target: physx, 6.2.0-rc.14+release.52805.02189a84.gl, 0.25.11, linux-x86_64.

### gso-glb

Selected asset: `ReadytoUse_Rolled_Fondant_Pure_White_24_oz_box` at `75e8895e4f4e854cddd7009a7e60f86812041012`.

- Pinned standard objects GLB, 120mm longest extent, experimental 0.12kg mass, measured convex hull.
- Canonical catalog/plan/durable preparation followed by a new 600-step actual imported-body drop with complete source/input/evidence pins.
- Matched missing-support control fails support contact, containment and settling while the body still falls.
- Limitation: Selected object and explicit experimental parameters only; no source-wide physics or manufacturer mass claim.
- Limitation: The engine/KTX2 viewer variant was not substituted for the verified standard GLB.

Observed target: physx, 6.2.0-rc.14+release.52805.02189a84.gl, 0.25.11, linux-x86_64.

### usdcraft

Selected asset: `ds_R021_02` at `92f4e908415d7532a02661d6502ab49dc3aa33f9`.

- Selected public metre/Z-up cabinet retains two native rigid links, one hinge, limits, masses, colliders, native friction and articulation root.
- Canonical prepared selection passes actual forward/reverse driven motion and limits with native DOF and same-sample body-frame measurements.
- Separate passive contact experiment and missing-striker-collision control discriminate downstream joint motion; missing native mass is rejected.
- Limitation: Only a canonical single-DOF graph is supported; noncanonical joint/inertia scaling and multi-DOF imports are rejected.
- Limitation: Passive prototype used an explicit heavy gravity-loaded bench fixture; no consumer-load, structural capacity or manufacturer validation is asserted.
- Limitation: Drive targets are declared schedules, not contact-triggered causality. Newton was not tested.

Observed target: physx, 6.2.0-rc.14+release.52805.02189a84.gl, 0.25.11, linux-x86_64.

### polyhaven

Selected asset: `studio_small_03` at `77caaff5b801972cfe022fd3d0f2ff4b946721ba211da0a59f366bf6e48473ab`.

- Explicitly selected 1k EXR acquired with declared size/MD5 and actual SHA256, verified warm restoration with zero new transfer.
- Normal plan/preparation produces a self-contained light-only USD with no geometry, invented bounds or physical body.
- Native two-camera rendering verifies the HDRI texture inside the hashed prepared snapshot, source print and contact shadows.
- Limitation: Metadata provider searches only the explicitly configured bounded asset IDs.
- Limitation: Selected material maps have metadata/acquisition helpers, but material geometry preparation is not claimed.
- Limitation: Diagnostic camera crop was recorded; the short smoke does not certify final-film framing.

Observed target: physx, 6.2.0-rc.14+release.52805.02189a84.gl, 0.25.11, linux-x86_64.

### simready-central

No locally executed example is recorded.

### projectsim-public

Selected asset: `industrial_pipe_valve` at `3d0c039b383b88f83a6bb137c0b77372b34876ee`.

- Pinned BOM package search, selected acquisition, durable visual-only preparation and two-frame native shader smoke.
- Original materials and package-local textures retained; no source dynamic or articulated validation claim.
- Zero-download source-closure and prepared-snapshot eviction/restore with exact content identity.
- Limitation: Only this pinned per-asset descriptor/BOM and visual-only profile were admitted. Other packages are not enabled by this evidence.
- Limitation: Unchanged source has three rigid bodies and two native joints; the current articulated profile rejects that topology. No articulation or source dynamics support is claimed.
- Limitation: Two original collision meshes keep guide purpose and have physics APIs stripped; all 33 rendered meshes retain their original material bindings.
- Limitation: Optional conformance and root metadata names in the descriptor are stale/unverified. Aggregate vendor package conformance is not asserted.
- Limitation: The first 128 MiB staging attempt failed after 44,831,072 downloaded bytes; a separately approved immutable plan with 256 MiB staging succeeded using zero new download bytes.
- Limitation: Preview retained one nonfatal omni.rtx invalid-semantic material warning; actual raw/decoded images show original textures without missing-red-material appearance.

Observed target: physx, 6.2.0-rc.14+release.52805.02189a84.gl, 0.25.11, linux-x86_64.

HF discovery returns **candidate repositories**, not registered sources or prepared assets. It never changes this registry automatically. Repository rows, renders and variants are not unique-object counts.
