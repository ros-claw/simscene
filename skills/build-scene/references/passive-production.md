# Build passive experiments with small, inspectable steps

Choose the entry path before authoring:

- **Reproduce:** acquire only the locked selections, import the ordinary recipe,
  run the pinned case. Do not regenerate a working layout from prose.
- **Modify:** identify the changed input/output/support port and its immediate
  receiver. Test that interface before paying for a whole-scene recording.
- **Create:** establish a physical goal and an intervention that would prevent
  it. Start with a small bench and visible collision geometry.

Read `passive-mechanisms.md` for the primitive/joint schema when needed. A passive
joint has no drive; an observation callback must never release an object.

## Parameter modules

`python3 skills/build-scene/scripts/plan_mechanism.py DEFINITION.json --output PLAN.json` compiles
repeated geometry on the simulation host. It prints a small plan reference,
hash and ports; the ordinary operations remain in the file. Definitions have
exactly `kind`, `prefix`, `parameters`:

```json
{"kind":"domino_line","prefix":"wave","parameters":{"count":24,"origin":[1,2,0.8],"spacing_m":0.065,"size_m":[0.018,0.08,0.14],"mass_kg":0.012}}
```

- `domino_line`: count2..512, metric size, centre spacing, optional supporting
  slab thickness (0 means caller supplies the surface).
- `domino_arc`: count, radius and signed sweep in degrees. Initial overlaps and
  excessive reach gaps are rejected; this does not establish wave propagation.
- `door_bridge`: length/width/thickness, raised angle and landing support.
  It authors a compound panel, passive hinge and landing block. The default
  panel is **unlatched**. To trigger it later, add a real retaining object at
  the returned retainer port; it does not synthesize a time-based release.

`origin` is the support top or bridge pivot; `orientation_wxyz` may rotate yaw.
For an arc, origin is under the first tile, not the circle centre; its initial tangent is local +X and the sign of sweep sets curvature. `radius_m` and `sweep_degrees` are the exact arc keys. These v1 modules require a horizontal support frame. Ports use world metres. Commands above start at the repository root; in an installed package use the corresponding skill scripts by absolute path.
Model-source, local frames, masses and solver settings remain explicit. A schema
pass is not a tested parameter range: test changed loads, scale, support and
collision neighbours. The rope planner remains a separate, experimental model;
do not advertise an arbitrary pulley route as validated by the sugar example.

Apply ordinary operations with the current revision and request ID. When the
installed CLI provides the module interface, `simscene mechanism apply --scene
ID --base-revision N --request-id KEY --plan PLAN --sha256 SHA` applies the exact
deterministic expansion without sending hundreds of objects through the model.
For an older backend, load the operations file in a host-side MCP client and
call existing `scene_apply`; keep that call and readback in the evidence.

## Diagnose the first failed transfer

`python3 skills/build-scene/scripts/diagnose_handoff.py --report FULL_REPORT --case CASE --output
DIAGNOSTIC.json` reads a retained passive-network report. It returns at most a
small summary; details, hypotheses and source hashes remain in the artifact.
It never reads multi-gigabyte trajectories just to summarize an existing report.

Follow the earliest rooted causal frontier: last completed event → first failed
transfer → its actual bodies, supports and obstacles. Distinguish observations
from hypotheses. Check a contact/clearance/axis near that boundary before
altering an idle downstream mechanism. In parallel branches, causal depth does
not give a unique time order or prove a root cause.

A negative control needs both its intended downstream block and its required
upstream activation. If the upstream never arrived, the control is inconclusive
even when the drawer/receiver stayed still. Missing samples, changed case
identity or incomplete integrity produce `unknown`, never an inferred pass.
The helper supports passive-network event graphs; other cases may require the
original checker and targeted state/contact queries rather than this helper.

For a local probe recreate a small **initial-state** bench with the real
support, obstacle and receiver. Do not teleport the full scene to a later pose
and call the result an uninterrupted passive experiment. Record the hypothesis,
changed parameters, job ID and result; retain failed attempts.

## Let the host wait

Start once with a stable `simulation_start.request_id`, retain the returned job
ID, then wait on that same job. On backends with the extended interface,
`job_status(wait_seconds=600,receipt_path=...)` waits and writes a compact receipt;
set a compatible MCP client timeout. Otherwise use `scripts/wait_job.py` in the
same SIMSCENE_HOME. Queued or stalled jobs are not permission to start another.
The wait receipt distinguishes observed from inferred exit codes and never
claims physical acceptance. Run the case verifier separately.

A resumed client must reconnect to the same persisted job. Preserve an old
client's unknown/nonzero exit and any interrupted logs; never replace them with
a later worker EXIT0. Only new, explicitly identified verification outputs may
express a later decision. Complete a full combined run after local interfaces
work, then record the requested video quality. Edit-only changes reuse media;
new cameras may use recorded-pose replay with its distinct provenance.
