# Validation status

This document records development evidence, not a declaration of first-version
acceptance. Actual simulation records and checks are in `evidence/`; unfinished,
failed and diagnostic trials are retained alongside successful ones.

The model-specific collision-audit planner proposes the previously documented
mechanical exceptions and the follower settings needed to collect discrete
overlap evidence. Its input validation, non-mutating proposals and MCP
transport have CPU tests. A proposal is not a passed physical audit; the
exact asset and every exception still require inspection and a completed run.
Preflight now rejects a stream collision policy that omits case robots or
does not match the scene's monitoring, self-collision and exclusion settings;
the physical audit remains the separate post-run check. An earlier queued
formal job was canceled before execution to freeze this change in all four
new suite runs; the cancellation record is in `evidence/formal-v10-preflight-restart/`.
The GPU queue now uses a stable per-user `/tmp` lock independent of `TMPDIR`,
so separate plugin hosts using different temporary-directory settings share
the same cooperative queue when they share that filesystem namespace.
- The supplied Isaac Sim 6.2.0 installation identifies itself as
  `6.2.0-rc.14+release.52805.02189a84.gl`; it was supplied after the 6.0.1
  runs began. Its robot configuration layout has moved, and the original
  Franka profile generation failed against 6.2. The integrated change finds the
  new cuMotion configuration location and generated all three profiles; it also
  reproduced the prior 6.0.1 profile hashes. A real 6.2 three-arm test with
  18 objects has passed; details and limits are recorded below. The 6.2
  sorting runs select the first A6000 through `CUDA_VISIBLE_DEVICES=0` and use
  CPU PhysX; the GPU is used by the rendered and motion-control runtime. A separate
  6.2 run did complete 120 physics steps, rendered
  a camera image and verified input/output hashes after reattaching to its
  worker; `evidence/isaac-6.2-exit-recovery/` includes the actual recorded zero
  exit code. It tests a falling cube, not robot sorting. An earlier 6.2 camera
  probe failed to obtain RGB and logged a zero-range timeline warning; stages
  now receive an explicit time range and camera warm-up; subsequent 6.2 runs
  produced images, without establishing the cause of the original failure.
  Another 6.2 smoke run loaded the previously selected USD Search conveyor from
  the simulation-host cache, ran 120 steps and saved an image with intact input
  and output hashes (`evidence/isaac-6.2-usd-search-asset/`). Its framing is
  cropped and it does not test conveyor motion or robot manipulation.
  Do not interpret the 6.0.1 evidence as 6.2 sorting support. The 6.0.1 suite
  was reattached to its immutable v10 package without interrupting its worker;
  the earlier code hashes remain available. For a legacy worker without an
  exit record, completion is inferred from its result and must not be presented
  as a directly observed zero exit code. Negative-control verification now rejects inferred exit codes.
  New jobs use a queue wrapper that records the actual child exit before it
  finishes; fake-process tests cover recovery and nonzero exits. One real 6.2
  cube run also verified reattachment and its recorded zero exit, as noted
  above; a second independent 6.2 reattachment probe also passed in
  `evidence/isaac-6.2-exit-recovery-v2/`.
- The local 6.2 agent guidance also informed candidate ambient/area-light
  support and an opt-in reactive obstacle binding for static primitives. USD
  schema export and invalid-input behavior have CPU tests. A real 6.2
  dome-plus-distant-light cube test completed 120 steps and produced the
  inspected image with intact hashes (`evidence/isaac-6.2-lighting-smoke/`).
  This is not proof of area-light behavior in every scene. Obstacle planning
  cannot certify a swept path.
- The first 6.2 obstacle-motion probe bound a real collision box into cuMotion.
  The per-step discrete audit found no unapproved contacts or overlaps, but the
  arm timed out 0.205 m from its goal. It is a failed motion, not a successful
  avoidance demonstration; the locked run is in
  `evidence/isaac-6.2-obstacle-direct-failed/`. A lateral detour also timed
  out, at 0.1063 m position error, although its discrete overlap audit and
  input/output locks passed; see
  `evidence/isaac-6.2-obstacle-detour-failed/`. An overhead trial also failed
  to complete its first raised waypoint, even though its sampled collision
  audit passed; see `evidence/isaac-6.2-obstacle-overhead/`. These tests do
  not establish reliable obstacle avoidance.
- The supplied `isaac-sim-remote` skill's full-app headless launch did not
  reach a ready local Python server within 180 seconds on this machine. Its
  log includes a ROS bridge startup failure; the timeout does not establish a
  single cause. The failed run is retained in
  `evidence/isaac-6.2-remote-full-startup-failed/`. A separate trimmed base-app
  probe passed local health and live stage edits in
  `evidence/isaac-6.2-remote-base-python-server/`; neither test establishes
  cross-machine remote access.
- A fresh retiming-edit session changed the belt speed and spawn spacing as
  requested, but ended while its simulation was still queued behind another
  test. The frozen checker therefore failed on the missing physical run. The
  agent correctly disclosed that no physical observation was available; after
  the session ended, the unused queued job was canceled. The trace and failed
  check are in `evidence/agent-edit-retime-v9-queued-failed/`. A new unassisted
  run when the GPU is available is still needed.
- Three other fresh sessions also ended while their last simulation was queued:
  `evidence/agent-three-arm-v2-queued-failed/`,
  `evidence/agent-online-v9-queued-failed/`, and
  `evidence/agent-edit-relocate-v9-queued-failed/`. We ran these tests
  concurrently, so they competed for the single simulation slot. Their frozen
  checks failed for lack of a completed run; remaining queued jobs were
  canceled after each agent had ended. The online session did genuinely search,
  inspect and acquire its chosen USD with no unresolved dependencies, but it
  did not complete a run using that asset. The relocation session used an
  incomplete collision policy; the new preflight detects this before launch.
  Repeat these agent tests with the simulator slot available and the final
  package rather than treating these attempts as passes.
- A separate fresh v9 session successfully exchanged the red and green robot
  routes, adjusted the corresponding bin colours and counters, observed the
  run, and waited for all 18,000 steps. Its pre-frozen checker found six of six
  case-checked placements, two per class, in distinct physical enclosed bins,
  with zero wrong bins and intact input/output locks. The trace and compressed
  run are in `evidence/agent-edit-swap-v9/`. The per-run case was derived from
  the edited scene; this does not establish full collision-path safety or the
  separately frozen multi-seed acceptance. The integrity checks were run at
  the original simulation-host paths; the archive retains those absolute paths
  and is not by itself a portable reconstruction of external assets.
- The first newly frozen v10 formal run, seed 17, completed all 48,000 steps.
  The pinned checker reported 59 of 60 correct, no wrong bins, and a passing
  discrete collision audit; this is one run, not the complete three-seed and
  long-duration acceptance. Its evidence is in `evidence/three-arm-v10-seed17/`.
  Seed 29 also completed the physical duration with 59 of 60 correct, no wrong
  bins and a passing audit; see `evidence/three-arm-v10-seed29/`. Its original
  OS exit code is unavailable after the documented supervisor transition, so
  the saved job status explicitly marks the exit code as inferred.
- A paired three-arm drive negative control against that seed-17 run completed
  its requested duration and passed: disabling Kawasaki drives produced measured
  zero gains and prevented the corresponding red pick. The other two paired
  controls are still required. See `evidence/three-arm-drive-control-v10/`.
- A separate 300-second presentation test added the physical chute to that
  arrangement and recorded four real cameras. It spawned 30 of the scheduled
  60 parts and archived 12 as correct by the stop time (red 9, green 1, blue
  2), with no wrong bins; the other 18 generated parts were failed or unfinished
  at that cutoff. The complete case and collision coverage check failed because
  later scheduled objects had not yet spawned, and the observed throughput is
  also insufficient to claim reliable feeder integration. An 80-second cut and
  the original check are in `evidence/three-arm-feeder-showcase-v10-diagnostic/`.
  Later feeder diagnostics and their outcomes are recorded below; this earlier
  presentation test is not a pass.

- Public USD Search was exercised for text and image search, metadata,
  thumbnails, download and a rendered selected asset. Hugging Face acquisition
  was exercised on a commit-pinned dataset asset. These results do not guarantee
  that every indexed asset has complete dependencies or usable physics.
- A fresh Codex CLI session searched online and used the bundled MCP server to
  create a conveyor scene, run it, observe a stationary parcel, add a moving
  surface, and rerun it. It used shell commands and a repaired local copy of
  the searched model while online acquisition remained pending. See
  `evidence/agent-codex-online/` for the actions and measured displacement.
- A separate fresh Codex session received a natural-language request and a single
  available Franka asset, then constructed a workbench with two rows of six
  open bins in total and an orbiting camera. It ran Isaac twice after seeing a
  cropped initial view. An independently written post-hoc geometry and playback
  check passed, including run integrity; the robot was not commanded to pick
  anything. See `evidence/agent-codex-workbench/`. This is not the formal
  pre-registered agent or three-arm acceptance. A separate frozen workbench
  case and checker were then used in another fresh session. The new agent built
  six open bins in two rows, ran the scene, observed a cropped view, revised
  the orbit camera and ran again. The frozen case passed for the second run,
  including the measured camera rotation, physical runtime, input/output
  locks and the fixed package/skill hashes. Prompt, trace, spec diff, two
  runs and screenshots are in `evidence/agent-codex-workbench-preregistered/`.
  This does not claim robot manipulation or three-arm acceptance.
  The same open-ended task was repeated after the queue and retry changes with
  a newly frozen package, skill, case and checker. The fresh session again
  ran and revised its scene, and the independent workbench checks passed;
  the two runs and their spec diff are in `evidence/agent-codex-workbench-v7/`.
- A real Isaac run rendered a spawned-object counter changing from 1 to 2 to 3
  as three objects entered the scene. Its sampled values, three extracted
  frames, video and input/output locks are in `evidence/display-probe/`.
  This test does not cover the verified-archive counter or status indicator.
- An isolated gravity-fed chute test spawned three cubes above an inclined
  physical surface. All three contacted the chute and the moving conveyor and
  remained on the belt downstream; the complete 1,800-step run and input/output
  hash checks passed. See `evidence/chute-probe/`. This establishes the feeder
  in isolation, not yet the combined three-robot scene.
- A separate three-arm MCP integration probe generated a case from the saved
  scene and supplied bin bounds, passed it inline to the simulation job, and
  ran 12,000 steps. All three workpieces passed the pinned physical case and
  were recorded in the checked archive ledger; the live verified counter
  reached three. The suction check included measured lift and the specified
  forbidden objects. See `evidence/three-arm-inline-case-probe/`. Because its
  case was derived from the scene, this is an integration check, not the
  independent three-arm acceptance. Its captured worker uses the earlier scope
  wording; current workers explicitly say that a case can be scene-derived.
- An exploratory fresh Codex session started from an empty scene and the three
  listed robot assets. After several real runs and corrections it built a
  gravity-fed chute, one moving belt, three robot stations, three actual
  cameras, case-backed counters and controller indicators. Its final 14,000
  step run checked and archived six of six items, two per class, in distinct
  physical bins with simultaneous robot activity. The user-facing case was
  derived from the generated scene; it was not the independent 60-object
  acceptance case. Its 65-second presentation cut comes from the earlier
  three-object run, not from the six-object run. Evidence and original trace
  are in `evidence/agent-codex-three-arm-exploratory/`.
  The session launched overlapping simulation jobs; we paused two older jobs
  to serialize GPU use and subsequently resumed them. Those interventions are
  recorded. The high-level checker was refined during the exploration rather
  than frozen before the session, so its overall result remains **failed** on
  those two procedural checks despite the six-object physical result. A new
  unassisted session with the finalized plugin and frozen checker is required.
- The shared worker now queues simulation jobs per account and host. A real
  two-job Isaac probe observed the second job queued until the first completed;
  both ran successfully with intact locks, and an identical request ID returned
  the first job instead of starting a duplicate. Queue pause, cancellation and
  recovery are also covered by CPU process tests. See `evidence/gpu-queue-probe/`.
  The queue does not coordinate other accounts or unrelated GPU applications.
- An isolated localhost SSH tunnel was exercised with actual Isaac, camera
  retrieval, pause/resume, a snapshotted case and input-lock verification. It
  does not establish cross-machine operation or native client installation.
- The three distinct arms completed a three-object upstream stream in one
  diagnostic, and three arms also worked simultaneously on three objects
  already at their stations. Neither establishes 60-object reliability.
- The nine-object GPU/default-physics stream repeatedly hit a PhysX internal
  CUDA error. A CPU-dynamics run completed 15,000 steps but passed only four of
  nine independent object checks, with wrong-arm and environment contacts.
  A subsequent hover-position diagnostic avoided those observed collisions but
  stopped at 8,226 steps after a controller timeout and dropped its second green
  object. A later slower-feed diagnostic correctly sorted six of nine before
  another controller timeout at 10,473 steps. These failures remain evidence;
  controller changes are exploratory. A subsequent full 16,800-step run
  correctly sorted seven of nine, with the two failures caused by robot-bin
  contact. Seven independently checked objects were recorded and reclaimed;
  the two unverified objects remained in the scene and the denominator. An
  initial same-slot reuse trial stopped early because Franka did not satisfy
  its motion-settling condition; its failed record is retained.
  The next same-slot run completed all 16,800 steps and passed eight of nine
  objects with no reported wrong-arm or robot-environment contacts. The first
  green object slipped during transfer despite landing in the correct bin, so
  it remains failed and was not reclaimed. Its saved input and output locks
  passed; this is still below the required per-robot rate.
  A trial lowering Franka’s global speed cap stopped earlier because its tracking
  error exceeded the fixed limit. The failed trial is retained.
  A transfer-only cap of 0.30 also caused a cuMotion configuration error
  because the model damping region is 0.35. The worker preserved partial
  evidence; new jobs reject this incompatible cap before launch.
  A subsequent 0.40 transfer-only cap completed 16,800 steps and all nine
  objects passed the independent checks, with no reported cross-arm or
  forbidden robot-environment contacts. Input and output locks passed. This
  one short run does not establish the required multi-seed or collision audit.
  Enabling articulation self collisions in the same nine-object scene retained
  six correct objects; all three Kawasaki picks failed while PhysX reported
  persistent contacts inside its wrist and gripper mechanism. This separate
  trial is a failure, and specific mechanical pair filtering is under test.
  Filtering six recorded Kawasaki linkage pairs restored all three Kawasaki
  picks in a subsequent nine-object run, but one Franka object slipped after
  an additional Franka finger-pair filter; eight of nine passed. The Franka
  filter was removed for the next trial. These records are retained separately.
  After removing that filter, all nine objects passed their individual checks
  with self collisions enabled. The discrete audit still failed on two Franka
  contacts recorded before controller reset; the record is not a passed audited
  run. New workers separate initialization from the frozen task timeline.
  With the reset timeline separated, a further nine-object run passed all
  item checks and the discrete collision audit, with self collisions enabled,
  the recorded mechanical exclusions, complete query coverage and verified
  input/output hashes. This remains one short diagnostic, not multi-seed
  acceptance or a swept-volume safety proof.
- The first 60-object seed-17 attempt did not reach its drain deadline: after
  25,357 of 48,000 steps, UR10's tracked target was far outside the work area
  and the controller failed. Of 43 spawned objects, 26 passed; the Franka
  gripper dropped several during transfer, and UR10 contacted the belt while
  chasing a displaced target. The result, failed checks and logs are preserved
  under `evidence/three-arm-formal-seed17-failed/`. The remaining seed runs were
  not started after these failures. A stronger-grip asset override and explicit
  target-workspace guards are under development. A separate 18-object test
  using an experimental Franka override (20 N drive limit, friction 1.0) passed
  all 18 item checks, simultaneous operation and the discrete collision audit.
  This is one diagnostic seed, not the required 60-object multi-seed result.
  A subsequent 18-object test combined the same experimental grip with the
  target-workspace guards, a catch floor, recovery bin, verified item counters
  and controller-state indicators. All 18 objects passed, as did the frozen
  case, discrete collision audit and original run input/output hash checks.
  The counters recorded six verified objects per class. Its complete evidence
  is in `evidence/three-arm-stream18-guarded/`; like the previous test it is
  a single short diagnostic and does not establish the 60-object gates.
  `excerpt_125s_200s.mp4` is a continuous 75-second, 2 fps excerpt of that
  real run; `excerpt-provenance.json` identifies its source and simulation-time
  interval. It is a diagnostic overview, not the requested multi-camera film.
  After moving the Franka grip settings into the run's scene layer instead of
  an external derived asset, a further 18-object run again passed all item
  checks and the discrete collision audit with intact input/output hashes.
  The selected source USD was not rewritten; cached sources can be snapshotted
  into the run before those scene-local settings are authored. Evidence:
  `evidence/three-arm-stream18-scene-grip/`. This is still one diagnostic seed.
  A separate real UR10 guard test rejected a target at z = -50 m before
  pursuit, ran all 120 requested physics steps and observed less than 1 mm
  TCP movement; its indicator reported the controller error. Evidence is in
  `evidence/workspace-guard-probe/`. This tests the guard, not complete path
  safety.
- A subsequent guarded 60-object seed-17 diagnostic ran all 48,000 requested
  physics steps and independently recorded 59 correct objects (20 Kawasaki,
  19 Franka and 20 UR10), with no wrong-bin placement. It nevertheless **failed**
  its frozen stream checker: the missed green object passed near the UR10 and
  the checker treated three reported proximity records as wrong-robot contacts.
  Each of those records had strictly positive minimum point separation, between
  4.26 and 6.87 mm; the independent discrete collision audit passed. The failed
  checker result, full run, logs and original locked code remain in
  `evidence/three-arm-stream60-v4-diagnostic/`. The revised verifier
  distinguishes completely observed positive-separation proximity from
  physical contact, while continuing to fail closed on missing separation data
  and reporting proximity separately. This is a checker correction, not a
  retroactive pass or a relaxation of the required no-contact condition.
  It now also checks actual suction-object lift when a case specifies a lift
  threshold and honors explicitly named forbidden obstacles. These changes
  require new runs with the revised frozen worker and verifier.
- A paired moving-pick test with arm drives enabled and disabled completed the
  requested physical duration, measured zero gains in the disabled run, and
  observed no correct placement in that run. The check is in
  `evidence/arm-drive-negative-control/` and covers one arm only.
- Separate paired single-object tests disabled suction and set belt speed to
  zero. Both ran for their full requested durations and checked physical state
  against their respective positive controls; see `evidence/suction-negative-control/`
  and `evidence/belt-zero-control/`. These are isolated tests, not the final
  three-arm negative-control suite.

The documented acceptance still requires the negative controls in the final
three-arm configuration, three independent 60-object seed runs, three verified resets, a separate
10-minute run with its ledger and resource samples, complete collision and
penetration coverage, and the specified fresh-agent composition tests. The
discrete collision audit has passed the earlier v10 direct-belt suite but must
also be checked on the final 6.2 feeder scene. `simscene verify-suite` fails
closed when the required evidence is missing.
Its queries check physics-step snapshots rather than continuous swept volumes.
An isolated Claude Code host loaded the plugin skill and connected its MCP
server, but its model turn could not run without a credential. Cross-machine
operation and other simulator versions must be established separately.

The frozen 6.0.1 v10 stream has now completed seed 17, 29 and 43 at 59/60
correct placements each, with no wrong-bin placements and passing discrete
overlap audits and input/output locks. Seed 17 and 43 have directly observed
zero process exits; the seed 29 supervisor was deliberately reattached and its
legacy worker did not persist the exit code, so that zero is marked as
inferred. See `evidence/three-arm-v10-seed17/`,
`evidence/three-arm-v10-seed29/` and `evidence/three-arm-v10-seed43/`.
The separate seed-53 run also completed 48,000 steps (800 seconds of simulated
time), with 59/60 correct and a passing audit and resource record. The frozen
v10 suite checker passes; its report is in `evidence/three-arm-v10-suite/` and
the long run is in `evidence/three-arm-v10-long-seed53/`. The seed-29 process
exit remains inferred as described above. Final controls and fresh-agent tests
are still required; these records use the earlier v10 worker and the
direct-belt scene, not the current 6.2 online-asset and feeder scene.

On the locally supplied Isaac Sim `6.2.0-rc.14`, a separate 24,000-step
three-arm probe completed with 18 of 18 workpieces placed in their expected
bins, a passing pinned case and discrete overlap audit, and verified input and
output locks. The actual process exit was observed as zero. Its robot USDs
were from the local 6.0 asset pack; the controller profiles were generated
against the 6.2 installation. The full run and verifier are retained in
`evidence/isaac-6.2-three-arm-18/`. This is a compatibility probe, not the
60-object multi-seed acceptance. A separate run acquired and profiled the
three selected 6.2 robot assets from the hosted USD Search service, then
completed 24,000 steps with 18/18 correct placements, a passing frozen case
and discrete overlap audit, verified input/output locks and an observed zero
process exit. Its actual asset snapshots and run are in
`evidence/isaac-6.2-online-three-arm-18/`. It used the earlier v13 worker and
direct-belt setup; it does not establish the final feeder-equipped multi-seed
case or prove that a fresh agent performed the whole task autonomously.
The evidence copy retains absolute paths from the original run. Its files are
available for inspection, but the current lock verifier and stage references
expect those original simulation-host paths; simply moving the copy does not
make it a self-contained replay package.
In a separate live USD Search check, an acquired 6.2 Franka package was
evicted and reacquired from the selected source; its archive hash changed,
while the locked asset-and-dependency content fingerprint remained identical.
The result is in `evidence/usd-search-cache-eviction-recovery/`. Unit tests
also cover saved-scene snapshotting, direct export and a pinned Hugging Face
revision after eviction. A follow-up live check used the original now-missing
path in a saved scene, restored the cached content, snapshotted it and exported
USD without changing the saved scene. A subsequent independent 6.2 run restored that selected package into a locked snapshot and executed all 120 requested physics steps with an observed zero exit, a rendered image, and verified input/output hashes. The original saved scene remained unchanged and its evicted path remained absent; see `evidence/isaac-6.2-evicted-scene-restoration/`.

A feeder alignment diagnostic stopped after 12,074 of 15,000 requested
steps because the first UR10 wait timed out. It did not pass; its original
resumed supervisor labeled the zero-exit process `completed`, even though
the pinned checker rejected the incomplete duration. The full failed run is
in `evidence/feeder-offset-timeout-v10/`. New job-status code treats an
incomplete result as failed while preserving the recorded controller error.
A later feeder experiment increases the wait to allow the added physical chute
travel; that is a new run, not a retroactive change to this evidence.
That new 15,000-step diagnostic completed with an observed zero exit; at the
cutoff 25 of the 60 scheduled objects had spawned and 14 had been verified in
the correct bins (7 red, 5 green and 2 blue), with no wrong-bin placement.
The full 60-object case and collision audit both fail at this partial cutoff,
including coverage for not-yet-spawned shapes and unfinished grasps. The
record is `evidence/feeder-offset-wait-v16/`; it is used only to select a
follow-up, fully checked presentation, not as an acceptance pass.
The subsequent 6.2 online-asset presentation completed all 24,000 steps but
failed the frozen 18-object case: 13/18 were placed correctly (6 red, 6 green,
1 blue), with zero wrong-bin placements; its discrete collision audit passed.
The second blue item crossed the pickup window before the UR10 began its next
wait and fell into the recovery tray. The actual run, four videos and timing
analysis are retained in `evidence/isaac-6.2-online-feeder-presentation/`.
A follow-up increases spawn spacing from 600 to 900 physics steps before
freezing a new run; it retains the same success and collision thresholds.
During that run the second blue piece again passed the UR10 while it was
finishing the first cycle and reached the end tray. The controller timed out
and the job correctly reported failure after 30,174 of 36,000 requested steps;
13/18 items had been placed correctly. The pinned-case post-run audit and
record are in `evidence/isaac-6.2-online-feeder-retimed/`; the earlier live
observation is in `evidence/isaac-6.2-retime-live-diagnostic/`. A separate
green-first class ordering, retaining 900-step spacing and the same success
thresholds, also missed the second blue pickup. At step 13,830 the UR10 was
waiting for that piece after it had passed the entire configured workspace;
the experiment was deliberately cancelled early and cannot be counted as a
completed-case or collision-audit result. Its preserved observation and
early-stop rationale are in `evidence/isaac-6.2-online-feeder-greenfirst/`.
A nominal geometry check found that the green bin wall overlaps the passing
workpiece path by 6 mm; this is a plausible cause, not proven contact. A new
trial moved the entire bin 70 mm, with its physical drop waypoints and frozen
case bounds translated consistently; see `evidence/feeder-bin-clearance-diagnostic/`.
That run failed at step 5,761: the Franka transfer waypoint timed out with a
2.33 cm position error. Its partial physical result is in
`evidence/isaac-6.2-online-feeder-bin-clearance/`. A separate 30 mm
translation completed all 36,000 steps and placed all 18 items correctly; its
discrete collision audit passed. It nevertheless failed the frozen case because
the three robots never had the required 60 steps of simultaneous active
cycles. The complete failed case is in
`evidence/isaac-6.2-online-feeder-bin-clearance-small/`. A new trial changes
the class order and spawn spacing while retaining the same success, concurrency
and collision thresholds. This 6.2 online-asset run completed all 36,000
steps with an observed zero exit, placed all 18 objects correctly, had 267
steps of simultaneous three-arm activity and passed the pinned case, discrete
collision audit and input/output integrity checks. The GPU-queue launcher
start and exit markers span approximately 1,702 wall-clock seconds, including
startup and shutdown, for 600 simulated seconds (about 0.35× real time). The
video and full record are in `evidence/isaac-6.2-online-feeder-concurrent/`. A three-camera-cycle
highlight cut from those recordings, together with source hashes and cut times,
is in `evidence/isaac-6.2-feeder-highlight-v2/` (approximately 65 seconds). This
one run does not replace
the separate 60-object multi-seed, negative-control or fresh-agent acceptance.

The first 60-object 6.2 trial using that arrangement stopped after 31,467 of
54,000 requested steps. Franka timed out during the fourteenth lift even
though its final TCP position error was 6.2 mm against a 10 mm tolerance;
sampled arm joint speeds frequently exceeded its 1.3 rad/s completion guard,
so it did not achieve 15 consecutive settled steps. The failed partial run and
its speed diagnostic are in
`evidence/isaac-6.2-online-feeder-concurrent-formal-suite/`. A new trial
retains the position tolerance and measured speed guard but requires five
consecutive settled steps for Franka lift moves. This is a controller tuning
change, not a change to the frozen case thresholds. With that tuning, a new
18-object run completed all 36,000 steps, placed all 18 objects correctly and
passed the fixed physical case, collision audit and integrity checks; see
`evidence/isaac-6.2-online-feeder-lift-settle/`. The separate 60-object runs with seeds 17, 29 and 43 each completed all 54,000
steps, placed all 60 objects correctly and passed their frozen physical cases
and discrete collision audits. For seed 17, 900 simulated seconds spanned
approximately 1,996 wall-clock seconds from launcher start to exit, including
startup and shutdown (about 0.45× real time). The records are in
`evidence/isaac-6.2-online-feeder-lift-settle-formal-suite/`. The separate
seed-53 long run also completed 900 simulated seconds and placed all 60
objects correctly; the combined frozen four-run physical suite, reset,
resource, collision and integrity checks passed. The paired drive-disabled,
suction-disabled and stopped-belt controls also passed. Fresh-agent checks
remain separate.
Separately, the same physical end-tray geometry was tested with a missed cube:
it contacted the belt, crossed its end, contacted the tray at step 322 and
settled inside. The pinned case, rendered video, measured state and verified
hashes are in `evidence/isaac-6.2-recovery-tray-probe/`. This one-object test
does not by itself prove the complete sorting scene.

New runs snapshot and hash the shared SimScene worker package before launch;
the formal suite requires this snapshot. Earlier evidence predates that change
and must not be represented as proof that its worker source was frozen.
An opt-in self-collision setting was also exercised for 120 steps with all
three articulations: Isaac reported it enabled for each, and the new source
snapshot and output hashes verified. That short test does not establish full
contact reporting, penetration coverage or successful sorting with the setting.
The same three-arm setup also ran a 120-step overlap-query diagnostic: all 45
robot shapes reported their own collider, 121 sample instants were queried
without gaps or query errors, and raw overlap pairs were saved. Convex-hull
query hits include intentional connected parts, and this still does not measure
penetration depths or prove collision-free continuous motion.
The extended monitor queried 63 active or spawned scene shapes in a separate
120-step positive control. An intentionally overlapping static box was
reported against the Franka base; self-query coverage, input locks and output
locks passed. This tests a known overlap, not every geometry type or crossing.
The independent discrete checker treats reported contacts with strictly positive
point separation as proximity records, and fails on unapproved zero/negative
separation or shape overlaps. It requires every expected collision shape and
every simulation step to be accounted for; missing geometry or contact data
fails the check. Initialization contacts before the reset run are excluded from
the run timeline in newly created workers.
The fixed three-arm collision policy lists six Kawasaki wrist/gripper linkage
pairs whose authored collision shapes interfered with the mechanism. It also
permits the Franka fingers to meet, while keeping their self collision enabled.
Directly joint-connected bodies with joint collision disabled are treated as
mechanical pairs. These explicit exceptions do not validate those geometries
as safe; the audit covers only the remaining modelled pairs at sampled steps.

`experiments/prepare_three_arm_profiles.py` prepares the three experimental
controller directories from individually selected local USD files, without
requiring a complete Isaac asset library. Its output contains the environment
variables accepted by `experiments/run_three_arm_stream60.py`; the Isaac runtime
itself and its controller configuration files remain necessary. Build-only
mode validates the proposed 60-object scene and case but does not run physics.

The NVIDIA 6.2 base Python Kit server also passed a local loopback health and live stage-edit probe in `evidence/isaac-6.2-remote-base-python-server/`. This is a developer IPC check on the simulation host, not a cross-machine test or a replacement for the plugin’s SSH transport. The second reattachment smoke run, including an observed process exit and image, is in `evidence/isaac-6.2-exit-recovery-v2/`.

The editable `three_arm_online_example` has also been installed on this host.
Its three selected online asset contents and regenerated controller files match
the verified 18-item source run, and its schema and USD export were checked.
A separate 120-step Isaac load-and-render smoke completed with observed exit 0
and both locks verified; it does not establish that the relocated copy has
passed the complete sorting case. See `evidence/local-example-install/`.

A fresh v26 online-agent session inspected and acquired a selected NVIDIA
conveyor, ran it, observed the result and verified run locks, but its
pre-registered evaluator reported failure: it compared the original cache path
with the run's copied asset-snapshot path. The original failure is retained.
A revised checker matches the selected source and package hash to the locked
snapshot; a post-hoc diagnostic passed all substantive checks but correctly
failed the frozen-checker check. This diagnosis is not an acceptance pass; a
new session with the revised checker frozen in advance is required. See
`evidence/agent-online-snapshot-checker-diagnostic/`.

During the fresh v26 three-arm agent session, a long simulation-start call and
concurrent job-status calls timed out while asset acquisition was underway. The
obsolete session was then deliberately terminated after the defect was
reproduced, and is retained as an interrupted failure; its uncompleted edits
are not acceptance passes.
The MCP SDK was executing synchronous tool functions on its event loop. A
local controlled reproduction showed that a blocked search also prevented an
unrelated scene read in v26. The v27 MCP entry point dispatches synchronous tool
work to threads; the same real stdio MCP test now lets the scene read finish
while the search remains blocked. The before/after logs and CPU regression
results are in `evidence/mcp-concurrency-repair/`. A second controlled test
holds the asset-cache lock during simulation preparation and confirms that
`job_status` remains responsive. An installed v28 MCP launcher also completed
a real 120-step Isaac 6.2 load-and-render smoke with verified locks and an
observed exit code (`evidence/local-install-v28/`). The four-run physical suite
above used the earlier v25/v26 Python implementation; the v28 transport change
is being checked again in a fresh suite and agent sessions.

In the v28 retest, the first two 60-object physical runs passed, but the
subsequent drive-disabled control failed at step 30 when Isaac returned no RGB
frame even after the previous 120 render-update retries. The partial v28 suite
was deliberately stopped and preserved in `evidence/isaac-6.2-v28-formal-suite/`.
The v29 worker allows up to 600 paused render updates before failing, without
skipping or inventing frames. A controlled delayed-frame test passes; this is
a bounded robustness change, not proof of the cause or a guarantee that every
renderer startup will succeed. The installed v29 MCP launcher completed a
separate 120-step Isaac load-and-render smoke with observed exit 0 and verified
locks (`evidence/local-install-v29/`). A fresh v29 suite then completed three
60-object seed runs and a separate 900-second simulated run, each with 60/60
correct; its frozen physical, resource, collision and integrity checks passed.
The three paired negative controls also passed. Records are in
`evidence/isaac-6.2-v29-formal-suite/`; fresh-agent checks remain separate.

Two fresh v29 agent cases have since passed their independently frozen checks:
the workbench case composed and ran a new two-row workbench with an orbiting
camera, and the online case searched the public service, inspected and
acquired a selected conveyor, loaded it into Isaac Sim, and observed the run.
Both verified their frozen skill and worker hashes and run integrity. The
online checker also tied the selected source and package to the run snapshot
and confirmed that the selected USD composed actual child prims. The complete
session evidence is in `evidence/agent-v29-independent-cases/`. These two
cases do not establish the outcome of the separate three-arm and scene-edit
agent cases, which are still being evaluated.

The fresh v29 three-arm session later built its own online-asset scene and
physically sorted 9/9 items with intact run evidence and the other frozen
checks passing. Its independent acceptance nevertheless failed: the three
observed pick cycles did not overlap for the required 60 physics steps. The
agent's own physical case did not require that overlap, so its 9/9 report was
not sufficient for the frozen criterion. The original session and failed
checker are preserved under `evidence/isaac-6.2-v29-formal-suite/agent-acceptance/three_arm/`.
The three scene-edit sessions were consequently skipped, not passed. A timing
planner and skill guidance have been added for a fresh evaluation; the
planner's proposal requires a new physical run and does not establish success.
The first retiming probe produced simultaneous motion but encountered a
Panda transfer timeout while already within the positional tolerance; it was
deliberately stopped and recorded in `evidence/agent-v30-suite/`. The second
probe adjusted the affected controller's consecutive settling interval while
retaining the joint-speed threshold. It sorted 9/9 items with 768 consecutive
overlapping physics steps, but its physical case still failed: the contact
report included a finger near the green-bin wall, with a measured minimum
positive separation of about 10.5 mm. The discrete overlap audit passed; the
stricter case treats that proximity record as a failure. Its result is in
`evidence/agent-v30b-suite/`. A further probe expanded the wrong wall: the
minus sign in the object ID becomes an extra underscore in the USD path. It
also failed the same strict check, and is retained in
`evidence/agent-v30c-suite/`. The next probe restores the original bin and
raises the Panda retraction waypoint before it returns across the near wall.
The IK solver found a position candidate. A short physical probe observed the
first three correct picks, overlap and no forbidden environment record, but its
full collision audit correctly reported incomplete shape coverage because later
objects had not yet spawned. The original short-check failure and a separate
post-hoc diagnostic are in `evidence/agent-v30d-short/`; neither substitutes
for the new full-length run and its unmodified audit. That subsequent 18,000
step run completed with 9/9 correct, no wrong bins, 768 consecutive overlapping
steps, an unmodified collision audit and both integrity checks passing. Its
frozen case and run are being archived in `evidence/agent-v30d-suite/`. These
probes modify a previous agent scene and are not themselves fresh-agent
acceptance; the fresh v30 sessions are running separately.

The v30 workbench and online-discovery sessions have passed their independently
frozen cases with the v30 package and skill frozen before each prompt; their
traces and checks are in `evidence/agent-v30d-suite/workbench/` and
`evidence/agent-v30d-suite/online/`. The remaining fresh v30 cases are still
running or pending and should not be inferred from these two results.

The v30 three-arm session was interrupted by the model service reporting
capacity exhaustion. It had not completed; the original trace and failed
verification are retained. The checker happened to select a completed
single-Panda diagnostic and incorrectly labelled its one-arm interval as
`simultaneous_robot_cycles`, although the independent distinct-robot and
per-class checks failed, so the overall result was not a pass. The checker has
been tightened to require all three distinct class owners before reporting
parallel cycles. A new session must freeze the revised checker before its
prompt; the interrupted session is not retroactively counted as an acceptance.
The model service subsequently answered a separate availability probe. A new
v30 three-arm session passed the revised independently frozen checker: it
discovered and acquired the three robots online, built its own scene from an
empty start, observed 9/9 correct items, and recorded 473 consecutive physics
steps with all three pick cycles overlapping. The physical case, discrete
collision audit, input/output locks, chute, recovery geometry, cameras and
verified counts also passed. Its trace, frozen checker and result are in
`evidence/agent-v30e-suite/three_arm/`. The already passed workbench and online
cases were carried forward only after their recorded package hashes matched
the current package. The three dependent scene-edit sessions are still being
evaluated; the three-arm result does not imply those edits have passed.

The first v30 retime session correctly changed belt speed from 0.08 to
0.06 m/s and item spacing from 1,000 to 1,500 steps; the checker measured the
changed belt motion. It did not pass acceptance: the run stopped at 14,196 of
18,000 requested steps after the Panda's final placement timed out, with 8/9
objects verified. The agent disclosed that failure. The preserved independent
result is `evidence/agent-v30e-suite/retime/verification.json`; the other edit
sessions are separate and their results are not implied by it.

The separate v30 route-swap session subsequently passed its frozen checker:
the two class routes were exchanged and the actual simulation sorted 9/9
items. The scene diff, trace and checks are in
`evidence/agent-v30e-suite/swap/`. The relocation case remains in progress.

The relocation session moved the red bin across the arm and physically placed
all three red pieces there, but its frozen checker did not pass: only one of
three green pieces passed the original case's forbidden-environment contact
check. A second checker flag incorrectly failed to identify the reviewed robot
models because run snapshots flatten their source paths. The checker now binds
each official source URL to the exact locked run snapshot. A post-hoc
diagnostic confirms that correction while still reporting the physical case
failure and an unfrozen checker; the original failed result is unchanged.
See `evidence/agent-v30e-suite/relocate/` and
`evidence/route-edit-snapshot-checker-diagnostic/`. A new session must freeze
the revised checker before its prompt.

Separate fresh repair evaluations were started from the accepted v30
agent scene. The original retime checker and its failure remain unchanged.
The new retime-repair case permits a move waypoint to shift by at most 5 cm
or a move timeout to increase by at most a factor of two, while holding the
task, geometry, item order, requested speed and spawn intervals fixed. It
adds requirements that all items pass the pinned physical case, remain inside
the original frozen bin bounds, overlap for at least the original duration,
and pass the full discrete collision audit. This is a separately frozen,
different repair criterion rather than a retroactive pass of the original
strict unchanged-controller case. The relocation repair uses the same
physical and collision requirements as before, with the snapshot identity
checker corrected before its new prompt.

The fresh retime-repair session has passed that separately frozen case. After
observing the initial failures, the agent moved six Panda waypoints by 4.5 cm,
kept the requested timing changes, and reran the simulation. All 9 items passed
the physical case and original bin bounds, the measured belt motion and
overlapping cycles were verified, and the full discrete collision audit and
input/output locks passed. The prompt, original failed trial, edit diff,
frozen criteria and result are in `evidence/agent-v30-edit-repairs/retime_repair/`.
The fresh relocation-repair session also passed its revised, pre-frozen
checker: the red bin moved across the robot, all 9 objects passed the physical
case, and the reviewed collision policy and full discrete audit passed.
Its prompt, diff, observations and result are in
`evidence/agent-v30-edit-repairs/relocate_repair/`.

The packaged agent-generated project was then copied to a different directory
and run through its own `run_project.py`. The relocated replay completed all
11,000 requested steps with 9/9 correct, no wrong bins, 473 overlapping steps,
a passing discrete collision audit and passing input/output integrity checks.
This checks the copied project's actual replay; it is distinct from the prior
fresh-agent test and the multi-seed formal suite. The run and logs are in
`evidence/agent-v30-delivery-replay/`.
