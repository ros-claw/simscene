# Catalog efficiency: frozen protocol and bounded collection

An initial collection pilot stopped after one timeout with missing usage and
unwanted global client context. No valid comparison is available. Token
reduction, quality equivalence, time improvement and billing savings are **unknown**. The
30% token reduction mentioned in the design is an optimization target, not an
observed result. Historical development hours cannot establish token savings.

The checked-in [protocol](../../examples/catalog_benchmark/protocol.json) and
[six tasks](../../examples/catalog_benchmark/tasks.json) define the experiment
before its pilot. The baseline is
`a36d2b272cd7d64b739a9d3ebc4d9a761323aafd` (v44). The candidate commit is
intentionally unset until the implementation is frozen. Actual model selection
comes from the explicitly frozen protocol or `freeze --model`; the initial
configured model is `gpt-6.1-sol`, reasoning effort `medium`, for both versions.
The driver never substitutes a different model.

## Collection validity

The first legacy native-layout pilot completed a physical worker but did not
write its required submission before the 240-second ceiling. It made 744 tool
calls, including 722 individual observation requests, and discovered a global
skill path outside the allowed task scope. The original timeout, scope failures
and absent usage remain unchanged; they are not a baseline capability failure
or a measured token count. That incomplete cohort stopped without expanding.

The revised collector uses fresh per-trial client state, privately copies only
available file-based login and model-capability metadata, and disables bundled
skills. Parent configuration, global instructions, plugins and history are not
copied. A live client probe exposed exactly the two installed SimScene skills.
This follows the documented [client state locations](https://learn.chatgpt.com/docs/config-file/config-advanced#config-and-state-locations)
and [skill controls](https://learn.chatgpt.com/docs/build-skills#enable-or-disable-local-codex-skills).
Credential contents and hashes are never written to evaluation receipts.

Both versions receive the same clarification: inspect a few representative
observations, submit the run/evidence locators promptly, and let the trusted host
check every saved physics step. Physical predicates, time/token ceilings and
source locks are unchanged. The evaluator/prompt change requires a new frozen
cohort; its results cannot be pooled with the failed original collection probe
or attributed as a plugin-only improvement.

A subsequent collection attempt obtained a passing common-task pair, but its
GLB trial could not fetch metadata because the MCP child lacked the host's proxy
environment. The host could read the same pinned metadata; allowing proxy
variable names into the child produced a successful live 8,317,292-byte metadata
query with zero model bytes. The revised command inherits variable names only,
following [MCP environment forwarding](https://learn.chatgpt.com/docs/extend/mcp?surface=cli#stdio-servers);
proxy values never appear in the recorded command. This network change requires
another cohort, with earlier successes, failures and usage retained separately.

The exact SimScene catalog resource read is allowed as a standard MCP operation;
it is not an additional asset tool. Global resource/template discovery and other
servers remain outside scope. The earlier GLB attempt also made those disallowed
global calls and produced no physical run; its failure is not relabelled.

## Comparisons and gates

Group A compares native USD layout, a warm 20 mm edit, and native video. Their
prompts and host predicates must work with the legacy tools; no new-tool call is
a passing criterion. Group B measures GLB rigid preparation, native articulated
preparation, and generated modules. A host-verified unsupported capability is a
`capability_gap`, never a zero-token success or 100% savings. A model saying that
something is unsupported is insufficient. The verifier must establish actual
support against the frozen installed package. Group B has no efficiency ratio.

First collect **two pilot pairs**, native-layout and glb-rigid, four isolated
sessions total. Each has a 240-second Codex wall limit, 1,000,000 reported
input+output tokens, and a separate 12,000 output-token limit. The full initial
budget is six tasks × three repetitions × two versions = 36 sessions, each with
420 seconds, 2,000,000 input+output tokens, and 16,000 output tokens. There are no
automatic retries. The model-process ceilings sum to 960 pilot seconds or 15,120
full seconds. Host verification is separately bounded to 120 seconds per trial
(480 pilot / 4,320 full seconds); setup/copy time is separately recorded.

Token counters include cached input. Cache and reasoning counters are subsets,
not extra token buckets. Uncached input is reported separately; cached tokens
are not described as free. Limits are checked on reported completed-turn usage.
A single in-flight request can exceed them, and clients may report usage only at
the end of a long turn. This is **not a hard provider billing cap**. Unknown
usage stays unknown. Invalid/conflicting usage stops an active trial; partial
known usage is retained. The driver stops at one explicit trial and never starts
an unattended 36-trial loop.

A full plan requires the exact SHA-256 of an explicitly reviewed pilot report.
The report must contain four trials with real usage and verifier evidence, and
the common-task pair must pass. Its comparison fingerprint must match the full
plan's packages, model, budgets, input bundles and host verifier. If collection
is invalid or common tasks fail consistently, stop, fix the observed problem and
freeze again. Preserve the earlier plan, trace and all failure costs. A revised
protocol starts a distinct cohort.

## Host bindings required before execution

`experiments/eval_catalog_efficiency.py` exposes `freeze`, `preflight`,
`run-trial`, and `aggregate`. Import, freeze and preflight launch no model or
simulator. `freeze` refuses missing hardware/runtime identity, a non-full
candidate SHA, missing input predicates, missing warm seed files, or missing
installed packages. It hashes the evaluator, reused M1 harness, package files,
skills, task inputs, and host verifier. `run-trial` rechecks these hashes before
and after execution and preserves consumed cost if post-run inputs drift.

The host supplies a JSON binding bundle outside Git:

```json
{
  "verifier": "/outside-checkout/host_verify.py",
  "tasks": {
    "native-layout": {
      "inputs": "/outside-checkout/frozen-inputs/native-layout",
      "acceptance_file": "acceptance.json"
    }
  },
  "server_environment": {
    "SIMSCENE_ISAAC_PYTHON": "/observed-runtime/python.sh"
  },
  "v2_config": {},
  "tool_allowlist": ["asset_search", "asset_acquire", "scene_apply"]
}
```

Supply entries for **all six tasks**, the actual complete allowlist shared by
both versions, immutable source locks/URLs, ordinary scene recipes, fixed source
geometry, joint topology and generated-module parameters, and exact acceptance
predicates. The example allowlist above is illustrative, not runnable. Group A
must use the same provenance, actor set, contact/bounds/settling checks and video
frame/visibility/motion thresholds on both versions. Group B requires equivalent
physical checks whenever both versions support the capability. The host verifier
is trusted evaluator code frozen before the model session; it is never an agent
submission. Predicate changes cannot be smuggled into a later trial.

For warm tasks put the identical common-native cache seed under `cache/` in each
input bundle. Optional `prepared/` and `index/` seeds are copied as well. Each
trial gets a private copy. A mutable cache produced by the other version is not
a paired seed. Model prompt caching is measured separately from source/prepared
caching. Assets, metadata access, byte limits, licenses, runtime, source network
policy, and accessible task directories must be equivalent. Freeze any required
path substitutions in the bundle/host verifier; do not give one version a hidden
asset or a prepared solution. Runtime setup observations may be shared read-only;
first installation, metadata indexing and source acquisition remain separately
reported costs.

The host verifier receives:

```text
python host_verify.py --task TASK --work WORK --state STATE \
  --package INSTALLED_PACKAGE --acceptance FROZEN_ACCEPTANCE_FILE
```

Its stdout must be one JSON object. A pass requires `passed`,
`provenance_verified`, and `quality_verified` all `true`. It must independently
inspect saved source hashes, immutable run inputs and actual physical/video
evidence using the installed package; model prose is never a verdict. Optional
fields are `actual_download_bytes` (all attempted transfers, including failures),
`video_passed`, `manual_interventions`, and `phase_intervals` with host monotonic
`phase`, `start_s`, `end_s`. A capability gap requires both `capability_gap` and
`capability_gap_verified` true. Missing measurements stay null. The root
integration must supply and review this task-specific verifier and six concrete
predicate/input bundles before launch; this driver does not invent those facts.

## Isolated packages and commands

Export the baseline without checking out or modifying the active worktree:

```sh
mkdir /outside-checkout/baseline-source
 git archive a36d2b272cd7d64b739a9d3ebc4d9a761323aafd | tar -x -C /outside-checkout/baseline-source
```

Use that revision's documented portable-package builder in the isolated export.
Build the candidate from its separately frozen export. Keep package build
receipts linking each installed package to its source commit. `freeze` hashes
installed package bytes, but cannot prove an arbitrary supplied package was
built from the asserted commit. Never mutate the shared checkout for this test.

Fill observed `hardware` values in an external copy of the protocol, then:

```sh
python experiments/eval_catalog_efficiency.py freeze \
  --protocol /outside-checkout/protocol.json \
  --bindings /outside-checkout/bindings.json \
  --baseline-package /outside-checkout/baseline-package \
  --candidate-package /outside-checkout/candidate-package \
  --candidate-commit FULL_40_HEX_SHA --output /outside-checkout/pilot-plan.json
python experiments/eval_catalog_efficiency.py preflight --plan /outside-checkout/pilot-plan.json
python experiments/eval_catalog_efficiency.py run-trial \
  --plan /outside-checkout/pilot-plan.json --plan-sha256 EXACT_PLAN_SHA256 \
  --trial-id native-layout-1-baseline --output /outside-checkout/trial-001
```

The actual run launches the reused Codex `exec --json` harness with an isolated
MCP server from the selected package, an explicit model/effort, copied installed
skills, and private state/config/cache/index/prepared directories. No new tools
are required for Group A. The host invokes its frozen verifier after the model
exits, with its own timeout. The sandbox and audited trace instructions do not
prove operating-system read confinement; do not claim they do.

Run the remaining explicit pilot trial IDs from the plan in its alternating
baseline/candidate, candidate/baseline order. Aggregate preserved results:

```sh
python experiments/eval_catalog_efficiency.py aggregate \
  --plan /outside-checkout/pilot-plan.json \
  --results /outside-checkout/trial-001/trial-result.json \
  --output /outside-checkout/pilot-report.json
```

The above single-result report is incomplete until all four results are listed.
After review, `freeze --full --pilot-report PATH --reviewed-pilot-sha256 SHA`
with the same inputs creates the 36-trial schedule. Each task/version/repetition
is an independent session. Keep order/time windows close; record runtime drift,
human help and every additional attempt rather than silently replacing a row.

## Measurement and interpretation

Reports show success and video quality before efficiency. All failures, timeouts
and capability gaps retain wall time and any reported usage. Missing counters
are null; a sum of known tokens is explicitly incomplete when any trial lacks
usage. Duplicate result IDs and mismatched pair/cache/phase/version identities
are rejected. Actual completed-turn usage is deduplicated by turn/event ID.
Conflicting duplicates or indistinguishable anonymous duplicate usage produce
an unknown aggregate rather than an invented total. Failed turns without usage
retain known subtotals and mark coverage partial.

Tool calls are deduplicated by actual call ID with their final result/status;
failed calls are counted. Tool-return bytes are the UTF-8 serialization of those
actual trace result objects, not a transport-byte claim. Source download bytes
come only from the host verifier's complete ledger. Monetary billing stays null.
Phase intervals are unioned per phase to avoid counting overlapping waits twice;
absent simulation/render/model-wait measurements remain unknown. Strict replay
is a separate no-model host phase with frozen input/run locks, not pooled with
creation or warm editing. No subtraction of simulation duration from wall time
is presented as measured model inference time.

Only clean, pass/pass, same-task Group A pairs receive token/time ratios. Raw
per-trial results and pair statuses remain in the aggregate, including excluded
and incomplete pairs. Report their small-sample distributions and failure costs;
do not generalize three repetitions to all assets, models, hardware or users.
No report currently establishes 30% savings or any other efficiency improvement.
