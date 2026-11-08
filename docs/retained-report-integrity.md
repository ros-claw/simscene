# Retained original examination integrity, version 1

`experiments/retained_report_integrity.py` is a delivery-time memoization reader.
It accepts only a **complete, already accepted original independent f7 report**
under its pre-existing independent receipt. It returns that entire original
report unchanged, plus a new byte-closure proof. It does not accept a failed,
reduced, unevaluated or differently versioned report, evaluate physics, parse
`result.json`, change any observation or claim that suite7 was rerun.

Its generic freeze precedes its first application. That freeze can follow a
physical job, and is explicitly not the original pre-job physical authority.
The original frozen f7, stock kernel, cases, static reviews, clock4, software and
original independent examinations remain the authorities. No numerical physical,
quiet, control, terminal or timing predicate changes.

## API and trust boundary

```python
report, proof = load_retained(
    directory, contract_path, static_review_path, freeze_path,
    {"receipt_path": absolute_path, "receipt_sha256": independently_retained_sha},
    mode="positive", reference_run=None, reference_record=None,
    aggregation_started_at_utc=timestamp,
    software_freeze_path=absolute_path,
    additional_files=(),
)
```

Expected receipt hashes must come from the examiner's already retained custody
ledger, never from freshly hashing a proposed receipt merely to satisfy the API.
Receipts and complete reports must remain outside the sealed run directory.
Local timestamps and hashes provide auditable custody bookkeeping, not external
notarization or signatures. A party able to replace the trusted ledger is outside
this trust model. Ordinary exceptions reject the proposed reuse; there is no
fallback acceptance or synthetic successful report.

All metadata/report paths are absolute, resolve without symlinks, and contain
JSON objects with unique keys and finite JSON numbers. Encoded typed canonical
schema-default values in original f7 catalogs remain original data; the reader
does not reinterpret arbitrary nonfinite authored physics values.

## Revalidation

The reader checks the original receipt, complete report hash/size, run/evidence
lock hashes, run identity/mode, exact f7 version/source, original stock kernel
identities, pre-job freeze chronology and every frozen source/static dependency.
It calls the unchanged `assert_software_freeze` for all installed/source files,
requires the actual entire worker-package hash dictionary to match the frozen
installed package, and requires all thirteen original runtime manifest fields.

It calls the original `run_integrity.verify`, including launcher/runtime files,
source snapshots, complete acquired asset/package closure, selected root and MDL
dependencies. It compares this result with the original complete input-integrity
proof. It calls original `sealed_identities` and canonical metadata functions;
asset-path equivalence is available only through verified asset identities.
Untrusted in-memory path exemption is not added.

The original accepted evidence enumeration and unchanged independently anchored
result bytes establish the same output references. The reader therefore streams
**every originally locked output artifact** against that anchored evidence
manifest's exact safe flat filename, size and SHA, without reparsing the large
result JSON. It compares all artifact checks with the original accepted output
proof. This is closure of the original referenced artifacts, not a claim that
arbitrary unrelated files in the directory acquire evidence status. Missing,
modified, symlinked, unsafe or partial locked artifacts reject reuse.

The complete original report must retain native catalogs, every dynamic body's
cooked mass/COM/inertia records, full-step auxiliary evidence, journal proof,
stock checks, complete named events/handoffs/tiles/categories and positive cart,
cable, bridge and composed module evidence. Positive original masks must cover
their full original window. Original clock4 `prefixes` rechecks them without
changing flags; the raw P1 check/contact inventory and every original per-step
motion record remain present. A valid stopping control retains its original
isolated-change and downstream-quiet proof, rather than inventing positive
completion evidence. These shape checks supplement the trusted original full
decision; they do not independently certify cooked values or physics again.

The complete reference report is validated first and released before loading
the current control report. Only comparison metadata, original identities and
small custody proofs survive that boundary. One report is returned to the
caller, which must spill/release it before processing the next run. No eight-run
raw sample or report accumulation is necessary.

## Positive receipt v1

Schema: `simscene.independent_full_report_custody.v1`. Exact fields:

```text
schema recorded_at_utc role run_directory accepted_for_clock_query
full_report original_run_lock_sha256 original_evidence_lock_sha256
checker_orchestration_version checker_source_sha256 full_summary anchor_origin
P3_accepted P4_accepted
```

`full_report` is exactly `{path, sha256, size}`, and `full_summary` is the original
`save_run_report` return, including that same identity. The original report and
summary must pass, mode is `positive`, orchestration version is 7, and
`accepted_for_clock_query` is true. `P3_accepted` and `P4_accepted` remain false:
one original run cannot accept the whole delivery. The receipt must predate the
new aggregation. A failed positive receipt remains valid historical custody but
cannot be memoized as accepted evidence.

## Contemporaneously reference-bound control receipt v2

Schema: `simscene.independent_full_report_custody.v2`. All v1 fields remain;
`accepted_for_clock_query` is false and original mode is the named control.
The following additional fields are mandatory:

```text
evaluation_started_at_utc
reference_prebinding = {path, sha256}
reference_postcheck = {completed_at_utc, unchanged: true, anchors}
```

The prebinding file schema is `simscene.independent_reference_prebinding.v1`.
Its exact fields are:

```text
schema created_at_utc current_run_directory mode reference_run_directory
reference_record reference_full_report reference_run_lock_sha256
reference_evidence_lock_sha256 reference_result_sha256
reference_clock_certificate
```

`reference_record` is the prior independent positive receipt identity. The full
report and clock certificate identities are `{path, sha256, size}`. All original
reference anchors originate in that already retained positive receipt/report and
complete original clock4 certificate, never a fresh root metadata inventory.
The certificate must retain its original report/run/evidence/result provenance,
complete geometry, collapsed physical entry, inner no-escape and all-prefix
timing success. The original reference masks are used to recheck its exact
clock4 prefix before that full reference report is released. The delivery
orchestrator separately checks the full certificate/static-geometry dependency
closure for all five positive runs.

Postcheck `anchors` has exactly:

```text
receipt_sha256 full_report_sha256 run_lock_sha256 evidence_lock_sha256
result_sha256 clock_certificate_sha256
```

These must equal the original prebinding anchors, with chronology:

```text
reference receipt < prebinding < original control evaluation start
evaluation start <= reference postcheck <= control receipt < aggregation start
```

The current control's independently retained report, verified canonical spec,
all thirteen runtime fields and geometry policy must match the same original
positive reference; unchanged `isolated_control_spec` checks exact allowed edits.
Reference locks/result/receipt/clock/prebinding are checked again after the
current load. An old v1 control receipt without contemporaneous reference proof
is rejected; the missing proof cannot be manufactured retrospectively. The
original full checker remains available if such a control needs recomputation.

## Bounds, tests and final authority

Supported inputs are JSON case snapshots, at most 20,000 original steps, a 1 GiB
complete report, 64 MiB per metadata document, 10,000 output artifacts and 64 GiB
total locked artifact bytes. Unsupported sizes/encodings fail rather than omit
data. Hashing is streamed through original SHA helpers. This is a bounded
retention design, not a universal guarantee against the memory expansion of a
single supported JSON report.

Synthetic tests exercise real input/output/package/asset closure, unchanged full
serialization, no result parsing or physics reevaluation, all-step mask checks,
metadata and path adversaries, missing runtime fields, incomplete/foreign clocks,
contemporaneous reference proof and reference-report release before current load.
Their tiny bookkeeping fixture explicitly mocks only physical contract
validation; an additional test restores the actual frozen validator and proves
that fixture is not a valid P3 case. No test presents synthetic evidence as an
actual scene's acceptance.

The caller still must apply **all unchanged suite7 final gates**, full attempt
inventory/chronology, three controls, three clean repeats, physical-entry clock4
certificates, exact variant comparison, native footage and distinct editable
project replay. This helper neither publishes nor actuates anything. Its output
must label memoized original evaluations accurately and must not claim a
monolithic suite7 rerun.
