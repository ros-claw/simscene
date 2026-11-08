# Catalog gravity cell

Rebuild a fixed gravity-routing scene with four instances of the selected ABO notebook, two ramps, angled baffles and receiver floors. The notebook is the actual imported model, scaled to a 150 mm longest extent with an experimental 0.12 kg mass. The ordinary scene objects remain editable.

The selected NVIDIA PackingTable contributes its bare-table member as visual-only geometry. Its authored centimetres normalize to metres through the standard exporter; the transparent tabletop proxy and routing fixtures provide explicit static collision. No structural-load or manufacturer-physics claim is made.

Install SimScene and configure the local Isaac Python launcher. Explicitly set up the pinned decoder and record the actual runtime observation before running:

```bash
simscene asset setup-decoder --output /your/owned/new/converter-tools
export SIMSCENE_GLTF_TRANSFORM_PREFIX=/your/owned/new/converter-tools
simscene asset probe
python experiments/run_catalog_mvp.py --routing --output /your/experiment-output/new-run
```

These commands can download selected assets and launch Isaac. The output must be a **new directory outside the checkout**. Setup never installs automatically during preparation. A prior runtime observation must match the configured launcher and decoder installation.

For an explicitly warm run, reuse an existing experiment cache root containing `source-cache` and `prepared-cache`:

```bash
python experiments/run_catalog_mvp.py --routing \
  --warm-cache /your/experiment-output/previous-run/artifact-cache \
  --output /your/experiment-output/new-warm-run
```

`--smoke` runs only the left-front notebook under the same physical predicates. `--record` keeps the inherited diagnostic cameras: 960×540, 30 fps, the first 300 physics steps. The default performs physics verification without camera recording. This example does not deliver or claim a final 1080p promotional video.

The runner refreshes only the pinned ABO metadata index when needed, searches both explicitly selected reviewed sources, selects the exact locked identities, prepares the notebook through a durable job, applies ordinary scene operations, runs 720 steps at 60 Hz with seed 42, and calls the existing rigid-asset checker. It requires direct ramp, baffle and receiver-floor contacts, measurable gravity displacement, complete-object target bounds, settling, and input/evidence integrity. It makes no timing-order claim. A changed source file or closure fails rather than substituting another asset.

The 2 GiB scene allowance is charged serially from actual newly downloaded model/dependency bytes, including failed reads. The NVIDIA compatibility acquisition is capped at 512 MiB and notebook acquisition at 16 MiB. Metadata indexes have a separate 32 MiB refresh allowance. Cache capacity, unpacking and staging limits remain separate.

`case.json` is a template. Before each new simulation, the runner fills its prepared-manifest marker from that attempt's verified preparation result and writes a separate frozen case. That new hash does not reinterpret or relabel any earlier run. Same-machine repetitions establish fixed-layout repeatability, not layout generalization, independent reproduction, or speed/token improvements.

The NVIDIA source uses the **legacy bounded USD compatibility route**, not a ready `asset_plan` result. Its individual asset license remains unknown. The [official Isaac license FAQ](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/common/license-faq.html) documents separate restrictive source terms for supplied Isaac assets; those terms are distinct from Apache-licensed search/application code and from CC-BY-4.0 assets elsewhere. This example accepts no gated terms and asserts no redistribution grant. The source URLs and references are in `assets.lock.json`. The ABO conversion declares CC-BY-4.0; preserve its notices and upstream attribution. No model payloads are included here.

Each attempt retains its input copies, metadata requests, transfer accounting, preparation receipt and status, editable compiled scene, frozen case, simulation receipt and verification report in the requested output. Failed attempts remain inspectable. Do not copy private runtime records or asset caches into Git.

To exercise an actual Codex model turn through an isolated installed MCP package, use the bounded evaluator after building/installing that package:

```bash
python3 experiments/eval_catalog_agent.py --client codex \
  --package /your/isolated-installed-package \
  --case examples/catalog_gravity_cell/agent-task.json \
  --output /your/experiment-output/new-agent-trial \
  --model YOUR_CONFIGURED_MODEL --reasoning-effort medium --wall-limit-s 900 \
  --v2-config /your/v2.json --cache-root /your/source-cache --cache-condition warm
```

Here `--cache-root` names the source-cache directory directly; the V2 configuration separately names the prepared cache and observed runtime manifest. Declare `cold` only when all relevant caches and indexes actually start empty. The evaluator checks the preserved tool trace, fixed source and layout identities, real run receipts and independent physical verdict. It keeps actual usage counters when the client supplies them. Its command-scope audit is a bounded heuristic, not an operating-system read sandbox. An explicit reassessment writes a separate result and never replaces an earlier verdict. A single warm trial does not establish token savings.
