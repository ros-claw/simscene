# Catalog benchmark

This is a bounded six-task model study, not a promise of token savings. Read the
[measured results and limitations](../../docs/validation/catalog-efficiency.md)
before interpreting ratios. The source driver never starts an unattended
schedule loop.

## Inputs

- `tasks.json` and `protocol.json`: task definitions and default collection rules.
- `frozen-inputs/`: the exact declarative JSON subset from the measured cohort,
  with SHA256 manifest. Model files and warm-cache payloads are excluded.
- `results/`: redacted original counters, separate scope reassessment and SDK
  capture-fix validation. Raw sessions and host bindings are not distributed.

The recorded comparison used V2 commit `599a90edb6197fa5ec19f6022907416f276effd7`
and evaluator commit `c1e0c65241e0cbd53b1ef1435ac9ef71ff17c8cb`. Later evaluator
fixes must be frozen as a new cohort; do not use them to overwrite original
results. Baseline v44 is identified by the release comparison artifact and its
file inventory, not by a Git commit available in the public repository.

Stage permitted selected source files and their necessary dependencies under
each task's declared `assets/` paths. For warm tasks, create the same cache seed
for both versions and retain its inventory. The source locks specify revisions,
geometry hashes, closure files and URLs. `${TASK_ROOT}` and `${CACHE_ROOT}` are
the supported relocation tokens. Follow the
[gravity-cell acquisition route](../catalog_gravity_cell/README.md) where
applicable, check asset rights, and do not redistribute the model payloads as
Apache-licensed project code.

Provide external bindings for all six tasks, actual SDK identity, configured
optional backends, installed package paths, host verifier and tool allowlist.
Freeze the complete rebuilt input bundle; this public subset is not the full
historical bundle and does not by itself recreate historical custody. Never
copy client credentials into the bindings or an artifact.

## Run one explicit trial

```sh
python experiments/eval_catalog_efficiency.py freeze \
  --protocol /outside/protocol.json --bindings /outside/bindings.json \
  --baseline-package /outside/baseline --candidate-package /outside/candidate \
  --candidate-commit FULL_40_HEX_SHA --output /outside/pilot-plan.json
python experiments/eval_catalog_efficiency.py preflight --plan /outside/pilot-plan.json
python experiments/eval_catalog_efficiency.py run-trial \
  --plan /outside/pilot-plan.json --plan-sha256 EXACT_PLAN_SHA256 \
  --trial-id native-layout-1-baseline --output /outside/trial-001
```

Inspect each result before starting the next scheduled ID. Preserve failures,
unknown usage and interventions. Aggregate all four pilot results, review its
actual SHA256, and pass `--full --pilot-report PATH
--reviewed-pilot-sha256 SHA` with the same comparison inputs before expanding.
The collector rejects input drift and duplicate output destinations. Model
login and capability metadata are copied privately into isolated client state;
global instructions, plugins, skills and conversation history are not reused.
Only the two installed SimScene skills are made available. This is a scoped
client/trace policy, not an operating-system read jail.

New model or SDK studies use new plans and directories. Report quality and all
failure costs before comparing the strictly passing Group A pairs. Group B
capability gaps do not define token savings.
