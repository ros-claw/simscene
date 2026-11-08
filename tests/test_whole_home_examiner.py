"""Synthetic CPU adversaries for the external examiner, never physics evidence."""
import copy
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
import weakref
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from experiments import whole_home_fidelity as f, whole_home_suite as suite


class FrozenV3KernelMixin:
    """Exercise unchanged v3 guards against their exact original core bytes.

    The current network and v4 examiner have their own regression tests. This
    does not bypass the v3 hash guard or substitute a new kernel's identity.
    """
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent/'fixtures/passive_network_v40.py'
        if hashlib.sha256(path.read_bytes()).hexdigest() != 'db21f1a4991fc67e3402f8a1de57da8419cb07ca5032ed91f06cdff89c73191e':
            raise AssertionError('legacy v3 test kernel fixture changed')
        spec = importlib.util.spec_from_file_location('simscene.verification._test_frozen_v40_network', path)
        cls.legacy_network = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.legacy_network)

    def setUp(self):
        context = patch.object(f, 'p', self.legacy_network)
        context.start()
        self.addCleanup(context.stop)


class TrackedPayload(dict):
    """Weak-referenceable synthetic per-step data; never a physics fixture."""


class TrackedSamples(list):
    pass


def ordering_fixture(root):
    """Only plumbing metadata; physics and case validators are mocked below."""
    spec = {'objects': {}}
    nominal = f.canonical_sha(spec)
    review = {'passed': True, 'scope': 'nominal_static_preflight', 'reviewer_role': 'independent_examiner', 'nominal_configuration_sha256': nominal,
              'network_case_sha256': 'f'*64, 'role_asset_proxy_review_passed': True, 'energy_force_catalog_passed': True}
    review_path = root/'review.json';review_path.write_text(json.dumps(review))
    contract = {'static_review_sha256': f.sha(review_path), 'nominal_configuration_sha256': nominal, 'network_case_sha256': 'f'*64,
                'cart': {}, 'cable': {}, 'bridge': {}, 'activity_groups': {}}
    contract_path = root/'contract.json';contract_path.write_text(json.dumps(contract))
    (root/'run-lock.json').write_text('{}')
    (root/'evidence-lock.json').write_text(json.dumps({'artifacts': {'result.json': {'sha256': 'e'*64}}}))
    return spec, contract_path, review_path


def cart_fixture():
    spec = {'objects': {n: {'kind': 'box', 'collision': True, 'dynamic': n != 'ground', 'position': [0, 0, 0]} for n in ('cart', 'wheel', 'ground')}}
    samples = []
    for step in range(11):
        samples.append({'physics_steps': step, 'absolute_physics_step': 3+step,
            'positions': {'/World/cart': [step*.1, 0, 0]}, 'orientations_wxyz': {'/World/cart': [1, 0, 0, 0]},
            'joints': {'axle': {'enabled': True, 'drive_present': False, 'angle_degrees': math.degrees(step)}},
            'contact_pairs': [] if step == 0 else [{'body_ids': ['wheel', 'ground'], 'actor_paths': ['/World/wheel', '/World/ground'], 'collider_paths': ['/World/wheel', '/World/ground'], 'count': 1, 'first_callback_absolute_physics_step': step+2, 'last_callback_absolute_physics_step': step+2}]})
    joint = {'path': '/World/axle', 'type': 'PhysicsRevoluteJoint', 'body0': ['/World/cart'], 'body1': ['/World/wheel'], 'enabled': True, 'drives': [], 'drive_attributes': []}
    run = {'initial_observation': samples[0], 'samples': samples[1:], 'mechanism_configuration': {'joints': [joint]}}
    report = {'events': {'starts': {'onset_step': 0}, 'ends': {'onset_step': 10}}}
    cfg = {'body_id': 'cart', 'phase': {'start_event': 'starts', 'end_event': 'ends'}, 'direction_world': [1, 0, 0], 'minimum_progress_m': .5,
           'minimum_progress_speed_m_s': .01, 'minimum_grounded_rotation_distance_fraction': .9,
           'wheels': [{'body_id': 'wheel', 'joint_id': 'axle', 'carrier_body_id': 'cart', 'support_body_ids': ['ground'], 'radius_m': .1, 'spin_sign': 1, 'minimum_rotation_degrees': 1, 'minimum_signed_angular_speed_degrees_s': 1}]}
    return run, spec, report, cfg


class WholeHomeFidelityTest(FrozenV3KernelMixin, unittest.TestCase):
    def test_single_wrapper_finishes_stock_before_loading_outer_raw_and_releases_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);spec, contract, review = ordering_fixture(root)
            calls, references = [], []
            def stock(*args, **kwargs):
                self.assertEqual(calls, [])
                calls.append('stock_complete')
                return {'passed': True, 'contact_journal': {'passed': True, 'records': []}, 'terminal': {'stable_onset_step': 10, 'stable_confirmation_step': 130}}
            def read(*args, **kwargs):
                self.assertEqual(calls, ['stock_complete'])
                calls.append('outer_raw_read')
                samples = TrackedSamples([{'synthetic_sample': n} for n in range(1000)])
                raw = TrackedPayload({'samples': samples, 'videos': {}, 'run_zero_absolute_physics_step': 3, 'mechanism_configuration': {'geometry_settings': {'policy': False}}})
                references.extend((weakref.ref(raw), weakref.ref(samples)))
                return {'passed': True, 'root': root, 'run': raw, 'spec': spec, 'case': {}, 'lock': {'physics_dt_s': 1/60}, 'integrity': {'case_sha256': 'f'*64}}
            with ExitStack() as stack:
                stack.enter_context(patch.object(f.p, 'verify_run', new=stock))
                stack.enter_context(patch.object(f.p, '_read_locked', new=read))
                stack.enter_context(patch.object(f, 'validate_contract', return_value=True))
                stack.enter_context(patch.object(f, 'sealed_identities', new=lambda data: {}))
                for name in ('static_stage_catalog', 'mass_catalog', 'cart_rolling', 'cable_no_bypass', 'bridge_support'):
                    stack.enter_context(patch.object(f, name, new=lambda *args, **kwargs: {'passed': True}))
                stack.enter_context(patch.object(f, 'activity_breakdown', return_value={}))
                report = f.verify_one(root, contract, review)
            self.assertTrue(report['passed'])
            self.assertEqual(calls, ['stock_complete', 'outer_raw_read'])
            self.assertTrue(all(reference() is None for reference in references), 'returned metadata retained expanded raw samples')
            self.assertEqual(report['suite_metadata']['evidence_sha256']['result.json'], 'e'*64)

    def test_suite_metadata_size_does_not_grow_with_raw_step_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);spec, _, _ = ordering_fixture(root)
            data = {'passed': True, 'root': root, 'spec': spec, 'case': {'frozen': True}, 'lock': {'seed': 42}, 'integrity': {'case_sha256': 'f'*64},
                    'run': {'samples': [{'sample_marker': True}], 'run_zero_absolute_physics_step': 3, 'videos': {}, 'mechanism_configuration': {'geometry_settings': {'policy': False}}}}
            first = f.suite_metadata(data, {})
            data['run']['samples'] = [{'sample_marker': n} for n in range(20000)]
            data['run']['contact_pairs'] = list(range(20000))
            second = f.suite_metadata(data, {})
            self.assertEqual(first, second)
            self.assertNotIn('sample_marker', json.dumps(second))
            self.assertNotIn('run', second)
            data['run']['mechanism_configuration']['geometry_settings']['policy'] = True
            self.assertFalse(second['geometry_settings']['policy'])

    def test_reordered_read_cannot_switch_locked_evidence_after_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);_, contract, review = ordering_fixture(root)
            def stock(*args, **kwargs):
                (root/'evidence-lock.json').write_text('{"changed_after_stock":true}')
                return {'passed': True}
            with patch.object(f.p, 'verify_run', new=stock), patch.object(f.p, '_read_locked', side_effect=AssertionError('must reject changed locks before raw read')):
                with self.assertRaisesRegex(ValueError, 'locks changed during stock'):
                    f.verify_one(root, contract, review)

    def test_cart_requires_real_signed_rotation_and_same_interval_support(self):
        run, spec, report, cfg = cart_fixture()
        measured = f.cart_rolling(run, spec, report, cfg, .1)
        self.assertTrue(measured['passed'])
        self.assertAlmostEqual(measured['wheels']['wheel']['radius_angle_to_net_progress_ratio'], 1)
        for fault in ('static_wheels', 'backward_wheels', 'no_callbacks', 'spin_after_travel', 'vertical_bob', 'backward_cart'):
            with self.subTest(fault=fault):
                bad = copy.deepcopy(run)
                for sample in [bad['initial_observation'], *bad['samples']]:
                    step = sample['physics_steps']
                    if fault == 'static_wheels':sample['joints']['axle']['angle_degrees'] = 0
                    elif fault == 'backward_wheels':sample['joints']['axle']['angle_degrees'] *= -1
                    elif fault == 'no_callbacks':sample['contact_pairs'] = []
                    elif fault == 'spin_after_travel':sample['joints']['axle']['angle_degrees'] = 0 if step < 10 else math.degrees(10)
                    elif fault == 'vertical_bob':sample['positions']['/World/cart'] = [0, 0, step*.1]
                    else:sample['positions']['/World/cart'][0] *= -1
                bad['contact_counts'] = {'wheel|/World/ground|': {'count': 999, 'first_physics_step': 1, 'last_physics_step': 10}}
                self.assertFalse(f.cart_rolling(bad, spec, report, cfg, .1)['passed'])

    def test_cart_rejects_missing_steps_self_support_duplicates_and_drive(self):
        for fault in ('missing', 'self_contact', 'duplicate_wheel', 'drive', 'wrong_joint', 'nonunit'):
            with self.subTest(fault=fault):
                run, spec, report, cfg = cart_fixture()
                if fault == 'missing':run['samples'].pop(4)
                elif fault == 'self_contact':cfg['wheels'][0]['support_body_ids'] = ['wheel']
                elif fault == 'duplicate_wheel':cfg['wheels'].append(copy.deepcopy(cfg['wheels'][0]))
                elif fault == 'drive':run['mechanism_configuration']['joints'][0]['drives'] = ['angular']
                elif fault == 'wrong_joint':run['mechanism_configuration']['joints'][0]['body0'] = ['/World/ground']
                else:cfg['direction_world'] = [1, 0, 1]
                with self.assertRaises(ValueError):f.cart_rolling(run, spec, report, cfg, .1)

    def test_cable_cut_is_sole_dynamic_constraint_path_and_discloses_planar_extras(self):
        spec = {'objects': {n: {'dynamic': True} for n in ('weight', 'a', 'b', 'drawer')}}
        def joint(name, first, second):
            return {'path': '/World/'+name, 'body0': ['/World/'+first], 'body1': ['/World/'+second], 'enabled': True, 'drives': [], 'drive_attributes': []}
        run = {'mechanism_configuration': {'joints': [joint('top', 'weight', 'a'), joint('interior', 'a', 'b'), joint('aux', 'a', 'b'), joint('load', 'b', 'drawer')]}}
        cfg = {'load_body_id': 'drawer', 'weight_body_id': 'weight', 'load_attachment_joint_id': 'load', 'additional_passive_joint_ids': ['aux'], 'model_description': 'Planar articulated cable; passive interior constraint, no auxiliary load connection.'}
        self.assertTrue(f.cable_no_bypass(run, spec, cfg)['passed'])
        bypass = copy.deepcopy(run);bypass['mechanism_configuration']['joints'].append(joint('hidden_bypass', 'weight', 'drawer'))
        self.assertFalse(f.cable_no_bypass(bypass, spec, cfg)['passed'])
        bad = copy.deepcopy(cfg);bad['additional_passive_joint_ids'] = ['load']
        with self.assertRaises(ValueError):f.cable_no_bypass(run, spec, bad)

    def test_bridge_requires_complete_mechanism_and_actual_phase_contact(self):
        run, spec, report, _ = cart_fixture()
        case = {'mechanism_cases': {'bridge': {'mechanism': 'wheel_door_bridge', 'roles': {'door': 'ground', 'rollingpin': 'wheel'}}}}
        report['mechanism_cases'] = {'bridge': {'report': {'passed': True}}}
        cfg = {'mechanism_case_key': 'bridge', 'phase': {'start_event': 'starts', 'end_event': 'ends'}, 'minimum_support_callback_updates': 2}
        self.assertTrue(f.bridge_support(run, spec, case, report, cfg)['passed'])
        report['mechanism_cases']['bridge']['report']['passed'] = False
        self.assertFalse(f.bridge_support(run, spec, case, report, cfg)['passed'])
        report['mechanism_cases']['bridge']['report']['passed'] = True
        for sample in run['samples']:sample['contact_pairs'] = []
        run['contact_counts'] = {'wheel|/World/ground|': {'count': 1000}}
        self.assertFalse(f.bridge_support(run, spec, case, report, cfg)['passed'])

    def test_120_samples_do_not_cover_two_full_seconds(self):
        case = {'profile': 'P3', 'terminal': {'hold_steps': 120}, 'required_controls': ['no_trigger', 'broken_rope', 'locked_door'], 'mechanism_cases': {k: {'mechanism': k} for k in ('rope_drawer', 'wheel_door_bridge', 'spoon_sugar')}}
        with patch.object(f.p, 'validate_case'):
            with self.assertRaises(ValueError):f.validate_floors(case, 1/60)
            case['terminal']['hold_steps'] = 121
            self.assertTrue(f.validate_floors(case, 1/60))

    def test_csv_exports_exact_half_open_role_union_and_rejects_missing(self):
        roles = [['ball', 'drawer'], ['ball'], [], [], ['drawer']]
        report = {'activity': {'metrics': {'window_start_step': 10, 'window_end_step': 15, 'chain_duration_s': 2.5, 'net_effective_action_s': 1.5, 'motion_occupancy': .6, 'maximum_idle_s': 1.}, 'per_step_motion_flags': [{'physics_step': 11+i, 'body_ids': values, 'active': bool(values)} for i, values in enumerate(roles)]}}
        case = {'activity': {'stages': [{'bodies': [{'id': 'ball'}, {'id': 'drawer'}]}]}}
        clock = Path(__file__).parent/'fixtures/score_motion_clock.py'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'clock.csv';record = f.export_motion_csv(report, case, output, clock, .5)
            self.assertEqual(record['metrics']['active_step_intervals'], 3)
            self.assertEqual(output.read_text().splitlines()[1], '10,1,1')
            with self.assertRaises(ValueError):f.export_motion_csv(report, case, output, clock, .5)
            report['activity']['per_step_motion_flags'].pop(2)
            with self.assertRaises(ValueError):f.export_motion_csv(report, case, Path(tmp)/'bad.csv', clock, .5)

    def test_mass_readback_requires_complete_positive_cooked_inertia(self):
        spec = {'objects': {'body': {'dynamic': True}}}
        mass = {'mass_kg': .1, 'center_of_mass_local_m': [0, 0, 0], 'principal_axes_local_wxyz': [1, 0, 0, 0], 'inertia_at_com_in_prim_axes_kg_m2': [[1, 0, 0], [0, 2, 0], [0, 0, 3]], 'observed_at_physics_step': 0, 'source': 'PhysX tensor readback synthetic fixture'}
        run = {'actual_physics_steps': 10, 'mechanism_configuration': {'mass_properties_by_prim_path': {'/World/body': mass}}}
        self.assertTrue(f.mass_catalog(run, spec)['passed'])
        mass['inertia_at_com_in_prim_axes_kg_m2'][2][2] = -3
        self.assertFalse(f.mass_catalog(run, spec)['passed'])
        mass['inertia_at_com_in_prim_axes_kg_m2'][2][2] = 3
        mass['source'] = 'authored guess'
        self.assertFalse(f.mass_catalog(run, spec)['passed'])

    def test_act_totals_are_unions_and_cannot_be_summed_as_chain_seconds(self):
        case = {'activity': {'stages': [{'id': 'a', 'bodies': [{'id': 'ball'}]}, {'id': 'b', 'bodies': [{'id': 'drawer'}]}]}}
        report = {'activity': {'per_step_motion_flags': [{'active': True, 'body_ids': ['ball', 'drawer'], 'stage_ids': ['a', 'b']}, {'active': True, 'body_ids': ['ball'], 'stage_ids': ['a']}]}}
        values = f.activity_breakdown(report, case, {'study': ['a'], 'kitchen': ['b']}, .1)
        self.assertAlmostEqual(values['act_union_effective_seconds']['study'], .2)
        self.assertAlmostEqual(values['act_union_effective_seconds']['kitchen'], .1)
        with self.assertRaises(ValueError):f.activity_breakdown(report, case, {'same': ['a', 'b'], 'duplicate': ['b']}, .1)

    def test_static_stage_inventory_rejects_drive_kinematic_and_force_attributes(self):
        from pxr import Usd, UsdGeom, UsdPhysics, Sdf, Gf
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'synthetic.usda'
            stage = Usd.Stage.CreateNew(str(path));prim = UsdGeom.Xform.Define(stage, '/Body').GetPrim()
            body = UsdPhysics.RigidBodyAPI.Apply(prim);body.CreateKinematicEnabledAttr(False)
            joint = UsdPhysics.RevoluteJoint.Define(stage, '/Axle')
            stage.GetRootLayer().Save()
            self.assertTrue(f.static_stage_catalog(path)['passed'])
            UsdPhysics.DriveAPI.Apply(joint.GetPrim(), 'angular').CreateMaxForceAttr(1)
            stage.GetRootLayer().Save()
            self.assertFalse(f.static_stage_catalog(path)['passed'])
            stage.RemovePrim('/Axle');body.CreateKinematicEnabledAttr(True);stage.GetRootLayer().Save()
            self.assertFalse(f.static_stage_catalog(path)['passed'])
            body.CreateKinematicEnabledAttr(False)
            prim.CreateAttribute('physxForce:force', Sdf.ValueTypeNames.Float3).Set(Gf.Vec3f(0, 0, 0));stage.GetRootLayer().Save()
            self.assertFalse(f.static_stage_catalog(path)['passed'])


class WholeHomeSuiteTest(FrozenV3KernelMixin, unittest.TestCase):
    def test_complete_reports_stream_to_disk_without_a_report_sized_dumps_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = {'passed': False, 'stock': {'passed': False, 'checks': {'kept_failure': False}, 'all_original_step_flags': list(range(10000))}}
            path = Path(tmp)/'complete.json'
            with patch.object(suite.json, 'dumps', side_effect=AssertionError('do not create a report-sized JSON string')):
                summary = suite.save_run_report(report, path)
            self.assertFalse(summary['passed'])
            self.assertEqual(json.loads(path.read_text()), report)
            self.assertEqual(summary['individual_report']['sha256'], f.sha(path))
            self.assertLess(len(json.dumps(summary)), 2000)
            with self.assertRaises(FileExistsError):suite.save_run_report(report, path)

    def variant_fixture(self):
        base = {'objects': {'cup': {'kind': 'compound', 'collision': True, 'position': [0, 0, 0]}, 'shelf': {'kind': 'box', 'collision': True, 'size': [1, 1, .1]}}}
        other = copy.deepcopy(base);other['objects']['cup']['position'][0] += .2;other['objects']['shelf']['size'][0] = 1.2
        case = {'terminal': {'receiver_id': 'cup'}, 'activity': {'limits': {'minimum_net_effective_action_s': 45}}}
        declaration = {'cup_body_id': 'cup', 'cup_delta_world_m': [.2, 0, 0], 'additional_spec_changes': [{'path': ['objects', 'shelf', 'size', 0], 'before': 1, 'after': 1.2}], 'case_geometry_changes': []}
        return base, other, case, declaration

    def test_variant_needs_full_cup_shift_plus_exact_local_change(self):
        base, other, case, declaration = self.variant_fixture()
        self.assertTrue(suite.compare_variant(base, other, case, case, declaration)['passed'])
        other['objects']['shelf']['mass_kg'] = 1
        self.assertFalse(suite.compare_variant(base, other, case, case, declaration)['passed'])
        declaration['additional_spec_changes'] = []
        with self.assertRaises(ValueError):suite.compare_variant(base, other, case, case, declaration)

    def test_variant_cannot_relax_timing_or_smuggle_physics_patch(self):
        base, other, case, declaration = self.variant_fixture()
        weaker = copy.deepcopy(case);weaker['activity']['limits']['minimum_net_effective_action_s'] = 44
        self.assertFalse(suite.compare_variant(base, other, case, weaker, declaration)['passed'])
        declaration['case_geometry_changes'] = [{'path': ['activity', 'limits', 'minimum_net_effective_action_s'], 'before': 45, 'after': 44}]
        with self.assertRaises(ValueError):suite.compare_variant(base, other, case, weaker, declaration)
        declaration['case_geometry_changes'] = []
        declaration['additional_spec_changes'][0]['path'] = ['objects', 'shelf', 'physics', 'linear_damping']
        with self.assertRaises(ValueError):suite.compare_variant(base, other, case, case, declaration)

    def test_repeat_selection_cannot_skip_a_failed_formal_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ('first', 'failure', 'second', 'third')
            for index, name in enumerate(names):
                path = root/name;path.mkdir()
                (path/'run-lock.json').write_text(json.dumps({'created_at_utc': '2026-01-01T00:00:0'+str(index)+'Z'}))
            ledger = [{'kind': 'main_positive', 'run_directory': str(root/name)} for name in names]
            self.assertFalse(suite.consecutive_three([root/n for n in ('first', 'second', 'third')], ledger))
            self.assertTrue(suite.consecutive_three([root/n for n in ('failure', 'second', 'third')], ledger))
            reordered = [ledger[1], ledger[0], ledger[2], ledger[3]]
            self.assertFalse(suite.consecutive_three([root/n for n in ('first', 'second', 'third')], reordered))
            # A chronologically valid selection still needs all measured passes.

    def test_attempt_inventory_keeps_unsealed_failures_and_rejects_omission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, name in enumerate(('ok', 'failed')):
                directory = root/name;directory.mkdir()
                (directory/'run-lock.json').write_text(json.dumps({'run_id': name, 'acceptance_case_sha256': 'f'*64, 'created_at_utc': '2026-01-01T00:00:0'+str(index)+'Z'}))
                (directory/'spec.json').write_text('{}')
            ledger = [{'kind': 'main_positive', 'run_directory': str(root/name)} for name in ('ok', 'failed')]
            self.assertTrue(suite.check_attempt_inventory(ledger, [root], {'f'*64})['passed'])
            with self.assertRaises(ValueError):suite.check_attempt_inventory(ledger[:1], [root], {'f'*64})
            with self.assertRaises(ValueError):suite.check_attempt_inventory(list(reversed(ledger)), [root], {'f'*64})

    def test_freeze_rejects_post_snapshot_or_changed_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);contract = root/'contract.json';review = root/'review.json';freeze = root/'freeze.json'
            contract.write_text('{}');review.write_text('{}')
            record = {'schema': 'simscene.whole_home_examiner_freeze.v1', 'frozen_at_utc': '2026-01-01T00:00:00Z', 'files_sha256': {str(Path(file).resolve()): f.sha(file) for file in (contract, review, f.__file__, suite.__file__)}}
            freeze.write_text(json.dumps(record));(root/'run-lock.json').write_text(json.dumps({'created_at_utc': '2026-01-01T00:00:01Z'}))
            self.assertTrue(suite.verify_freeze(freeze, contract, review, root)['passed'])
            (root/'run-lock.json').write_text(json.dumps({'created_at_utc': '2025-12-31T23:59:59Z'}))
            with self.assertRaises(ValueError):suite.verify_freeze(freeze, contract, review, root)
            contract.write_text('{"changed":true}')
            with self.assertRaises(ValueError):suite.verify_freeze(freeze, contract, review, root)

    def test_native_camera_role_and_absolute_boundaries_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cameras = {'fixed': 'master', 'tracking': 'travelling'}
            videos = {}
            for name in cameras.values():
                frames = root/(name+'.frames.jsonl')
                frames.write_text(''.join(json.dumps({'physics_step': step, 'render_context': {'absolute_physics_step': step+3}})+'\n' for step in (2, 4)))
                videos[name] = {'path': str(root/(name+'.mp4')), 'native_resolution': [1920, 1080], 'fps': 30, 'timebase': 'simulation', 'frame_manifest': str(frames)}
            spec = {'objects': {'master': {'kind': 'camera'}, 'travelling': {'kind': 'camera', 'camera_path': {'synthetic': True}}}}
            run = {'run_zero_absolute_physics_step': 3, 'videos': videos}
            (root/'spec.json').write_text(json.dumps(spec))
            (root/'result.json').write_text(json.dumps(run))
            stock = {'activity': {'metrics': {'window_start_step': 2}}, 'terminal': {'stable_confirmation_step': 4}}
            with patch('simscene.video_tools.inspect', return_value={'issues': [], 'simulation_timeline': {'passed': True}}) as inspect:
                self.assertTrue(suite.verify_native(root, cameras, stock)['passed'])
                self.assertEqual(inspect.call_args.kwargs['record'], videos['travelling'])
                with patch.object(suite, '_load', side_effect=AssertionError('suite native must not reload the expanded run')):
                    self.assertTrue(suite.verify_native(root, cameras, stock, _metadata={'run': run, 'spec': spec})['passed'])
                (root/'travelling.frames.jsonl').write_text(json.dumps({'physics_step': 2, 'render_context': {'absolute_physics_step': 999}})+'\n')
                self.assertFalse(suite.verify_native(root, cameras, stock)['passed'])

    def test_individual_passes_cannot_hide_mismatched_full_suite_runtime(self):
        # This exercises orchestration with explicitly mocked individual
        # physics reports. It is not synthetic telemetry accepted as physics.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);runs = root/'original/state/runs';runs.mkdir(parents=True)
            names = ['p1', 'p2', 'p3', 'no_trigger', 'broken_rope', 'locked_door', 'variant']
            paths = [runs/name for name in names]+[root/'exported/state/runs/replay']
            for index, path in enumerate(paths):
                path.mkdir(parents=True)
                (path/'run-lock.json').write_text(json.dumps({'created_at_utc': '2026-01-01T00:00:0'+str(index)+'Z'}))
            base, variant_spec, case, declaration = self.variant_fixture()
            declaration_path = root/'variant.json';declaration_path.write_text(json.dumps(declaration))
            ledger = [{'kind': 'main_positive' if i < 3 else names[i] if i < 7 else 'replay', 'run_directory': str(path)} for i, path in enumerate(paths)]
            ledger_path = root/'ledger.json';ledger_path.write_text(json.dumps(ledger))
            proof = root/'export-proof.txt';proof.write_text('independently reviewed export fixture')
            export_path = root/'export-preflight.json';export_path.write_text(json.dumps({'passed': True, 'scope': 'independent_editable_export_preflight', 'source_run_directory': str(paths[0]), 'project_directory': str(root/'exported'), 'files_sha256': {str(proof): f.sha(proof)}}))
            data = {str(path.resolve()): {'passed': True, 'root': str(path), 'canonical_spec': copy.deepcopy(variant_spec if path.name == 'variant' else base), 'case': case,
                    'lock': {key: 'same frozen value' for key in f.m.PAIRED_MANIFEST_FIELDS}, 'geometry_settings': {'policy': False}, 'integrity': {'case_sha256': 'f'*64}, 'native_metadata': {}} for path in paths}
            for value in data.values():value['lock']['physics_dt_s'] = 1/60
            manifest = {'schema': suite.SCHEMA, 'software_freeze_path': 'unused-by-mock', 'contract_path': 'contract.json', 'static_review_path': 'review.json', 'freeze_path': 'freeze.json',
                'positive_runs': [str(path) for path in paths[:3]], 'controls': {name: str(paths[i]) for i, name in enumerate(names) if 3 <= i < 6},
                'variant': {'run_directory': str(paths[6]), 'contract_path': 'variant-contract.json', 'static_review_path': 'variant-review.json', 'freeze_path': 'variant-freeze.json', 'declaration_path': str(declaration_path)},
                'replay': {'run_directory': str(paths[7]), 'export_preflight_path': str(export_path)}, 'attempt_ledger_path': str(ledger_path), 'formal_runs_roots': [str(runs), str(paths[7].parent)],
                'native_cameras': {'fixed': 'master', 'tracking': 'moving'}, 'native_positive_index': 0, 'clock_directory': str(root/'clocks'), 'provided_clock_path': 'unused-by-mock'}
            with ExitStack() as stack:
                live = [];clock_calls = []
                def one(directory, *args, **kwargs):
                    self.assertTrue(all(value() is None for value in live), 'previous expanded report survived into next run')
                    payload = TrackedPayload({'synthetic_per_step_values': list(range(2000))})
                    live.append(weakref.ref(payload))
                    return {'passed': True, 'stock': {'passed': True, 'complete_per_step_evidence': payload}, 'suite_metadata': data[str(Path(directory).resolve())]}
                def clock(stock, *args, **kwargs):
                    self.assertEqual(len(stock['complete_per_step_evidence']['synthetic_per_step_values']), 2000)
                    clock_calls.append(True)
                    return {'metrics': {'span_s': 50}}
                stack.enter_context(patch.object(f, 'assert_software_freeze', return_value={'passed': True}))
                stack.enter_context(patch.object(suite, 'verify_freeze', return_value={'passed': True}))
                stack.enter_context(patch.object(f, 'verify_one', side_effect=one))
                stack.enter_context(patch.object(f.p, '_read_locked', side_effect=AssertionError('orchestration must not retain raw reads')))
                stack.enter_context(patch.object(suite, 'check_attempt_inventory', return_value={'passed': True}))
                # Mock call histories would themselves retain stock arguments;
                # plain replacements keep this retention test honest.
                stack.enter_context(patch.object(suite, 'verify_native', new=lambda *args, **kwargs: {'passed': True}))
                stack.enter_context(patch.object(f, 'export_motion_csv', new=clock))
                accepted = suite.verify_suite(manifest)
                self.assertTrue(accepted['passed'])
                self.assertEqual(len(clock_calls), 5)
                self.assertTrue(all(value() is None for value in live))
                self.assertNotIn('complete_per_step_evidence', accepted['runs']['positive_1']['stock'])
                saved = accepted['runs']['positive_1']['individual_report']
                self.assertEqual(f.sha(saved['path']), saved['sha256'])
                self.assertEqual(len(json.loads(Path(saved['path']).read_text())['stock']['complete_per_step_evidence']['synthetic_per_step_values']), 2000)
                data[str(paths[2].resolve())]['lock']['gpu_selection'] = {'simscene_gpu': 'different device'}
                manifest['clock_directory'] = str(root/'clocks-second-check')
                report = suite.verify_suite(manifest)
                self.assertFalse(report['passed'])
                self.assertFalse(report['checks']['all13_runtime_fields_match'])
                self.assertTrue(report['checks']['all_original_physics_and_fidelity_pass'])


if __name__ == '__main__':
    unittest.main()
