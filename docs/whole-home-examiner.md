# Independent whole-home examiner (external v3)

`experiments/whole_home_fidelity.py` and `experiments/whole_home_suite.py` are
read-only supplements outside the frozen v40 plugin. They never author a
mechanism, start Isaac, choose coordinates, release a body, apply a force,
repair a project or manufacture an observation. Synthetic CPU fixtures in
`tests/test_whole_home_examiner.py` are counterexamples, not simulation evidence.

External v3 adds only exact synchronized translations of existing passive
world-joint anchors during a predeclared layout variant. The complete v1/v2
code/policy/test archives remain preserved. No physical predicate, case value, time window,
contact witness, control, asset proof or motion-mask computation is relaxed.
The v40 plugin/P1 kernels and old P2 case remain byte-identical.

Each run now completes the same full stock check, supplementary fidelity,
original-mask CSV and (for the selected repeat) native-video checks before
the next run starts. Its **complete** report, including all stock per-step
records and masks, is streamed with `json.dump` into
`clock_directory/individual-run-reports/<name>.json`, atomically published
without replacing prior evidence. The suite's `runs` entries are small
summaries with that file's path/size/SHA256. They do not embed all eight full
reports. Only locks, canonical configuration, verified acquired identities,
case, geometry policy, native-capture metadata and original evidence hashes
survive between runs. The result records `orchestration_version: 3`. The bounded
memory orchestration introduced in v2 is unchanged.

The single-run wrapper lets the unchanged stock checker finish before loading
the outer raw observations, and checks that the run/evidence lock hashes stayed
identical across that ordering. It no longer adds an outer third raw copy while
a stock control holds its current/reference pair. After the per-run report and
clock are saved, both raw observations and the full report are released. Native
inspection receives the small, already-verified capture metadata rather than
reloading a multi-gigabyte result. CPU tests check actual object release,
metadata size independent of step payload, untruncated disk reports and the
unchanged all-or-fail suite comparisons. This is a bound on retained structures,
not a measured promise of a particular RSS: the immutable stock control still
loads its own current and positive-reference observations together. Its intrinsic
paired peak remains, and every original full lock/physics check still executes.

The generic rules/code are frozen before formal house attempts. A scene-bound
contract is still **unbound** until the independent examiner receives only the
fresh builder's nominal spec, role map, asset/proxy measurements and static
preview. Engineering trajectories are not used to tune acceptance thresholds.
No current P3/P4 acceptance follows from publishing these files.

The software basis is v40/commit `da42fdd8b1f1d0f381050533fc48a63e87ca3b9c`.
The software record SHA256 is
`efdfdc9f54f8d9326997e4051e95ef507b6f1ba696a126cdb97b1d38c7fc1435`.
The suite rechecks its 1,078 installed files, 93 checkout source files and the
immutable network/P1 kernels. It does not modify them.

The full network still has to pass the original v40 evaluator: at least 200
named real tiles, every named tile finally at least 60 degrees, six meaningful
transmitting household categories, at least 50 seconds span and 45 seconds
purposeful union activity, occupancy at least .85 and longest idle at most two
seconds. Books, rope, support hardware and decorative assets do not count as
tiles. Independent semantic review rejects pins/supports renamed as housewares.
The complete cube must remain in its independently measured receiver bounds.

The supplement additionally freezes at least 121 terminal samples at 60 Hz and
checks `(stable_confirmation_step - stable_onset_step) * dt >= 2.0`. The timing
window still ends at the original first complete entry, excluding confirmation
waiting. No later entry may replace an escaping first entry. This new-house
rule changes neither the P2 case nor its old 120-sample confirmation marker;
the P2 descriptive appendix records its actual 20.5333-second stable tail.

The public scene-bound schema is `simscene.whole_home_fidelity.v1`. It requires:

| Field | Frozen meaning |
| --- | --- |
| `network_case_sha256` | Exact independently frozen network case bytes. |
| `nominal_configuration_sha256` | `canonical_sha(canonical_spec(spec, verified_asset_identities))`, captured during static preflight. Only scene ID, revision and request metadata are excluded. All other fields, including camera/capture configuration, stay exact. |
| `static_review_sha256` | Independent nominal role, household identity, visual/proxy fit, support/clearance, mass/inertia derivation and permitted-energy/force review. |
| `physics_dt_s` | Actual frozen physics timestep, matching every run lock. The v40 baseline is 60 Hz. |
| `cart` | Body, upstream-to-outgoing event phase, unit signed progress direction, positive speed/travel floors and actual wheel records described below. |
| `cable` | Weight/load roles, sole load-end attachment, exact additional passive joint inventory and honest model description. |
| `bridge` | Matching nested wheel/door contract, bridge-crossing event phase and positive minimum actual pin-door callback updates. |
| `activity_excluded_body_ids` | All rope links, free pulley and cart wheel roots; their structural spin never supplies task seconds. |
| `activity_groups` | An exact partition of registered task stage IDs into named acts. |

This v1 scope reuses complete nested `rope_drawer`, `wheel_door_bridge` and
`spoon_sugar` assertions on the original unsliced telemetry. The original P1
event contracts have their existing role/type/world-anchor restrictions. A
legitimate nominal mechanism outside those semantics is reported as unsupported
by this supplement, not as unphysical. Any necessary generic extension must be
reviewed and versioned before formal attempts; it must not change v40/ce05 or
silently reinterpret a case. No hypothetical extension is pre-authorized.

Each cart wheel declares `body_id`, `joint_id`, `carrier_body_id`, static
`support_body_ids`, physical `radius_m`, signed `spin_sign`, positive
`minimum_rotation_degrees` and
`minimum_signed_angular_speed_degrees_s`. The cart declares positive
`minimum_progress_m`, `minimum_progress_speed_m_s` and a frozen
`minimum_grounded_rotation_distance_fraction` in (0,1]. These scene-specific
floors are chosen from nominal geometry/function before formal observations;
this generic schema supplies no success-derived default.

The cart phase must match its signed linear activity stage, which has no
independent angular-speed branch that could reward vertical bobbing. During
forward progress, the evaluator requires correctly signed axle angle changes
and actual wheel-ground callbacks in the same recorded intervals. Coverage is
weighted by distance, so a late spin cannot stand in for earlier sliding.
The actual net `radius * signed_angle / signed_cart_progress` is reported
descriptively, without claiming calibrated no-slip. Per-step callbacks are
indexed once by observation step. Existing first/last summary contacts do not
substitute for these witnesses. Visual marker readability needs later frame
and motion review; a single static image cannot establish rolling.

The bridge requires the full frozen wheel/latch/door-seat/retainer/released-pin
sequence and region crossing, plus actual pin-door callback data inside the
declared bridge phase. Its role/hinge must be the one locked in the negative
control. The cable's joint graph must connect weight to load before the exact
cut and disconnect them after removing only that attachment. Extra planar
constraints cannot attach directly to the load. This graph is not a tension
sensor: actual wrap/rim contacts, wheel motion, slack/taut behavior and the
matched broken-rope counterfactual remain mandatory in the nested contract.
The static review must explicitly disclose planar articulated approximations,
self-collision/CCD choices, damping, cradles and proxy collision geometry.

`static_stage_catalog` reads the actual composed USD: active joint/body APIs,
frames, physical attributes, gravity and transform/physics time samples. It
rejects drives, force/surface-velocity candidates, enabled kinematics,
time-authored action transforms and known behavior/graph actuation candidates.
It does not claim to read live forces from PhysX. The independent source/energy
review, frozen worker, strict restored t0 and actual loaded passive settings
remain necessary. `mass_catalog` requires each dynamic root's cooked positive
mass, local COM/principal frame and symmetric positive inertia tensor readback.
Appearance of an acquired mesh is not a mass calibration of that household
object. Proxy fit and semantic identity are independently reviewed from nominal
static evidence rather than inferred from a successful chain.

The static review is JSON with `passed: true`,
`scope: "nominal_static_preflight"`, `reviewer_role: "independent_examiner"`,
the exact `network_case_sha256` and `nominal_configuration_sha256`, and explicit
`role_asset_proxy_review_passed` / `energy_force_catalog_passed` flags backed by
the review's measurements/images/catalogues. These are examiner records; the
builder does not self-certify them. Acquired identities come only from complete
pinned content/dependency proof. In-memory dictionaries do not gain trust.

The suite schema is `simscene.whole_home_suite.v1`. Its manifest names the
software freeze, main contract/review/freeze, exactly three main positive run
directories, `no_trigger` / `broken_rope` / `locked_door` controls, one variant,
one editable-project replay, the complete attempt ledger and all formal run
roots, the selected native-positive index and fixed/tracking camera IDs, and
fresh external clock directory plus the provided clock script path.

The variant record names its own run, contract/review/freeze and predeclared
change document. That document has `cup_body_id`, a unit-metre-world
`cup_delta_world_m` of norm exactly .20, nonempty `additional_spec_changes`
and `case_geometry_changes`. Each edit is an exact `path` / `before` / `after`
patch. Another physical local geometry/asset change is required. Physics knobs
and global timing/quiet/tilt thresholds cannot be hidden among variant edits.
Case edits are restricted to declared receiver/support/bridge geometry and
activity ROIs; all other case content remains exact. Independent review still
must approve their physical meaning before freezing the variant attempt.

The only additional joint edit allowed in v3 is the exact four-component path
`["objects", "existing_joint_id", "joint", "local_pos0"]`, replacing its entire
finite three-vector. The original joint must be an enabled supported passive
fixed/revolute/prismatic/spherical joint, with world `body0` (null/default) and
an existing, initially present, dynamic colliding primitive/compound `body1`.
The original joint must pass the frozen passive schema validation; drives,
targets and unsupported fields are rejected. The same declaration must include
an explicit entire `body1.position` patch with finite nonzero translation; its
authored orientation must remain unchanged. The anchor's change must equal
that body's position change. The absolute 1e-12 m comparison bound handles
floating-point subtraction roundoff only and does not alter any physical
anchor-error/quiet/contact tolerance.

Anchor component edits, a whole-joint replacement, another joint frame,
rotation, axis, limits, connections, enabled state or collision-enabled state
remain forbidden. Overlapping patches remain forbidden. The anchor edit itself
does not count as another layout change: at least one patch must still pass the
original local physical geometry/asset rule. Independent static review must
confirm that this other change is meaningful and independent of the required
cup shift. No additional case-geometry path or sugar-dimension contract is
exempted. Variants without anchor edits retain the original v2 predicates.

The replay names a distinct run under a genuinely new project directory and
an independently prepared export preflight. Root owns project export/preflight,
not this examiner. Its document has
`scope: "independent_editable_export_preflight"`, `passed: true`,
`source_run_directory` identifying an accepted main repeat,
`project_directory` containing the replay and a nonempty exact
`files_sha256` map. The suite rechecks those files and requires the full replay
to pass the unchanged main physics/fidelity contract, matching canonical
assets/configuration and all runtime fields. A check-only export does not count
as a physics replay.

`simscene.whole_home_examiner_freeze.v1` records a timezone-aware
`frozen_at_utc` and `files_sha256`, keyed by absolute file path. It includes the
bound contract, static review and both external scripts; a variant freeze also
includes its exact change document. Each freeze must precede its original
run-lock `created_at_utc`. These local chronology records are auditable, not
external timestamp signatures. The generic archive precedes scene binding;
the final nominal freeze must occur before the first formal house attempt.

The attempt ledger is an ordered JSON list of `{kind, run_directory}` with
`kind` among `main_positive`, the three control modes, `variant`, and `replay`.
The examiner enumerates every run with either frozen case under every declared
run root. Earlier unsealed/failed attempts must remain in that inventory with
their input records. Ledger order is checked against original snapshot dates;
three consecutive positives are selected by those dates, so a failed attempt
cannot be reordered away. All eight accepted runs must be distinct. All 13
runtime manifest fields and recorded geometry policy match across the suite.

Every accepted main/variant/replay emits functional-role CSV from the original
network masks. CSV row `step` is checker `physics_step - 1`; rows cover exactly
`[release, first_whole_entry)`. The kit's unchanged clock reaggregates that CSV
and must reproduce all four original metrics. Acts and role seconds are also
reported. Acts can overlap, so their totals cannot be summed as elapsed chain
time. Missing intervals fail, not silently count inactive. Clock exports and
suite reports use fresh paths outside sealed runs and preserve earlier files.

At least one repeat must have same-run native 1920x1080/30 recordings from a
fixed camera and an along-path moving camera. Video decode and original frame
provenance must be continuous, cover release through stable confirmation, and
agree with the strict t0 absolute physics boundary. The helper calls the frozen
native inspector with the actual capture record. It does not synthesize frames
or count camera motion as task activity. The 90–120-second director cut, labels
for slow motion/repeats/audio, source mapping and causal/marker/proxy visibility
still require independent visual review. `complete_delivery_accepted` therefore
remains false in this physics-suite tool, and nothing authorizes publication.

Once all bindings and evidence exist, read-only invocation is:

```bash
PYTHONPATH=/home/dell/.local/share/simscene/plugins/simscene-v40/server/vendor:. \
  /home/dell/.local/share/simscene/venv-v31/bin/python \
  experiments/whole_home_suite.py /contracts/house-suite.json \
  --output /new-reports/house-suite-check.json
```

Keep the large JSON in the output file. Passing one run, a thumbnail, an export
precheck or the CPU counterexamples never accepts P3/P4 on its own.
