# Supplementary checker v2 — post-hoc / exploratory

This separately versioned checker was prepared **after all four allocated builders ended**, on explicit instruction to repair two evaluator interfaces. It never replaces the original frozen outcomes. No native physics or builder/model request is rerun. All original task files, thresholds, checker, failed attempts and sealed native runs remain unchanged.

The fixes are limited to:

1. Effective compiled collisions: dynamic primitives in v43 already acquire colliders without an explicit `collision:true` source key. v2 retains the explicit positive mass rule and reads enabled ColliderAPI / dynamic RigidBodyAPI schemas. Initial bodies are read from the original sealed USD. A scheduled body's USD does not exist in that initial file; v2 therefore uses a temporary CPU-only initial-equivalent compilation of its unchanged source, using exporter/spawn dependency bytes pinned to the native worker. It records that witness as compiler policy rather than native spawn-stage readback. All original native contact, strict initial-state, clock and passive-motion checks still apply. A missing/disabled collider, disabled rigid body, kinematic body or unpinned compiler fails.
2. Empty joints: where the exact frozen source/case joint inventories are empty, an omitted per-step `joints` key is treated as `{}`. Explicit `None`, an unexpected joint entry, missing required strict t0 data, or any nonempty source joint inventory gets no exemption.

The legacy JSON check key `all_dynamics_explicit_mass_collision` is retained for compatibility; in v2 it means explicit positive mass plus effective compiled collisions, with witnesses under `compiled_dynamic_collisions`.

All original numeric motion/contact/stability functions and isolated-intervention comparator remain AST-identical. Both original public contracts retain their exact hashes. `CHANGE-RECORD.json` and `original-to-supplementary.diff` expose the complete change.

Use an unchanged original design directory and the same evidence/runtime identity:

```bash
PYTHONPATH=/absolute/pinned-v43/src python3 score_v2.py --design-root /absolute/original-design --task P1 --positive /absolute/sealed/positive --negative /absolute/sealed/negative --identity /absolute/approved-runtime.json > /absolute/reports/supplementary-v2.json
```

P2 uses the same interface with `--task P2`; omit `--negative` only for a single-positive diagnostic. Output includes `supplementary_posthoc=true` and `replaces_frozen_outcome=false`. There is no overall task-passed field. Over-budget, missing-submission or assisted arms remain protocol failures even if a post-hoc physical suite passes.

CPU regression tests use actual v43 USD export/readback and no Isaac process:

```bash
PILOT_ORIGINAL_DESIGN=/absolute/original-design PYTHONPATH=/absolute/pinned-v43/src python3 test_interfaces_cpu.py
```

The 15 tests cover implicit dynamic box/compound collisions, actual exporter behavior for explicit false, scheduled-body compilation without altering the original stage/spec, missing/disabled colliders, disabled/kinematic bodies, compiler identity mismatch, empty/malformed joint maps, unchanged numeric/causal functions, and original design/contract hashes.

The original frozen checker's 15 CPU tests remain separate. Their synthetic fixture tests did not exercise compiled USD collision defaults or the native no-joint encoding, which explains how these interface defects escaped initial preparation.

The v2 suite results are the **same records selected in the original audit**. The P1 selection is the ordered repair followed by the unique locked control, not a retrospective best-of-many selection. Two P1 engineering pairs pass v2; both P2 repairs still fail measured motion/terminal criteria. Neither P1 pair is an on-budget complete submission. Overall allocated-trial acceptance remains 0/4 and no savings rate is justified.
