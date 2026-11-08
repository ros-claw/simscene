# Independent whole-home examiner v4

This is the explicitly versioned external examiner for the v41 network kernel.
The frozen v3 files and archives remain intact. The new files are
`experiments/whole_home_fidelity_v4.py` and
`experiments/whole_home_suite_v4.py`; contracts use
`simscene.whole_home_fidelity.v2` and suite manifests use
`simscene.whole_home_suite.v2`. The orchestration version is 4.

The software freeze is `generic-freeze/v41-software.json`, SHA256
`17aaa6433e87e2cc9101908492e272d8b7955687a99511ad3f3d23b3dc2d98ce`,
source commit `732e601`, with 1,080 installed files and 105 checkout source
files. The code rechecks both inventories and exact bytes. The separate root
release gate still requires its retained old-P2 regression; this software
freeze does not claim that check ran. There is no formal case binding or
permission to start formal jobs from a generic helper freeze. No candidate
runtime outcomes informed this version.

The code pins these independently frozen kernels:

| Kernel | SHA256 |
| --- | --- |
| passive network | `0ed9160f0225bcba3e621c2b22ce0a36720ca67203cb29330883abfd99a1adc1` |
| mechanism | `ce05b85cd11af946901f77249e6d16208434d5764056c5ba704a97beb4c9f4e8` |
| typed structural loads | `e75f33f48ac0c4f5e491b0666d0b5c5694f1698240a1561e7d01a2fa6b986c42` |

`simscene.passive_network.v1` retains its original predicates; only explicit v2
declarations admit the narrowly typed gravity support/friction pad described in
[structural-loads-verification.md](structural-loads-verification.md). All modes
must pass that new kernel's actual contact/free-guide/quiet proof. Its pad IDs
receive no task-path, household-category or activity credit. There is no new
exception to isolated control comparison or imported-asset identity checks.

Every existing fidelity contract field remains required, and v2 adds an exact
`non_contact_auxiliary_body_ids` list. It can be empty only when independent
static review establishes that no such auxiliary is being claimed. Every
listed body must also be in `activity_excluded_body_ids`, together with all
rope links, free pulleys, cart wheels and explicitly typed structural-load pads.
The independent static review must contain
`non_contact_auxiliary_review_passed: true` and exactly the same ordered
`non_contact_auxiliary_body_ids` list. This is a separately bound physical-role
review, not an exception supplied by the scene author or inferred from success.

`bind_non_contact_auxiliary_bodies(spec, case, body_ids)` is a static-only role
check. Listed bodies must be initially present real dynamic colliders. Task
paths, measured task events, categories, terminal/trigger bodies, cable roles
and declared support pads cannot be relabelled non-contact auxiliaries. The
contract also rejects using cart, roller or carrier fidelity roles as such
auxiliaries. The global stock kernel still inventories and checks their passive
joints, quiet behavior and controls. This designation itself adds no graph
connectivity, activation, semantic household kind, force reading or timing.

`non_contact_auxiliary_bodies(...)` then examines the complete original strict
clock and **every original raw per-step callback** for every mode, including
stopping controls. It validates actor/collider/body identity, count and original
absolute callback boundary without constructing an activation instant. Any
callback involving a listed auxiliary and any other actual actor—including the
initial cue, static ground, a task body or another auxiliary—fails. Missing
steps/contact lists, truncation, malformed callbacks and differing journal
inventory fail. An omitted journal record cannot conceal a raw callback.
Aggregate first/last-contact summaries do not substitute for the original
nonempty physical callback records. Zero callbacks is an observation statement,
not proof of continuous separation or measured guide reaction forces.

The original static USD catalog's unbounded **schema defaults** can contain
infinities, which strict JSON cannot encode as numbers. V4 preserves them as
explicit `{"nonfinite_schema_value": "-inf"}` (or `inf`/`nan`) tags and records
whether a value opinion is authored. Values are not dropped, clamped or changed
to finite limits. Authored nonfinite physical parameters—including quaternion,
gravity and velocity values—are rejected and retained as tagged evidence.
Unknown mandatory physical quantities still need the original source/static/
runtime proofs; a tagged default is no substitute. This fixes catalog evidence
serialization, without changing guide, contact, time, quiet or terminal bounds.

All previous physical and orchestration rules remain. The old cart/cable/bridge
fidelity functions, 121-sample and actual two-second floor, original union masks,
provided-clock `[N,M)` CSV export, mass catalog, exact variant comparator, native
frame verification and suite orchestration are checked by AST regressions.
Specifically, all 200 named real tiles must first and finally tilt at least
60 degrees; at least six meaningful household kinds must transmit; span is at
least 50 seconds and net purposeful union activity at least 45 seconds, with
occupancy at least .85 and longest idle at most two seconds. Original earliest
complete sugar entry and whole-cube/no-later-exit/stability checks remain intact.
No confirmation wait or structural spin contributes task seconds.

The suite still requires three retained consecutive clean main repeats, all
three exact isolated controls, predeclared cup translation of 0.20 m plus an
independently meaningful local layout/asset change, and a full editable replay
from a distinct directory. All thirteen runtime manifest fields, exact acquired
asset identities, canonical camera/presentation configuration and recorded
geometry policy must match. A synchronous world-anchor translation remains only
the narrow v3 allowance and supplies no independent layout credit.

Full individual stock/fidelity reports and original masks are streamed to disk
before the next run; only small verified configuration/provenance metadata and
summaries remain. The stock control still owns its intrinsic current/reference
pair. The v2 bounded-retention design and exact lock checks around stock/read
ordering remain unchanged. New tests additionally check auxiliary failure gates
a control despite mocked other collaborators passing, without retaining the raw
run. These ordering fixtures explicitly do not certify synthetic physics.

Before a formal snapshot, freeze the main and variant case/contract/static
reviews, the exact variant declaration, all auxiliary proof/geometry files and
both v4 scripts in a chronological scene-bound freeze. The separate halfspace
observer keeps its own pre-job contract/freeze and independently retained sealed
run-lock/evidence-lock anchors; it remains an additive geometry observation.
No helper can establish that receiver planes match a modeled cavity without
independent static geometry review. GPU jobs, scene edits and publication are
outside these examiner programs. No P3/P4 success follows from these files.
