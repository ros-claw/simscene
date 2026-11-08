# Independent pilot design v1 — private handoff

This directory is examiner material. It is not a skill, build recipe, or a task result.
Do not mount the whole directory into a builder session.

Two independent tasks were prepared without participating in candidate skill/tool authoring:

- P1: gravity load acting through one passive lever, supporting a separate payload.
- P2: gravity-driven rolling contact transferring motion to an unjointed free slider, followed by frictional stopping.

Both use a few primitives, no online assets, one low-resolution stationary camera, a short native simulation and a local causal intervention that must preserve real upstream motion. They assess distinct local physical work; neither renames the previous sugar chain. P1 is a load/support task rather than a long relay. Neither task was chosen to require the B domino/door modules. Treat B as the entire new package.

Operator release only `public/P1/prompt.md` + `public/P1/public-case.json` to the P1 builder; do the analogous release for P2. Copy the same bytes into both arms' fresh workspaces. Release order is P1 A→B, P2 B→A, all Isaac jobs serial. Do not share examiner sources, test fixtures, this README, or another arm's evidence with builders.

- `public/P1/`, `public/P2/`: identical A/B prompts and public target contracts, no solution coordinates.
- `examiner/ACCEPTANCE.md`: exact evidence/quality review procedure and protocol limits.
- `examiner/score.py`: independent read-only scorer; stdout report only.
- `examiner/freeze_runtime_identity.py`: create-once identity lock from an unrelated generic smoke run and the already-frozen whole candidate package manifest.
- `examiner/test_score_cpu.py`: synthetic numerical tests of scorer decisions; not physics evidence.
- `smoke-source/generic_smoke_ops.py`: unrelated environment-probe ops source; never starts Isaac.
- `CPU-CHECKS.json`: CPU self-check results and explicit non-execution statement.
- `DESIGN-FREEZE.json`: design/source hashes. Publish or retain its SHA before formal prompt release. Do not regenerate after observing task outcomes.

A/B model version, reasoning level, underlying v43/worker/runtime, cache starting point, tools, starting budget, prompt bytes and allowed concurrency must be frozen by the operator before trials. The immutable scorer requires an independent runtime identity prepared from generic smoke evidence. No formal trial has been run in this design task. All overall pass labels and efficiency claims still require external visual/protocol/usage review specified in ACCEPTANCE.md.
