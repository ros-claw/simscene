"""Locate the earliest observed broken handoff without reading raw trajectories.

Input is a retained verifier report. A diagnosis is not a new physical verdict,
nor a claim that the verifier or its source files were independently trusted.
"""
import hashlib
import json
from pathlib import Path


def _load(path):
    p = Path(path).expanduser().resolve()
    if not p.is_file() or p.stat().st_size > 128*2**20:
        raise ValueError('bounded retained report/case required (maximum 128 MiB)')
    data = p.read_bytes()
    return json.loads(data), {'path': str(p), 'sha256': hashlib.sha256(data).hexdigest()}


def diagnose(report_path, case_path):
    report, report_ref = _load(report_path)
    case, case_ref = _load(case_path)
    stock = report.get('stock', report)
    base = {'schema': 'simscene.handoff_diagnosis.v1', 'status': 'unknown',
            'observed': {}, 'hypotheses': [], 'suggested_probe': None,
            'evidence_ref': {'report': report_ref, 'case': case_ref},
            'scope': 'Read-only diagnosis of the supplied report; not acceptance, root-cause proof, or permission to actuate.'}
    timeline = stock.get('timeline', {})
    missing = [name for name, value in [('timeline', timeline.get('passed')),
               ('input_integrity', stock.get('input_integrity', {}).get('passed')),
               ('output_integrity', stock.get('output_integrity', {}).get('passed'))] if value is not True]
    if missing:
        base['observed'] = {'reason': 'incomplete_or_untrusted_record', 'missing_complete_checks': missing}
        return base
    if stock.get('case_sha256') and stock['case_sha256'] != case_ref['sha256']:
        base['observed'] = {'reason': 'supplied_case_does_not_match_report'}
        return base
    events = stock.get('events')
    handoffs = case.get('handoffs')
    if not isinstance(events, dict) or not isinstance(handoffs, list) or not handoffs:
        base['observed'] = {'reason': 'no_supported_event_graph', 'supported': 'passive_network retained reports'}
        return base
    mode = report.get('mode', stock.get('mode', 'positive'))
    control = case.get('controls', {}).get(mode, {})
    upstream = control.get('upstream_event_ids', [])
    def onset(name):
        event = events.get(name, {})
        value = event.get('onset_step')
        return value if type(value) is int and value >= 0 else None
    # Kahn levels avoid dict/alphabetic order being mistaken for causal order.
    nodes = {h[k] for h in handoffs for k in ('source_event', 'target_event')}
    predecessors = {n: set() for n in nodes}
    for h in handoffs:
        predecessors[h['target_event']].add(h['source_event'])
        for guard in h.get('guard_events', []):
            predecessors.setdefault(guard, set()).add(h['source_event'])
            predecessors[h['target_event']].add(guard)
    levels, remaining = {}, dict(predecessors)
    while remaining:
        ready = [n for n, parents in remaining.items() if parents <= set(levels)]
        if not ready:
            base['observed'] = {'reason': 'cyclic_or_invalid_event_graph'}
            return base
        for n in ready:
            levels[n] = max((levels[x]+1 for x in remaining[n]), default=0)
            del remaining[n]
    measured = stock.get('handoffs', {})
    ordered = sorted(handoffs, key=lambda h: (levels[h['target_event']], levels[h['source_event']], h['id']))
    failures = []
    for h in ordered:
        source, target = onset(h['source_event']), onset(h['target_event'])
        guards = [onset(n) for n in h.get('guard_events', [])]
        complete = source is not None and target is not None and all(n is not None for n in guards)
        sequence = [source, *guards, target]
        good_order = complete and all(a <= b for a, b in zip(sequence, sequence[1:]))
        in_time = complete and target-source <= h.get('maximum_lag_steps', float('inf'))
        evidence_failed = measured.get(h['id'], {}).get('passed') is False
        if source is not None and (not good_order or not in_time or evidence_failed):
            failures.append((h, source, target, guards))
    upstream_missing = [n for n in upstream if onset(n) is None]
    base['observed'].update(mode=mode, source_report_passed=stock.get('passed'),
                            handoff_evidence_scope='reported_physical_links' if measured else 'event_frontier_only',
                            required_control_upstream_missing=upstream_missing)
    if mode != 'positive' and stock.get('passed') is True:
        base['status'] = 'expected_control_block'
        base['observed']['reason'] = 'source_report_accepts_this_specific_intervention'
        base['observed']['expected_cut_handoff'] = control.get('cut_handoff_id')
        return base
    if not failures:
        base['status'] = 'no_failed_handoff_in_report' if stock.get('passed') is True else 'unknown'
        base['observed']['reason'] = ('all_declared_handoffs_complete' if stock.get('passed') is True
                                      else 'source_failed_without_a_supported_local_handoff_witness')
        return base
    h, source, target, guards = failures[0]
    ids = list(dict.fromkeys(h['body_path']))
    earlier = [v for v in ordered if levels[v['target_event']] < levels[h['target_event']]
               and onset(v['target_event']) is not None and measured.get(v['id'], {}).get('passed') is not False]
    base['status'] = 'first_failed_handoff'
    base['observed']['selection_rule'] = 'earliest rooted causal depth; independent branches are not a total causal order'
    base['observed'].update(handoff_id=h['id'], source_event=h['source_event'], source_step=source,
                            target_event=h['target_event'], target_step=target,
                            guard_steps=guards, body_ids=ids[:8],
                            last_completed_event=earlier[-1]['target_event'] if earlier else h['source_event'])
    if earlier:
        previous = earlier[-1]
        base['observed']['last_completed_event_edge'] = {
            'source_event': previous['source_event'], 'source_step': onset(previous['source_event']),
            'target_event': previous['target_event'], 'target_step': onset(previous['target_event']),
            'scope': 'declared event thresholds; physical link evidence is separate'}
    # Frozen geometry embedded in the original report can identify local
    # supports without returning the entire scene. AABBs are candidates only.
    objects = report.get('suite_metadata', {}).get('canonical_spec', {}).get('objects', {})
    if objects and ids:
        from .placement import bounds
        import math
        sources = [bounds(objects[n]) for n in ids[:2] if n in objects]
        nearby = []
        for name, obj in objects.items():
            if obj.get('dynamic') or obj.get('collision', True) is False or obj.get('kind') not in ('box','sphere','capsule','cylinder','compound'):
                continue
            box = bounds(obj)
            distance = min((math.sqrt(sum(max(a['min'][i]-box['max'][i], box['min'][i]-a['max'][i], 0)**2 for i in range(3))) for a in sources), default=1)
            if distance <= .025:
                nearby.append({'id': name, 'initial_AABB_gap_m': distance, 'bounds': box})
        nearby.sort(key=lambda x: (x['initial_AABB_gap_m'], x['id']))
        base['observed']['nearby_static_candidates'] = nearby[:8]
        base['observed']['geometry_scope'] = 'Frozen initial AABB neighbours, not observed collision or a proven obstruction.'
    tile_values = {n: {k: stock['tiles'][n].get(k) for k in
                          ('maximum_tilt_degrees', 'first_tipped_step', 'final_tilt_degrees')}
                   for n in ids if n in stock.get('tiles', {})}
    if tile_values:
        base['observed']['tiles'] = tile_values
        base['hypotheses'].append({'claim': 'Check support/collision clearance and available tipping impulse at this boundary.',
                                   'basis': 'Observed tile tilt/failed transfer; obstruction has not been measured.'})
    failed_links = [i for i, link in enumerate(measured.get(h['id'], {}).get('links', [])) if link.get('passed') is False]
    if failed_links:
        base['observed']['failed_link_indices'] = failed_links[:4]
        base['hypotheses'].append({'claim': 'Inspect the local contact or joint-frame witness.',
                                   'basis': 'The supplied report rejects these link witnesses; this does not identify a unique physical cause.'})
    if upstream_missing:
        base['observed']['control_conclusion'] = 'Upstream prerequisites did not occur; downstream quietness alone cannot validate the intervention.'
    base['evidence_ref']['report_pointer'] = '/stock/events' if 'stock' in report else '/events'
    probe_ids = list(dict.fromkeys(ids[:8]+[x['id'] for x in base['observed'].get('nearby_static_candidates', [])]))
    base['suggested_probe'] = {'body_ids': probe_ids, 'start_step': max(0, source-60),
                               'end_step': source+max(120, min(600, h.get('maximum_lag_steps', 120))),
                               'action': 'Inspect these bodies and their actual supports/obstacles; build a small initial-state bench for the first missing transfer before changing the downstream chain.'}
    return base


def write_diagnosis(report_path, case_path, output):
    value = diagnose(report_path, case_path)
    p = Path(output).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    # Fixed field projection instead of truncation of arbitrary serialized JSON.
    observed = value['observed']
    summary = {'status': value['status'], 'observed': {k: observed[k] for k in
               ('reason', 'handoff_id', 'source_event', 'source_step', 'target_event', 'target_step',
                'last_completed_event', 'last_completed_event_edge', 'handoff_evidence_scope', 'required_control_upstream_missing', 'control_conclusion', 'tiles') if k in observed},
               'diagnostic_ref': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
               'suggested_probe': value['suggested_probe'], 'acceptance_claimed': False}
    if len(json.dumps(summary, ensure_ascii=False).encode()) > 2048:
        summary.pop('suggested_probe', None)
        summary['observed'].pop('tiles', None)
    return summary
