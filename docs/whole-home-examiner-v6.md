# Independent external examiner v6

This pre-formal version adds explicit composition of the two event mechanisms.
It does not edit installed v41, its 105 pinned source files, ce05, network 0ed9,
any old case, or any archived examiner/report. Old v5 rejection remains correct:
the complete standalone pilots require a direct global cue contact that a
whole-room chain does not have. No actual candidate trajectory informed this
extension. Synthetic fixtures exercise the unchanged ce05 entry point.

## Contracts and authority

`whole_home_fidelity_v6.py` uses schema `simscene.whole_home_fidelity.v4`,
orchestration version 6. `whole_home_suite_v6.py` uses suite schema v4. Stock
`mechanism_cases` contains complete unchanged rope assertions only. An external
fidelity contract additionally requires `composed_mechanisms`, exactly one
`wheel_door_bridge` and one `spoon_sugar` declaration, keyed by frozen names:

```json
{
  "wheel_module": {
    "mechanism_case": {"schema": "simscene.mechanism.v1", "mechanism": "wheel_door_bridge"},
    "incoming_handoff_id": "existing_named_contact_handoff",
    "local_input_body_id": "actual_upstream_dynamic_body"
  }
}
```

The example omits required mechanism fields for brevity and is not an executable
case. Each definition must contain every ce05 role, joint, axis, threshold and
geometric field and `require_strict_initial_state: true`; unknown fields and
optional local activity are rejected. The global unique trigger ID and release
step must remain identical. Actual case/spec/contract files remain hash-bound
through the original sealed evidence, nominal configuration, independent static
review and pre-job freeze. The bridge field now names
`composed_mechanism_key`; it consumes the explicit composed result directly.
It never fabricates a successful stock/P1 subreport.

`composed_event_mechanisms.py` calls the original unmodified
`m.evaluate_event_mechanism(run, spec, definition, dt)` once per module, passing
the identical full run/spec objects. That entry point executes the unchanged
`event_mechanism_base` and wheel/spoon evaluator and computes the original final
`passed`. No samples, poses, clocks, events or trigger are sliced, rebased or
changed. The entire raw report, including false direct-global contact and raw
false `passed`, is retained in the composed report.

The adapter freezes exact inventories: 43 strict/base checks, 11 module physical
checks, and 4 spoon / 5 wheel contact reports. Every base and every non-aggregate
physical check must be true. It verifies raw `passed == all(raw.checks)` and the
known contact aggregate `== all(raw.contacts.passed)`. All non-incoming raw
contacts must pass unchanged. Only the known
`all_physical_handoff_contacts_witnessed` aggregate may be false because of the
explicit direct-global incoming contact. There is no filter that drops arbitrary
false checks, no acceptance of an unknown inventory, and no claim that a raw
full P1 pilot passed. A raw full pilot that actually passes is also retained
honestly; composition still requires its independent local edge.

## Actual local incoming witness

The replacement must name one existing required global two-body contact handoff
with exactly `[local_input_body, wheel_or_lasttile]`. Source and target events
measure exactly those roots. The source must be reachable from `trigger_release`
and target must reach `terminal_entered` in the unchanged global DAG. The local
source cannot be the global trigger, any module role, or a scheduled spawn; both
endpoints must be initially present dynamic colliders. Complete stock network
validation and all its actual physical handoffs remain mandatory.

The stock local handoff must pass. Its measured source onset must follow global
release and precede both global target onset and original ce05 first target
activation. The original per-step journal must contain an identified actual
callback in the intersection `[source_onset, min(global_target_onset,
raw_target_activation)]`, with tolerance equal to the smaller of the two already
frozen contact-window tolerances. Original absolute callback counters remain
unchanged. This is a boundary witness, not an invented contact instant. An
eventual summary contact, unrelated body, late callback, failed stock handoff,
missing step or invalid strict t0 cannot replace it. Each non-incoming ce05
contact additionally needs an original per-step callback in its original ce05
window. Bindings, original events, callback records and failed checks remain
visible in the result.

Stopping controls deliberately do not assert completed wheel/spoon/cart/bridge
or terminal outcomes. All three original isolated-control comparators, matched
runtime/source/geometry proofs, downstream quiet, global passivity, typed-load
proofs and zero-contact auxiliary checks still gate every control. Positive
completion cannot be inferred from a stopped control.

## Unchanged predicates and variants

No energy, force, mass, inertia, drive, initial quiet, tile, household category,
activity, control, terminal or stability predicate is relaxed. All 200 named
tiles still require first and final 60-degree tilt; at least six transmitting
types, 50-second span, 45-second original-mask net time, 0.85 occupancy and at
most 2 seconds idle remain. Whole cube and 121 samples **and** actual 2-second
onset-to-confirmation remain. Wheel spin supplies no activity/category credit.
Three consecutive clean main runs, three exact controls, cup 20 cm plus an
independent local physical variation, and distinct editable new-directory
full replay/native video remain required.

The existing variant scene/case comparator is retained verbatim as
`_compare_variant_core`. A declaration additionally carries
`fidelity_geometry_changes`. The new contract comparator permits only exact
predeclared geometric patches under composed spoon support/receiver-world bounds
or wheel bridge regions. These must be independently certified static
transformations for the actual variant before snapshots. Every other field,
including roles, local handoffs, global trigger/release, thresholds, clocks,
cart rules and physical gates, remains exact. Only the three separately verified
case/configuration/static-review hash identities differ by definition. A whole
module replacement or an undeclared coordinate change fails. Source scene,
case, contract and static review remain separately frozen.

## Clock v3

`bounded_entry_clock_v3.py` uses schema `simscene.bounded_entry_clock.v3` and pins
the exact v6 fidelity reader. It accepts only an independently retained complete
orchestration-6 positive report and its original run/evidence lock anchors.
The halfspace helper, exact polytope/stock inclusion, original masks, all-prefix
50/45/.85/2 tests, earliest inner entry, no escape and mandatory observed-bound
collapse are unchanged. Geometry/time theorem AST identity is tested; only the
authority version label and pinned reader/report version change. Timing-only
success still cannot establish physical entry/no-escape or stability. No new
credit, later entry, alternate stability authority or cavity equivalence is
introduced. Old clock v1/v2 and all archives remain unchanged.

## Execution and limits

Use v6 suite CLI as before with an exact frozen manifest; individual full reports
are streamed atomically to fresh report paths, and raw runs are released between
runs. Suite summaries include composed verdicts but preserve complete raw P1
reports in the individual report files. File-level stock integrity is mandatory;
pure helper calls on supplied dictionaries do not establish evidence custody.
Keep all generic code, tests and policy hashes frozen before any actual runtime
query. Then independently freeze the static scenario contracts before any
formal job. Neither a single composed positive nor the suite authorizes
publication or establishes randomized robustness, calibrated contact forces,
continuous-time containment, no-slip rolling, or readable cinematography.
