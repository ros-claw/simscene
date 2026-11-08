"""Synthetic original-mask/geometry/custody adversaries, never house outcomes."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import ast

from experiments import bounded_entry_clock_v4 as b
from test_box_halfspace_observation_v2 import fixture as geometry_fixture, cube_planes
from test_passive_network import seal_fixture


def fixture(collapsed=False, inactive=()):
    count = 70
    centers = [[2, 0, 0] if step < 58 else ([0, 0, 0] if collapsed or step >= 62 else [.8 if step < 60 else .4, 0, 0]) for step in range(count+1)]
    run, spec, inner, _ = geometry_fixture(centers=centers)
    dt = 1.
    for sample in [run['initial_observation'], *run['samples']]:
        sample['simulation_time_s'] = sample['physics_steps']*dt
        sample['absolute_simulation_time_s'] = .05+sample['physics_steps']*dt
    run['simulation_time_s'] = count*dt
    case = {'profile': 'P3', 'release_step': 2, 'events': {}, 'trigger_id': 'cue',
        'terminal': {'body_id': 'box', 'receiver_id': 'receiver', 'size_m': [.2]*3,
            'interior_local': {'min': [-.3]*3, 'max': [.3]*3}, 'hold_steps': 3,
            'maximum_motion_m': .01, 'maximum_rotation_degrees': 2},
        'activity': {'limits': {'minimum_chain_duration_s': 50, 'minimum_net_effective_action_s': 45,
            'minimum_motion_occupancy': .85, 'maximum_idle_s': 2},
            'stages': [{'id': 'transfer', 'bodies': [{'id': 'box'}]}]}}
    inner.update(physics_dt_s=dt, planes=cube_planes(.6), case_sha256='c'*64)
    outer = copy.deepcopy(inner);outer['planes'] = cube_planes(1.)
    stock_end = 58 if collapsed else 62
    flags = [{'physics_step': step, 'simulation_time_s': step*dt, 'active': step not in inactive,
              'body_ids': ['box'] if step not in inactive else [], 'stage_ids': ['transfer'] if step not in inactive else []}
             for step in range(3, stock_end+1)]
    idle = longest = 0
    for row in flags:
        idle = 0 if row['active'] else idle+1;longest = max(longest, idle)
    metrics = {'window_start_step': 2, 'window_end_step': stock_end, 'chain_duration_s': (stock_end-2)*dt,
        'net_effective_action_s': sum(r['active'] for r in flags)*dt,
        'motion_occupancy': sum(r['active'] for r in flags)/len(flags), 'maximum_idle_s': longest*dt}
    condition = b.p.event_definitions(case)['terminal_entered']['conditions'][0]
    terminal_flags = [b.m.condition_matches(condition, sample, run['initial_observation'], spec) for sample in run['samples']]
    stock = {'passed': True, 'mode': 'positive', 'profile': 'P3',
        'activity': {'passed': True, 'metrics': metrics, 'per_step_motion_flags': flags},
        'terminal': {'passed': True, 'first_whole_entry_step': stock_end, 'whole_sugar_inside_per_step': terminal_flags}}
    contract = {'schema': b.SCHEMA, 'case_sha256': 'c'*64, 'inner_contract_sha256': 'd'*64,
        'outer_contract_sha256': 'e'*64, 'static_review_sha256': inner['static_review_sha256'],
        'physics_dt_s': dt, 'limits': copy.deepcopy(case['activity']['limits']),
        'physical_entry_scope': 'collapsed_observed_bounds_only'}
    return run, spec, case, stock, inner, outer, contract


def locked_fixture(root, review_valid=True):
    """Synthetic custody authority; not a simulated or real full-verifier pass."""
    run, spec, case, stock, inner, outer, contract = fixture(True)
    directory = root/'run';directory.mkdir();seal_fixture(directory, run, spec, case)
    lock = json.loads((directory/'run-lock.json').read_text())
    lock.update(physics_dt_s=1., created_at_utc='2021-01-01T00:00:00Z')
    (directory/'run-lock.json').write_text(json.dumps(lock))
    case_path = root/'case.json';case_path.write_text(json.dumps(case))
    proof = root/'static-proof.txt';proof.write_text('Generic synthetic static inner/outer premise; no actual receiver approval.\n')
    review = {'scope': 'independent_static_inner_outer_entry_bounds', 'reviewer_role': 'independent_examiner',
        'passed': review_valid, 'inner_inside_physical_cavity': True, 'physical_cavity_inside_outer': True,
        'physical_cavity_definition': 'Synthetic bounded volume only, not an actual household receiver.',
        'inner_planes_sha256': b.canonical_sha(inner['planes']), 'outer_planes_sha256': b.canonical_sha(outer['planes']),
        'case_sha256': b.sha(case_path), 'files_sha256': {str(proof.resolve()): b.sha(proof)}}
    review_path = root/'review.json';review_path.write_text(json.dumps(review))
    for item in (inner, outer): item.update(case_sha256=b.sha(case_path), static_review_sha256=b.sha(review_path))
    inner_path = root/'inner.json';inner_path.write_text(json.dumps(inner))
    outer_path = root/'outer.json';outer_path.write_text(json.dumps(outer))
    contract.update(case_sha256=b.sha(case_path), inner_contract_sha256=b.sha(inner_path),
        outer_contract_sha256=b.sha(outer_path), static_review_sha256=b.sha(review_path))
    contract_path = root/'clock.json';contract_path.write_text(json.dumps(contract))
    freeze = {'schema': 'simscene.bounded_entry_clock_freeze.v1', 'frozen_at_utc': '2020-01-01T00:00:00Z',
        'files_sha256': {str(path.resolve()): b.sha(path) for path in (case_path, inner_path, outer_path,
            contract_path, review_path, Path(b.__file__), Path(b.h.__file__), Path(b.f.__file__))}}
    freeze_path = root/'freeze.json';freeze_path.write_text(json.dumps(freeze))
    stock.update(case_sha256=b.sha(case_path), checker_sha256=b.f.KERNEL_SHA256['passive_network'])
    anchors = {name: b.sha(directory/name) for name in ('run-lock.json', 'evidence-lock.json')}
    full = {'passed': True, 'mode': 'positive', 'orchestration_version': 7,
        'scope': 'Synthetic custody wrapper fixture, not actual independently verified physics.',
        'supplemental_code_sha256': b.DEPENDENCIES['fidelity'], 'run_directory': str(directory.resolve()),
        'run_lock_sha256': anchors['run-lock.json'], 'evidence_lock_sha256': anchors['evidence-lock.json'],
        'stock': stock, 'suite_metadata': {'evidence_sha256': {**anchors, 'result.json': b.sha(directory/'result.json')}}}
    full_path = root/'full-report.json';full_path.write_text(json.dumps(full))
    return [directory, case_path, inner_path, outer_path, contract_path, review_path, freeze_path,
            full_path, b.sha(full_path), anchors['run-lock.json'], anchors['evidence-lock.json']]


class BoundedClockTests(unittest.TestCase):
    def test_original_geometry_theorem_prefix_and_scope_functions_unchanged(self):
        from experiments import bounded_entry_clock_v3 as old
        def functions(path):
            return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(Path(path).read_text()).body if isinstance(node, ast.FunctionDef)}
        before, after = functions(old.__file__), functions(b.__file__)
        for name in ('exact_vertices', 'points_inside', 'stock_region_corners', 'prepare', 'prefixes', 'main'):
            self.assertEqual(before[name], after[name], name)
        # Only the stability-authority version LABEL changes in evaluate;
        # all expressions, comparisons, loops and numeric predicates are exact.
        self.assertEqual(before['evaluate'].replace('Unchanged original stock/v6 report;', 'Unchanged original stock/v7 report;'), after['evaluate'])
        # Report authority is explicitly new v6, not silently reinterpreted v5.
        with tempfile.TemporaryDirectory() as tmp:
            args = locked_fixture(Path(tmp));value = json.loads(args[7].read_text())
            value['orchestration_version'] = 6;args[7].write_text(json.dumps(value));args[8] = b.sha(args[7])
            self.assertFalse(b.verify(*args)['file_integrity_verified'])
    def test_all_possible_prefixes_pass_but_noncollapsed_scope_stays_incomplete(self):
        values = fixture();before = copy.deepcopy(values)
        result = b.evaluate(*values)
        self.assertTrue(result['bounded_timing_floors_passed'], result)
        self.assertEqual(result['actual_first_entry_observed_step_bounds_inclusive'], [58, 60])
        self.assertEqual([r['end_boundary_step'] for r in result['every_possible_original_prefix']['prefixes']], [58, 59, 60])
        self.assertEqual(result['original_stock_entry_step'], 62)
        self.assertFalse(result['physical_entry_no_escape_complete'])
        self.assertFalse(result['supplemental_complete'])
        self.assertFalse(result['formal_house_accepted'])
        self.assertEqual(values, before)

    def test_collapsed_original_observed_bounds_complete_only_additive_scope(self):
        result = b.evaluate(*fixture(True))
        self.assertTrue(result['bounded_timing_floors_passed'], result)
        self.assertTrue(result['physical_entry_no_escape_complete'])
        self.assertTrue(result['supplemental_complete'])
        self.assertFalse(result['file_integrity_verified'])
        self.assertFalse(result['stability_assessed'])
        self.assertFalse(result['formal_house_accepted'])

    def test_earlier_prefix_can_fail_net_floor_while_original_later_window_passes(self):
        # A late stock entry can hide an early physical-window failure even
        # though its full original window meets ALL four unchanged floors.
        inactive = {3+5*i for i in range(12)}
        values = fixture(inactive=inactive);run, spec, case, stock = values[:4]
        for step in range(71, 91):
            sample = copy.deepcopy(run['samples'][-1]);sample.update(physics_steps=step,
                simulation_time_s=float(step), absolute_physics_step=3+step, absolute_simulation_time_s=.05+step)
            run['samples'].append(sample)
        run.update(actual_physics_steps=90, requested_physics_steps=90, simulation_time_s=90.)
        for sample in run['samples']:
            if 62 <= sample['physics_steps'] < 82: sample['positions']['/World/box'] = [.4, 0, 0]
        flags = stock['activity']['per_step_motion_flags']
        for step in range(63, 83):
            flags.append({'physics_step': step, 'simulation_time_s': float(step), 'active': True,
                          'body_ids': ['box'], 'stage_ids': ['transfer']})
        stock['activity']['metrics'].update(window_end_step=82, chain_duration_s=80.,
            net_effective_action_s=68., motion_occupancy=.85, maximum_idle_s=1.)
        stock['terminal']['first_whole_entry_step'] = 82
        condition = b.p.event_definitions(case)['terminal_entered']['conditions'][0]
        stock['terminal']['whole_sugar_inside_per_step'] = [b.m.condition_matches(condition, sample, run['initial_observation'], spec) for sample in run['samples']]
        result = b.evaluate(*values)
        self.assertFalse(result['bounded_timing_floors_passed'])
        first = result['every_possible_original_prefix']['prefixes'][0]
        self.assertFalse(first['checks']['minimum_net_effective_action'])

    def test_middle_prefix_occupancy_failure_cannot_hide_between_passing_ends(self):
        # Both bounding endpoints pass; an intermediate possible physical
        # entry fails occupancy. Checking just the endpoints would be wrong.
        values = fixture();case, stock = values[2:4]
        inactive = {5, 10, 15, 20, 25, 30, 35, 40, 45, 63}
        flags = [{'physics_step': step, 'simulation_time_s': float(step), 'active': step not in inactive,
                  'body_ids': ['box'] if step not in inactive else [], 'stage_ids': ['transfer'] if step not in inactive else []}
                 for step in range(3, 73)]
        stock['activity']['per_step_motion_flags'] = flags
        stock['activity']['metrics'].update(window_end_step=72, chain_duration_s=70.,
            net_effective_action_s=60., motion_occupancy=60/70, maximum_idle_s=1.)
        stock['terminal']['first_whole_entry_step'] = 72
        result = b.prefixes(stock, case, 62, 72, 1.)
        self.assertEqual(len(result['prefixes']), 11)
        self.assertTrue(result['prefixes'][0]['passed'])
        self.assertFalse(result['prefixes'][1]['checks']['minimum_motion_occupancy'])
        self.assertTrue(result['prefixes'][-1]['passed'])
        self.assertFalse(result['passed'])

    def test_missing_reordered_or_duplicated_original_masks_rejected(self):
        for change in ('missing', 'duplicate', 'reorder', 'false_credit', 'clock', 'metric'):
            values = fixture();stock = values[3];flags = stock['activity']['per_step_motion_flags']
            if change == 'missing': flags.pop(5)
            elif change == 'duplicate': flags[5] = copy.deepcopy(flags[4])
            elif change == 'reorder': flags[4], flags[5] = flags[5], flags[4]
            elif change == 'false_credit': flags[5]['body_ids'] = ['unregistered_spin']
            elif change == 'clock': flags[5]['simulation_time_s'] = 0
            else: stock['activity']['metrics']['net_effective_action_s'] += 1
            self.assertFalse(b.evaluate(*values)['supplemental_complete'])

    def test_original_terminal_masks_or_entry_cannot_be_replaced(self):
        values = fixture();values[3]['terminal']['whole_sugar_inside_per_step'][61] = False
        self.assertFalse(b.evaluate(*values)['bounded_timing_floors_passed'])
        values = fixture();values[3]['terminal']['first_whole_entry_step'] = 59
        self.assertFalse(b.evaluate(*values)['bounded_timing_floors_passed'])

    def test_early_escape_and_reentry_keep_earliest_inner_and_fail_complete_scope(self):
        values = fixture(True)
        values[0]['samples'][59]['positions']['/World/box'] = [2, 0, 0]
        condition = b.p.event_definitions(values[2])['terminal_entered']['conditions'][0]
        values[3]['terminal']['whole_sugar_inside_per_step'] = [b.m.condition_matches(condition, s, values[0]['initial_observation'], values[1]) for s in values[0]['samples']]
        result = b.evaluate(*values)
        self.assertEqual(result['inner_first_entry']['physics_steps'], 58)
        self.assertEqual(result['inner_escape_steps'], [60])
        self.assertFalse(result['supplemental_complete'])

    def test_stock_earlier_than_inner_is_rejected_without_extending_masks(self):
        values = fixture();values[2]['terminal']['interior_local'] = {'min': [-.9]*3, 'max': [.9]*3}
        result = b.evaluate(*values)
        self.assertFalse(result['bounded_timing_floors_passed'])
        self.assertIn('not an inward-certified subset', result['errors'][0]['reason'])

    def test_malformed_unbounded_or_unordered_static_regions_rejected(self):
        for kind in ('unbounded', 'infeasible', 'inner_outside', 'nonfinite', 'floor_loosened', 'transit_fake'):
            values = fixture();inner, outer, contract = values[4:]
            if kind == 'unbounded': outer['planes'] = outer['planes'][:4]
            elif kind == 'infeasible': outer['planes'][0]['offset_m'] = -10
            elif kind == 'inner_outside': inner['planes'] = cube_planes(2.)
            elif kind == 'nonfinite': outer['planes'][0]['normal_world'][0] = float('nan')
            elif kind == 'floor_loosened': contract['limits']['minimum_net_effective_action_s'] = 44
            else: contract['physical_entry_scope'] = 'assume_transit_success'
            self.assertFalse(b.evaluate(*values)['supplemental_complete'])

    def test_partial_clock_missing_corner_pose_and_initial_entry_rejected(self):
        for change in ('step', 'quaternion', 't0', 'inside_initial'):
            values = fixture()
            if change == 'step': values[0]['samples'].pop(5)
            elif change == 'quaternion': values[0]['samples'][5]['orientations_wxyz'] = {}
            elif change == 't0': values[0]['initialization_reset']['setters_during_task'] = True
            else:
                values[1]['objects']['box']['position'] = [0, 0, 0]
                values[4]['box_configuration_sha256'] = values[5]['box_configuration_sha256'] = b.canonical_sha(values[1]['objects']['box'])
                values[0]['initial_observation']['positions']['/World/box'] = [0, 0, 0]
            self.assertFalse(b.evaluate(*values)['supplemental_complete'])

    def test_tilted_noncentered_stock_region_uses_all_vertices(self):
        values = fixture();spec, case = values[1:3]
        spec['objects']['receiver']['orientation_wxyz'] = [math.cos(math.pi/8), 0, 0, math.sin(math.pi/8)]
        case['terminal']['interior_local'] = {'min': [.1, -.1, -.2], 'max': [.3, .1, .2]}
        points = b.stock_region_corners(spec, case)
        self.assertEqual(len(points), 8)
        self.assertAlmostEqual(max(float(p[0]) for p in points), .4/math.sqrt(2))
        scale = math.sqrt(1.00005)
        q = [scale*math.cos(math.pi/8), 0, 0, scale*math.sin(math.pi/8)]
        spec['objects']['receiver']['orientation_wxyz'] = q
        points = b.stock_region_corners(spec, case)
        recovered = [b.m.rotate([q[0], -q[1], -q[2], -q[3]], [float(v) for v in p]) for p in points]
        for axis in range(3):
            self.assertAlmostEqual(min(p[axis] for p in recovered), case['terminal']['interior_local']['min'][axis], places=13)
            self.assertAlmostEqual(max(p[axis] for p in recovered), case['terminal']['interior_local']['max'][axis], places=13)

    def test_file_level_full_locks_frozen_static_and_independent_report_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = locked_fixture(Path(tmp));result = b.verify(*args)
            self.assertTrue(result['file_integrity_verified'], result)
            self.assertTrue(result['supplemental_complete'], result)
            self.assertFalse(result['formal_house_accepted'])
            raw = json.loads(args[7].read_text());raw['stock']['activity']['per_step_motion_flags'][0]['active'] = False
            args[7].write_text(json.dumps(raw))
            result = b.verify(*args)
            self.assertFalse(result['file_integrity_verified'])

    def test_untrusted_new_report_hash_or_changed_static_inputs_rejected(self):
        for change in ('missing_anchor', 'changed_result', 'changed_source', 'late_freeze', 'review_false'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp);args = locked_fixture(root, review_valid=change != 'review_false')
                if change == 'missing_anchor': args[8] = None
                elif change == 'changed_result': (args[0]/'result.json').write_text('{}')
                elif change == 'changed_source': (root/'static-proof.txt').write_text('different static geometry')
                elif change == 'late_freeze':
                    value = json.loads(args[6].read_text());value['frozen_at_utc'] = '2022-01-01T00:00:00Z';args[6].write_text(json.dumps(value))
                result = b.verify(*args)
                self.assertFalse(result['file_integrity_verified'], result)
                self.assertFalse(result['supplemental_complete'])

    def test_new_cli_process_preserves_original_sealed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);args = locked_fixture(root)
            original = {str(path): b.sha(path) for path in args[0].rglob('*') if path.is_file()}
            names = ('run', 'case', 'inner', 'outer', 'contract', 'review', 'freeze', 'full-report',
                     'full-report-sha256', 'run-lock-sha256', 'evidence-lock-sha256')
            output = root/'additional-report.json'
            command = [sys.executable, b.__file__]
            for name, value in zip(names, args): command += ['--'+name, str(value)]
            command += ['--output', str(output)]
            process = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr+process.stdout)
            self.assertTrue(json.loads(output.read_text())['supplemental_complete'])
            self.assertEqual(original, {str(path): b.sha(path) for path in args[0].rglob('*') if path.is_file()})


if __name__ == '__main__': unittest.main()
