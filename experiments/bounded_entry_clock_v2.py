"""Additive original-mask clock over independently declared entry bounds.

No scene commands, new activity credit, re-timing or altered stock report.
Physical-entry/no-escape scope is complete only when observed bounds collapse.
Static cavity containment is an independent pre-job premise, not inferred here.
"""
import argparse
import copy
from fractions import Fraction as F
import gc
import itertools
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import box_halfspace_observation_v2 as h, whole_home_fidelity_v5 as f
from simscene.verification import passive_network as p, mechanism as m

SCHEMA = 'simscene.bounded_entry_clock.v2'
DEPENDENCIES = {'halfspace_observer': '57a37688a514a70a2ae4a80a16c178e2b75b0e451cae79519d28a6d2f11d6620',
                'fidelity': '5f7b04052f05737535a4bc54dc1d71531c5bf71fbcb17f22ba91f5c0c668de57'}
LIMIT_KEYS = {'minimum_chain_duration_s', 'minimum_net_effective_action_s', 'minimum_motion_occupancy', 'maximum_idle_s'}
require, sha, canonical_sha = h.require, h.sha, h.canonical_sha


def assert_dependencies():
    f.assert_kernel()
    require(sha(h.__file__) == DEPENDENCIES['halfspace_observer'] and sha(f.__file__) == DEPENDENCIES['fidelity'], 'frozen additive geometry/fidelity helper changed')


def exact_vertices(prepared):
    """Enumerate all vertices of a previously bounded full-dimensional volume."""
    planes = prepared['planes'];vertices = set()
    for a, b, c in itertools.combinations(planes, 3):
        det = h.dot(a['n'], h.cross(b['n'], c['n']))
        if not det: continue
        terms = [h.cross(b['n'], c['n']), h.cross(c['n'], a['n']), h.cross(a['n'], b['n'])]
        point = tuple((a['b']*terms[0][i]+b['b']*terms[1][i]+c['b']*terms[2][i])/det for i in range(3))
        if all(h.dot(plane['n'], point) <= plane['b'] for plane in planes): vertices.add(point)
    require(vertices, 'bounded full-dimensional volume has no exact vertices')
    return vertices


def points_inside(points, prepared):
    return all(h.dot(plane['n'], point) <= plane['b'] for point in points for plane in prepared['planes'])


def stock_region_corners(spec, case):
    terminal = case['terminal'];obj = spec['objects'][terminal['receiver_id']]
    lower, upper = terminal['interior_local']['min'], terminal['interior_local']['max']
    require(m.vector(lower) and m.vector(upper) and all(a < b for a, b in zip(lower, upper)), 'finite stock region bounds required')
    q = obj.get('orientation_wxyz', [1, 0, 0, 0]);position = obj.get('position', [0, 0, 0])
    require(m.quaternion(q) and m.vector(position) and obj.get('dynamic') is not True, 'stock receiver must be statically authored')
    # Invert the exact affine receiver map used by stock rotate(conjugate(q)).
    # Do not replace its almost-unit authored quaternion with a different
    # normalized rotation. Actual floating/runtime endpoint coverage is also
    # checked separately, since the box observer normalizes recorded box q.
    w, x, y, z = [F(q[0]), -F(q[1]), -F(q[2]), -F(q[3])]
    a = [1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)]
    c = [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]
    row = [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)]
    det = h.dot(a, h.cross(row, c));require(det, 'stock receiver affine map is singular')
    terms = [h.cross(row, c), h.cross(c, a), h.cross(a, row)]
    return [[F(position[i])+sum(F(local[j])*terms[j][i] for j in range(3))/det for i in range(3)]
            for local in itertools.product(*zip(lower, upper))]


def prepare(contract, inner, outer, spec, case):
    fields = {'schema', 'case_sha256', 'inner_contract_sha256', 'outer_contract_sha256',
              'static_review_sha256', 'physics_dt_s', 'limits', 'physical_entry_scope'}
    require(isinstance(contract, dict) and set(contract) == fields and contract['schema'] == SCHEMA, 'expected complete '+SCHEMA)
    require(case.get('profile') == 'P3', 'original P3 profile required')
    require(contract['physical_entry_scope'] == 'collapsed_observed_bounds_only', 'no unimplemented transit-proof exception')
    for key in ('case_sha256', 'inner_contract_sha256', 'outer_contract_sha256', 'static_review_sha256'):
        value = contract[key]
        require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value), 'exact predeclared hash required: '+key)
    limits = contract['limits']
    require(isinstance(limits, dict) and set(limits) == LIMIT_KEYS and all(m.finite(v) for v in limits.values()), 'declare all finite clock floors')
    require(limits == case['activity']['limits'] and limits['minimum_chain_duration_s'] >= 50 and limits['minimum_net_effective_action_s'] >= 45 and .85 <= limits['minimum_motion_occupancy'] <= 1 and 0 < limits['maximum_idle_s'] <= 2, 'same original floors, at least50/45/.85 and at most2s idle required')
    require(m.finite(contract['physics_dt_s']) and contract['physics_dt_s'] > 0, 'positive original timestep required')
    for declaration in (inner, outer):
        require(all(declaration.get(k) == inner.get(k) for k in ('case_sha256', 'physics_dt_s', 'box_body_id', 'receiver_id', 'box_size_m', 'box_configuration_sha256', 'receiver_configuration_sha256', 'static_review_sha256')), 'entry declarations differ in physical roots/case/clock/review')
        require(declaration['case_sha256'] == contract['case_sha256'] and declaration['physics_dt_s'] == contract['physics_dt_s'] and declaration['static_review_sha256'] == contract['static_review_sha256'], 'clock contract differs from declared geometry')
    require(inner['box_body_id'] == case['terminal']['body_id'] and inner['receiver_id'] == case['terminal']['receiver_id'], 'clock geometry must bind the actual stock terminal roots')
    a, b = h.prepare(inner), h.prepare(outer)
    vertices = exact_vertices(a)
    require(points_inside(vertices, b), 'declared inner volume is not a subset of outer enclosure')
    require(points_inside(stock_region_corners(spec, case), a), 'stock region is not an inward-certified subset of inner region')
    return {'inner': a, 'outer': b, 'exact_inner_vertex_count': len(vertices)}


def prefixes(stock, case, first, last, dt):
    """Use every original flag once; never synthesize a missing interval."""
    activity = stock['activity'];metrics = activity['metrics'];flags = activity['per_step_motion_flags']
    release, end = metrics['window_start_step'], metrics['window_end_step']
    require(type(release) is int and type(end) is int and release == case['release_step'] and end == stock['terminal']['first_whole_entry_step'], 'stock window is not original release to first stock entry')
    require(isinstance(flags, list) and [r.get('physics_step') for r in flags] == list(range(release+1, end+1)), 'original mask missing/duplicate/reordered intervals')
    require(type(first) is int and type(last) is int and release < first <= last <= end, 'missing prefix coverage, pre-cue entry or stock-earlier scope')
    roles = {body['id'] for stage in case['activity']['stages'] for body in stage['bodies']}
    stages = {stage['id'] for stage in case['activity']['stages']}
    active = idle = longest = 0;rows = [];limits = case['activity']['limits']
    for index, row in enumerate(flags, 1):
        require(type(row.get('active')) is bool and isinstance(row.get('body_ids'), list) and isinstance(row.get('stage_ids'), list) and set(row['body_ids']) <= roles and set(row['stage_ids']) <= stages and row['active'] == bool(row['body_ids']) == bool(row['stage_ids']), 'invalid/unregistered original union mask')
        require(m.finite(row.get('simulation_time_s')) and abs(row['simulation_time_s']-row['physics_step']*dt) <= max(1e-6, dt*1e-4), 'original mask clock differs')
        active += row['active'];idle = 0 if row['active'] else idle+1;longest = max(longest, idle)
        current = {'chain_duration_s': index*dt, 'net_effective_action_s': active*dt,
                   'motion_occupancy': active/index, 'maximum_idle_s': longest*dt}
        if first <= row['physics_step'] <= last:
            checks = {'minimum_chain_duration': current['chain_duration_s'] >= limits['minimum_chain_duration_s'],
                      'minimum_net_effective_action': current['net_effective_action_s'] >= limits['minimum_net_effective_action_s'],
                      'minimum_motion_occupancy': current['motion_occupancy'] >= limits['minimum_motion_occupancy'],
                      'maximum_idle': current['maximum_idle_s'] <= limits['maximum_idle_s']}
            rows.append({'end_boundary_step': row['physics_step'], 'interval_start_inclusive': release,
                         'interval_end_exclusive': row['physics_step'], 'metrics': current, 'checks': checks, 'passed': all(checks.values())})
    require(all(math.isclose(current[k], metrics[k], abs_tol=1e-10, rel_tol=1e-10) for k in current), 'reported full stock metrics disagree with original masks')
    require(len(rows) == last-first+1, 'not every possible original prefix end was checked')
    return {'passed': all(row['passed'] for row in rows), 'prefixes': rows,
            'original_full_masks_sha256': canonical_sha(flags), 'original_full_window': [release, end],
            'possible_end_boundaries_inclusive': [first, last], 'source_flags_unchanged': True}


def evaluate(run, spec, case, stock, inner, outer, contract):
    result = {'schema': SCHEMA, 'geometry_queries_complete': False, 'bounded_timing_floors_passed': False,
              'physical_entry_no_escape_complete': False, 'supplemental_complete': False,
              'file_integrity_verified': False, 'formal_house_accepted': False, 'stability_assessed': False, 'errors': []}
    try:
        preparation = prepare(contract, inner, outer, spec, case)
        require(stock.get('passed') is True and stock.get('mode') == 'positive' and stock.get('profile') == 'P3' and stock.get('activity', {}).get('passed') is True and stock.get('terminal', {}).get('passed') is True, 'preserve an already accepted original positive stock report')
        # No full report is copied and no input sample is altered/sliced.
        inside = h.evaluate(run, spec, inner);outside = h.evaluate(run, spec, outer)
        require(inside['geometry_query_complete'] and outside['geometry_query_complete'], 'complete bounded original-step geometry queries required')
        require(inside['first_complete_entry'] is not None and outside['first_complete_entry'] is not None, 'inner/outer entry absent')
        left = outside['first_complete_entry']['physics_steps'];right = inside['first_complete_entry']['physics_steps']
        result.update(geometry_queries_complete=True, inner_first_entry=inside['first_complete_entry'],
                      outer_first_entry=outside['first_complete_entry'], inner_escape_steps=inside['escape_steps'])
        dt = contract['physics_dt_s'];stock_end = stock['terminal']['first_whole_entry_step']
        require(type(stock_end) is int and left <= right <= stock_end, 'entry ordering/stock coverage failed; never invent later masks')
        terminal_condition = p.event_definitions(case)['terminal_entered']['conditions'][0]
        observed_stock = [m.condition_matches(terminal_condition, sample, run['initial_observation'], spec) for sample in run['samples']]
        require(observed_stock == stock['terminal']['whole_sugar_inside_per_step'] and next((i for i, value in enumerate(observed_stock, 1) if value), None) == stock_end, 'original stock terminal masks/entry differ from full original telemetry')
        timing = prefixes(stock, case, left, right, dt)
        inner_no_escape = inside['membership_supplement_passed'] is True
        collapsed = left == right
        result.update(geometry_queries_complete=True, inner_first_entry=inside['first_complete_entry'], outer_first_entry=outside['first_complete_entry'],
            original_stock_entry_step=stock_end, actual_first_entry_observed_step_bounds_inclusive=[left, right],
            actual_chain_duration_s_bounds=[(left-case['release_step'])*dt, (right-case['release_step'])*dt],
            inner_no_escape=inner_no_escape, inner_escape_steps=inside['escape_steps'], outer_escape_steps=outside['escape_steps'],
            every_possible_original_prefix=timing, exact_inner_vertex_count=preparation['exact_inner_vertex_count'],
            bounded_timing_floors_passed=timing['passed'], physical_entry_no_escape_complete=collapsed and inner_no_escape,
            supplemental_complete=bool(timing['passed'] and collapsed and inner_no_escape),
            physical_entry_scope='Collapsed original observed boundaries plus inner no-escape cover physical earliest/no-escape at every recorded boundary.' if collapsed and inner_no_escape else 'Unresolved physical earliest/no-escape between bounds; timing-only success does not complete this supplement.',
            static_geometry_scope='Conditional on independently frozen I subset physical cavity subset O; this kernel proves polytope/stock ordering but not modeled cavity equivalence.',
            between_step_continuity='not_established', stability_authority='Unchanged original stock/v5 report; this tool does not assess stability or replace its hold.',
            original_flags_scope='Only prefixes of unchanged original stock masks, every [release,end) interval once; no credit added or retimed.')
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, ArithmeticError, MemoryError) as error:
        result['errors'].append({'type': type(error).__name__, 'reason': str(error)})
    return result


def reduced_report(path, expected_sha, root, expected_locks):
    require(sha(path) == expected_sha, 'independently retained full-verifier report SHA differs')
    report = json.loads(Path(path).read_text())
    require(report.get('passed') is True and report.get('mode') == 'positive' and report.get('orchestration_version') == 5 and report.get('supplemental_code_sha256') == DEPENDENCIES['fidelity'], 'accepted independent full v5 positive report required')
    require(Path(report['run_directory']).resolve() == root and report['run_lock_sha256'] == expected_locks['run-lock.json'] and report['evidence_lock_sha256'] == expected_locks['evidence-lock.json'], 'full verifier report belongs to different original locks/run')
    stock = report['stock']
    require(stock.get('checker_sha256') == f.KERNEL_SHA256['passive_network'], 'full verifier report has a different frozen stock kernel')
    result = {'stock': {k: copy.deepcopy(stock[k]) for k in ('passed', 'mode', 'profile', 'case_sha256', 'activity', 'terminal')},
              'evidence_sha256': copy.deepcopy(report['suite_metadata']['evidence_sha256'])}
    # Complete reports are read alone, then reduced before loading raw telemetry.
    del report;gc.collect()
    return result


def verify(directory, case_path, inner_path, outer_path, contract_path, review_path, freeze_path,
           full_report_path, full_report_sha256, original_run_lock_sha256, original_evidence_lock_sha256):
    result = {'schema': SCHEMA, 'file_integrity_verified': False, 'supplemental_complete': False,
              'formal_house_accepted': False, 'errors': []}
    try:
        assert_dependencies();root = Path(directory).resolve()
        paths = [Path(v).resolve() for v in (case_path, inner_path, outer_path, contract_path, review_path, freeze_path)]
        case_path, inner_path, outer_path, contract_path, review_path, freeze_path = paths
        retained = {'run-lock.json': original_run_lock_sha256, 'evidence-lock.json': original_evidence_lock_sha256}
        require(all(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value) for value in [*retained.values(), full_report_sha256]), 'independent retained original lock/full-report SHA256 anchors required')
        require(all(sha(root/name) == digest for name, digest in retained.items()), 'original lock bytes changed')
        reduced = reduced_report(full_report_path, full_report_sha256, root, retained)
        before = {name: sha(root/name) for name in ('run-lock.json', 'evidence-lock.json', 'result.json', 'spec.json')}
        require(all(reduced['evidence_sha256'].get(name) == before[name] for name in ('run-lock.json', 'evidence-lock.json', 'result.json')), 'independent full report differs from original evidence/result')
        external = {str(path): sha(path) for path in paths}
        case, inner, outer, contract, review, freeze = [json.loads(path.read_text()) for path in paths]
        require(sha(case_path) == contract['case_sha256'] == reduced['stock']['case_sha256'] and sha(inner_path) == contract['inner_contract_sha256'] and sha(outer_path) == contract['outer_contract_sha256'] and sha(review_path) == contract['static_review_sha256'], 'frozen case/inner/outer/static-review identities differ')
        require(review.get('scope') == 'independent_static_inner_outer_entry_bounds' and review.get('reviewer_role') == 'independent_examiner' and review.get('passed') is True and review.get('inner_inside_physical_cavity') is True and review.get('physical_cavity_inside_outer') is True and review.get('inner_planes_sha256') == canonical_sha(inner['planes']) and review.get('outer_planes_sha256') == canonical_sha(outer['planes']) and review.get('case_sha256') == contract['case_sha256'] and isinstance(review.get('physical_cavity_definition'), str) and review['physical_cavity_definition'], 'independent static cavity-bound premises required')
        require(isinstance(review.get('files_sha256'), dict) and review['files_sha256'] and all(Path(name).is_file() and sha(name) == digest for name, digest in review['files_sha256'].items()), 'static source geometry proof files changed/missing')
        lock = json.loads((root/'run-lock.json').read_text())
        require(freeze.get('schema') == 'simscene.bounded_entry_clock_freeze.v1' and h._date(freeze['frozen_at_utc']) < h._date(lock['created_at_utc']), 'independent binding must predate original job snapshot')
        required_paths = [*paths[:-1], Path(__file__).resolve(), Path(h.__file__).resolve(), Path(f.__file__).resolve()]
        require(all(freeze.get('files_sha256', {}).get(str(path)) == sha(path) for path in required_paths), 'pre-job freeze omits/changes code/case/contracts/review')
        require(lock['physics_dt_s'] == contract['physics_dt_s'] and 0 < lock['requested_physics_steps'] <= h.MAX_STEPS, 'unsupported original clock/step budget')
        def mapping_case(value):
            require(isinstance(value, dict) and value.get('profile') == 'P3', 'original P3 mapping required; its complete physics semantics remain the independently retained full v5 report authority')
        data = p._read_locked(root, case_path, case_validator=mapping_case)
        require(data['passed'], 'complete original input/output/case/source locks required')
        result = evaluate(data['run'], data['spec'], case, reduced['stock'], inner, outer, contract)
        require(all(sha(root/name) == digest for name, digest in before.items()) and all(sha(name) == digest for name, digest in external.items()) and sha(full_report_path) == full_report_sha256, 'original files or predeclared contracts changed during evaluation')
        require(all(sha(name) == digest for name, digest in review['files_sha256'].items()), 'static geometry source changed during evaluation')
        result.update(file_integrity_verified=True, provenance={'original_files_sha256': before,
            'external_files_sha256': external, 'independently_retained_lock_sha256': retained,
            'independently_retained_full_report_sha256': full_report_sha256, 'full_report_path': str(Path(full_report_path).resolve()),
            'helper_sha256': sha(__file__), 'input_output_proof': data['integrity']})
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, ArithmeticError, MemoryError) as error:
        result['supplemental_complete'] = False;result['file_integrity_verified'] = False
        result['errors'].append({'type': type(error).__name__, 'reason': str(error)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'case', 'inner', 'outer', 'contract', 'review', 'freeze', 'full-report', 'full-report-sha256', 'run-lock-sha256', 'evidence-lock-sha256', 'output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args();output = Path(args.output).resolve()
    require(not output.is_relative_to(Path(args.run).resolve()), 'output must remain outside sealed original run')
    result = verify(args.run, args.case, args.inner, args.outer, args.contract, args.review, args.freeze,
                    args.full_report, args.full_report_sha256, args.run_lock_sha256, args.evidence_lock_sha256)
    with output.open('x') as stream: json.dump(result, stream, indent=2, allow_nan=False);stream.write('\n')
    print(json.dumps({k: result.get(k, False) for k in ('geometry_queries_complete', 'bounded_timing_floors_passed', 'physical_entry_no_escape_complete', 'supplemental_complete', 'file_integrity_verified')}))
    return 0 if result.get('supplemental_complete') and result.get('file_integrity_verified') else 1


if __name__ == '__main__': raise SystemExit(main())
