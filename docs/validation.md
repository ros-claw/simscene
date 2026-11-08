# Validation scope

SimScene has completed a stage covering online asset composition, physical
interaction verification and multi-camera video delivery. Reusable production
tools are included. Cross-task token advantages remain to be established by
comparable real use.

V2 preview `0.2.0.dev1` retains 46 legacy MCP schemas and adds six tools.
The final source passed 1,115 CPU tests (five conditional skips), both build
paths and extracted transport checks, plus Python 3.10/3.12 CI. Actual SDK
validation is separate: imported rigid bodies, native hinge motion, generated
parts, a four-camera 3,600-step gallery and its matched stopping control.
Two final-package Codex tasks passed independent video/physics and GLB/physics
checks. See [release qualification](../examples/catalog_benchmark/results/release-qualification.json).

Validation is specific to a source revision, preparation profile, runtime,
scene and frozen case. Search results, successful conversion, an SDK exit code
and a physically successful task are different evidence levels.

## V2 imported assets

The [catalog capability matrix](validation/catalog-capabilities.md) records
selected GLB rigid bodies, preserved native joints, open containers, HDRI
lighting and optional generated parts on the actual Isaac Sim 6.2 RC runtime.
It distinguishes declared asset facts, inspected preparation and measured
physics. Source registration does not certify an entire library.

The [gravity cell](../examples/catalog_gravity_cell/README.md) documents the
selected ABO notebook and NVIDIA visual workbench, including fixed source
locks, physical predicates and new-run reproduction. The imported notebook
itself moves and contacts the fixtures; it is not a decorative substitute for
a primitive payload. The workbench remains visual-only with measured static
collision proxies and unresolved individual asset licensing.

The [measured efficiency study](validation/catalog-efficiency.md) separates common
legacy tasks from new capabilities, keeps failure costs, and leaves missing
usage unknown. Historical development hours are not a token baseline.
The original 36-session comparison did not establish savings; its four passing
common-task pairs had a median token ratio of 1.1201. Later capture/audit fixes
and qualification are separate from those original results.

## Three-level passive chain

The [three-level example](../examples/three_level_chain/README.md) contains four
balls, 60 independently moving dominoes and 63 required contact edges. Three
clean fixed-layout repetitions, no-trigger and missing-middle controls, an
edited layout and editable-project replay were checked in the original
experiment. Its physical actors are primitives. Imported shelves, workbench
and trays provide visual geometry with explicit static collision proxies.
These results are not evidence that arbitrary downloaded meshes were already
dynamic rigid bodies.

Use the example's independent checker and exact frozen case. A normal worker
exit does not establish the chain's contact order or necessary causality.
The public recipe is editable; same-host repetitions do not establish
second-machine compatibility or arbitrary-layout generalization.

## Whole-home sugar machine

The [whole-home example](../examples/whole_home_sugar/README.md) publishes its
recipe, declared approximations and a compact
[acceptance/provenance record](../examples/whole_home_sugar/acceptance-provenance.json).
For the accepted configuration, 200 dominoes and seven functional household
roles lead to sugar entering a cup. The main chain spans 87.65 seconds with
87.0167 seconds of measured effective motion; overlapping motion intervals are
counted once. Edited movie duration is a separate measurement.

The retained suite includes three clean main repetitions, no-trigger,
broken-rope and locked-door controls, a layout variant and new-directory
editable replay. The replay's original outer session exited 143; the same
physical job completed and passed its documented recovery procedure. It is
not described as an uninterrupted outer-session success or a new physical
retry. Original outcomes and recovery receipts remain distinct.

Online decorative assets are visual attachments; functional doors, cup,
dominoes and other physical parts use the explicitly authored bodies/proxies.
The rope is a passive 55-capsule, finite-D6 model with endpoint connections and
an actual free pulley, not a calibrated fibre model. Read the example's
physical assumptions rather than treating its appearance as material fidelity.

## Robot examples and remote access

Earlier sorting/motion examples use model-specific robot profiles and declared
collision exclusions. Their discrete observations do not establish universal
robot motion, swept-volume safety or reliable avoidance for unfamiliar assets.
Failed and queued historical experiments were not promoted to passes.

A local SSH-tunnel/HTTP setup was tested. Cross-machine deployment must still be
validated in the target environment. Simulation-host assets and caches stay on
that host; a local simulation necessarily reads its selected geometry there.

## Reproduce and inspect

Freeze a new acceptance case before running. Verify its actual body/contact
mapping, task predicates, input snapshots and saved-output hashes. A prepared
cache hit reuses conversion, not an old physical verdict. The checker only
reads evidence and never repairs or triggers the scene.

CPU CI covers Python 3.10/3.12 contracts, pure offline providers and explicit
agent/package suites. It does not claim GPU acceptance. SDK-dependent tests
are opt-in; actual GPU/Isaac evidence is recorded separately with runtime
versions and case/source hashes. Live network probes remain separate from
ordinary offline regressions.

The [packaging matrix](packaging.md) distinguishes stdio loading, tool turns
and real simulation for each client. Public recipes, compact provenance and
rendered films are distributed; complete machine logs, downloaded models and
private session archives are kept outside the repository. A public digest is
an evidence locator, not a downloadable copy of those archives.
