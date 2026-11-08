"""Synthetic custody records only; no simulated/real P3 acceptance evidence.

The physical authority/contract validator is deliberately mocked for the tiny
bookkeeping fixture. Real locked bytes, whole-package snapshot checks, acquired
asset closures, original report serialization and original CSV-mask checks run.
Production has no bypass parameter. The fixture fails real P3 validation.
"""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import weakref

from experiments import retained_report_integrity as r
from experiments import whole_home_fidelity_v7 as f, whole_home_suite_v7 as suite
from simscene.run_integrity import verify as inputs
from simscene.evidence_integrity import verify as outputs, seal
from simscene.jobs import _snapshot_cached_assets
from test_composed_event_mechanisms import fixture as event_fixture
from test_passive_network import seal_fixture
from test_asset_snapshot_comparison import cache

ROOT = Path(__file__).resolve().parents[1]
SOFTWARE = Path('/code/rosclaw/simscene/evidence/whole-room-sugar-20261031/generic-freeze/v41-software.json')
STARTED = '2030-01-01T00:00:00Z'

def original_v41_fixture_available():
    # These archive-specific tests intentionally exercise the REAL old byte
    # authority, not a newly synthesized package pretending to be v41.
    if not SOFTWARE.is_file():return False
    record=json.loads(SOFTWARE.read_text())
    return (Path(record['package'])/'server/vendor/simscene').is_dir() and (Path(record['checkout_root'])/'experiments/whole_home_fidelity_v7.py').is_file()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def fixture(base, mode='positive', reference=None, assets=False):
    run, spec, case, definitions, stock = event_fixture()
    for sample in run['samples']:
        sample['simulation_time_s'] = float(sample['physics_steps'])
        sample['absolute_simulation_time_s'] = .05+sample['physics_steps']
    run['simulation_time_s'] = 100.
    case.update(profile='P3', mechanism_cases={}, rope_body_ids=[], household_categories={},
        tiles={'ids': ['tile']}, activity={'stages': [{'id': 'transfer', 'bodies': [{'id': 'sugar'}]}],
            'limits': {'minimum_chain_duration_s': 50, 'minimum_net_effective_action_s': 45, 'minimum_motion_occupancy': .85, 'maximum_idle_s': 2}})
    report_composed = f.composed.evaluate(run, spec, case, definitions, stock, 1.)
    assert report_composed['passed']
    case['controls'] = {'no_trigger': {'downstream_body_ids': ['tile']}}
    case['terminal'].update(body_id='sugar', receiver_id='cup')
    directory = base/mode;directory.mkdir()
    records = None
    if assets:
        package = cache(base)
        spec['objects']['visual'] = {'kind': 'asset', 'asset_path': str(package/'model.usda'),
            'asset_physics': 'visual_only', 'rigid_attachment': {'body': 'spoon'}}
        records = _snapshot_cached_assets(spec, directory)
    if mode != 'positive': spec['objects'].pop('trigger')
    seal_fixture(directory, run, spec, case, reference['root']/'python.sh' if reference else None)
    # This fixture explicitly exercises the retained v41 authority below.
    # Its worker must therefore be the frozen v41 package, even when the
    # current development checkout has newer generic capabilities.
    software = json.loads(SOFTWARE.read_text())
    frozen_worker = Path(software['package'])/'server/vendor/simscene'
    shutil.rmtree(directory/'runtime/simscene')
    shutil.copytree(frozen_worker, directory/'runtime/simscene', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    lock = json.loads((directory/'run-lock.json').read_text())
    prefix = 'server/vendor/simscene/'
    lock['worker_code_sha256'] = {name[len(prefix):]:sha for name, sha in software['installed_package_files_sha256'].items() if name.startswith(prefix)}
    lock.update(physics_dt_s=1., created_at_utc='2029-01-01T00:00:00Z', run_id=directory.name)
    if records is not None:
        dump(directory/'asset-lock.json', records);lock['asset_lock_sha256'] = f.sha(directory/'asset-lock.json')
    dump(directory/'run-lock.json', lock);seal(directory)
    config = f.sealed_identities({'passed': True, 'root': directory, 'spec': spec, 'lock': lock})
    canonical = f.canonical_spec(spec, config)
    casepath = base/(mode+'-case.json');shutil.copyfile(directory/'acceptance-case.json', casepath)
    reviewpath = base/(mode+'-review.json')
    nominal = reference['contract']['nominal_configuration_sha256'] if reference else f.canonical_sha(canonical)
    dump(reviewpath, {'passed': True, 'network_case_sha256': f.sha(casepath), 'nominal_configuration_sha256': nominal})
    contract = {'schema': f.SCHEMA, 'network_case_sha256': f.sha(casepath), 'static_review_sha256': f.sha(reviewpath),
        'nominal_configuration_sha256': nominal, 'physics_dt_s': 1., 'cart': {'wheels': []}, 'composed_mechanisms': definitions}
    contractpath = base/(mode+'-contract.json');dump(contractpath, contract)
    freezepath = base/(mode+'-freeze.json')
    freeze = {'schema': 'simscene.whole_home_examiner_freeze.v1', 'frozen_at_utc': '2028-01-01T00:00:00Z',
        'files_sha256': {str(path.resolve()): f.sha(path) for path in (contractpath, reviewpath, casepath, Path(f.__file__), Path(suite.__file__), Path(f.composed.__file__))}}
    dump(freezepath, freeze)
    integrity = {'input_integrity': inputs(directory), 'output_integrity': outputs(directory), 'case_pinned_to_run': True,
        'worker_snapshot_pinned': True, 'case_sha256': f.sha(casepath), 'checker_sha256': f.KERNEL_SHA256['passive_network'], 'reused_mechanism_sha256': f.KERNEL_SHA256['mechanism']}
    assert integrity['input_integrity']['passed'] and integrity['output_integrity']['passed']
    flags = [{'physics_step': step, 'simulation_time_s': float(step), 'active': True, 'body_ids': ['sugar'], 'stage_ids': ['transfer']} for step in range(11, 69)]
    stock.update(mode=mode, profile='P3', checks={'synthetic_original_full_decision': True}, timeline={'passed': True}, strict_initial_state={'passed': True},
        terminal={'passed': True, 'first_whole_entry_step': 68, 'whole_sugar_inside_per_step': [i >= 68 for i in range(1, 101)]},
        activity={'passed': True, 'metrics': {'window_start_step': 10, 'window_end_step': 68, 'chain_duration_s': 58., 'net_effective_action_s': 58., 'motion_occupancy': 1., 'maximum_idle_s': 0.}, 'per_step_motion_flags': flags},
        events={name: {'onset_step': 20} for name in f.p.event_definitions(case)},
        handoffs={v['id']: {'passed': True} for v in case['handoffs']}, tiles={'tile': {'counted': True}},
        household_categories={}, actual_tipped_tile_count=1, actual_final_tipped_tile_count=1, **integrity)
    if mode != 'positive':
        stock.update(reference_positive_passed=True, same_frozen_case_as_reference=True, paired_runtime_configuration_matches=True, paired_geometry_settings_match=True)
        stock['checks'].update(only_frozen_isolated_scene_change=True, control_downstream_remains_quiet=True)
    metadata = {'passed': True, 'root': str(directory), 'lock': lock, 'case': case, 'canonical_spec': canonical,
        'verified_asset_identities': config, 'geometry_settings': None, 'integrity': integrity,
        'evidence_sha256': {name: f.sha(directory/name) for name in ('run-lock.json', 'evidence-lock.json', 'result.json')},
        'native_metadata': {'run': {'videos': {}, 'run_zero_absolute_physics_step': 3}, 'spec': {'objects': {}}}}
    massnames = {f.m.path(n) for n, obj in spec['objects'].items() if obj.get('dynamic')}
    report = {'passed': True, 'formal_house_accepted': False, 'mode': mode, 'run_directory': str(directory),
        'run_lock_sha256': f.sha(directory/'run-lock.json'), 'evidence_lock_sha256': f.sha(directory/'evidence-lock.json'),
        'supplemental_code_sha256': r.PINS['fidelity'], 'supplemental_contract_sha256': f.sha(contractpath), 'orchestration_version': 7,
        'scope': 'SYNTHETIC TRUSTED-CUSTODY UNIT FIXTURE; NOT physics evidence.', 'suite_metadata': metadata, 'stock': stock,
        'static_stage': f.static_stage_catalog(directory/'scene.usda'),
        'mass_properties': {'passed': True, 'body_checks': {name: True for name in massnames}, 'mass_properties_by_prim_path': {name: {'fixture_only': True} for name in massnames}, 'scope': 'synthetic authority record'},
        'non_contact_auxiliaries': {'passed': True, 'original_steps_examined': 100, 'contact_records': [], 'activity_or_category_credit': False},
        'original_contact_journal_reconstruction': {'passed': True}}
    if mode == 'positive':
        report.update(nominal_configuration_matches=True, whole_stable_confirmation_interval_s=2., composed_mechanisms=report_composed,
            cart={'passed': True, 'phase_steps': [10, 68], 'signed_net_progress_m': 1., 'speed_qualified_forward_distance_m': 1., 'wheels': {}, 'scope': 'fixture'},
            cable={'passed': True}, bridge={'passed': True, 'phase_steps': [10, 68], 'support_callback_updates': 1, 'callback_records': [], 'scope': 'fixture'})
    else: report['positive_fidelity_scope'] = 'Stopped control, no positive completion assertion.'
    reportpath = base/(mode+'-full-report.json');summary = suite.save_run_report(report, reportpath)
    receipt = {'schema': 'simscene.independent_full_report_custody.v1', 'recorded_at_utc': '2029-01-01T00:01:00Z',
        'role': mode, 'run_directory': str(directory), 'accepted_for_clock_query': mode == 'positive', 'full_report': summary['individual_report'],
        'original_run_lock_sha256': report['run_lock_sha256'], 'original_evidence_lock_sha256': report['evidence_lock_sha256'],
        'checker_orchestration_version': 7, 'checker_source_sha256': r.PINS['fidelity'], 'full_summary': summary,
        'anchor_origin': 'Synthetic independent authority for byte-closure unit tests only.', 'P3_accepted': False, 'P4_accepted': False}
    receiptpath = base/(mode+'-receipt.json');dump(receiptpath, receipt)
    record = {'receipt_path': str(receiptpath), 'receipt_sha256': f.sha(receiptpath)}
    return {'root': directory, 'case': case, 'casepath': casepath, 'contract': contract, 'contractpath': contractpath, 'reviewpath': reviewpath,
        'freezepath': freezepath, 'report': report, 'reportpath': reportpath, 'receipt': receipt, 'receiptpath': receiptpath, 'record': record}


def reissue(value, report=True):
    if report:
        dump(value['reportpath'], value['report'])
        identity = {'path': str(value['reportpath']), 'sha256': f.sha(value['reportpath']), 'size': value['reportpath'].stat().st_size}
        value['receipt']['full_report'] = identity;value['receipt']['full_summary']['individual_report'] = identity
    dump(value['receiptpath'], value['receipt']);value['record']['receipt_sha256'] = f.sha(value['receiptpath'])


def load(value, **kwargs):
    return r.load_retained(value['root'], value['contractpath'], value['reviewpath'], value['freezepath'], value['record'],
        aggregation_started_at_utc=STARTED, software_freeze_path=SOFTWARE, **kwargs)


def original_v41_source_location():
    """Exercise the real frozen-source guard at its original authority path.

    These tests deliberately concern v7/v41, not the current experimental
    checkout. No source or worker check is mocked. The original module bytes
    must match the same pinned authority before selecting its source location.
    """
    software = json.loads(SOFTWARE.read_text())
    original = Path(software['checkout_root'])/'experiments/whole_home_fidelity_v7.py'
    assert f.sha(original) == r.PINS['fidelity'] == f.sha(f.__file__)
    return patch.object(f, '__file__', str(original))


def bind_control(base, reference, control):
    # Controls use exactly the original positive contract/review/freeze.
    for name in ('contractpath', 'reviewpath', 'freezepath', 'contract'): control[name] = reference[name]
    control['report']['supplemental_contract_sha256'] = f.sha(control['contractpath'])
    certificate = {'schema': r.clock.SCHEMA, 'errors': [], 'file_integrity_verified': True, 'geometry_queries_complete': True,
        'bounded_timing_floors_passed': True, 'physical_entry_no_escape_complete': True, 'inner_no_escape': True, 'supplemental_complete': True,
        'actual_first_entry_observed_step_bounds_inclusive': [68, 68], 'original_stock_entry_step': 68,
        'inner_first_entry': {'physics_steps': 68}, 'outer_first_entry': {'physics_steps': 68},
        'every_possible_original_prefix': r.clock.prefixes(reference['report']['stock'], reference['case'], 68, 68, 1.),
        'provenance': {'helper_sha256': r.PINS['clock'], 'independently_retained_full_report_sha256': reference['receipt']['full_report']['sha256'],
            'independently_retained_lock_sha256': {'run-lock.json': reference['receipt']['original_run_lock_sha256'], 'evidence-lock.json': reference['receipt']['original_evidence_lock_sha256']},
            'original_files_sha256': {'result.json': reference['report']['suite_metadata']['evidence_sha256']['result.json']}, 'full_report_path': str(reference['reportpath'])}}
    cp = base/'prior-clock.json';dump(cp, certificate)
    identity = {'path': str(cp), 'sha256': f.sha(cp), 'size': cp.stat().st_size}
    binding = {'schema': 'simscene.independent_reference_prebinding.v1', 'created_at_utc': '2029-01-01T00:02:00Z',
        'current_run_directory': str(control['root']), 'mode': 'no_trigger', 'reference_run_directory': str(reference['root']),
        'reference_record': copy.deepcopy(reference['record']), 'reference_full_report': copy.deepcopy(reference['receipt']['full_report']),
        'reference_run_lock_sha256': reference['receipt']['original_run_lock_sha256'], 'reference_evidence_lock_sha256': reference['receipt']['original_evidence_lock_sha256'],
        'reference_result_sha256': reference['report']['suite_metadata']['evidence_sha256']['result.json'], 'reference_clock_certificate': identity}
    bp = base/'prebinding.json';dump(bp, binding)
    receipt = control['receipt'];receipt.update(schema='simscene.independent_full_report_custody.v2', recorded_at_utc='2029-01-01T00:05:00Z',
        evaluation_started_at_utc='2029-01-01T00:03:00Z', reference_prebinding={'path': str(bp), 'sha256': f.sha(bp)},
        reference_postcheck={'completed_at_utc': '2029-01-01T00:04:00Z', 'unchanged': True, 'anchors': {
            'receipt_sha256': reference['record']['receipt_sha256'], 'full_report_sha256': reference['receipt']['full_report']['sha256'],
            'run_lock_sha256': reference['receipt']['original_run_lock_sha256'], 'evidence_lock_sha256': reference['receipt']['original_evidence_lock_sha256'],
            'result_sha256': reference['report']['suite_metadata']['evidence_sha256']['result.json'], 'clock_certificate_sha256': identity['sha256']}})
    reissue(control)
    return bp, cp


@unittest.skipUnless(original_v41_fixture_available(), 'Requires the local frozen v41 software/evidence archive')
class RetainedIntegrityTests(unittest.TestCase):
    def setUp(self):
        # Only physical contract validation is mocked for the tiny generic
        # custody fixture. Real production has no policy bypass flag.
        context = patch.object(f, 'validate_contract', new=lambda *a: True)
        context.start();self.addCleanup(context.stop)
        location = original_v41_source_location()
        location.start();self.addCleanup(location.stop)

    def test_v41_guard_still_rejects_the_different_current_source(self):
        original_root = Path(json.loads(SOFTWARE.read_text())['checkout_root']).resolve()
        if ROOT.resolve() == original_root:
            self.skipTest('Requires a distinct development checkout')
        with patch.object(f, '__file__', str(ROOT/'experiments/whole_home_fidelity_v7.py')):
            with self.assertRaisesRegex(ValueError, 'frozen checkout source changed'):
                f.assert_software_freeze(SOFTWARE)

    def test_real_byte_closure_original_full_report_identity_and_no_result_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = fixture(Path(tmp));before = value['reportpath'].read_bytes();original = Path.read_text
            def read_text(path, *args, **kwargs):
                if path == value['root']/'result.json': raise AssertionError('raw result parsing forbidden')
                return original(path, *args, **kwargs)
            with ExitStack() as stack:
                stack.enter_context(patch.object(Path, 'read_text', new=read_text))
                for module, name in [(f, 'verify_one'), (f.p, '_read_locked'), (f.p, 'evaluate'), (r.clock, 'verify')]:
                    stack.enter_context(patch.object(module, name, side_effect=AssertionError('physics/geometry recomputation forbidden')))
                report, proof = load(value)
            self.assertTrue(proof['passed']);self.assertFalse(proof['original_raw_result_parsed']);self.assertFalse(proof['physics_recomputed'])
            self.assertEqual(report, value['report']);self.assertEqual(value['reportpath'].read_bytes(), before)
            copied = Path(tmp)/'full-copy.json';suite.save_run_report(report, copied)
            self.assertEqual(copied.read_bytes(), before)

    def test_changed_every_locked_input_output_and_worker_extra_rejected(self):
        for filename in ('result.json', 'spec.json', 'scene.usda', 'asset-lock.json', 'runtime-lock.json', 'acceptance-case.json', 'runtime/simscene/worker/isaac_run.py', 'runtime/simscene/injected.py'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                value = fixture(Path(tmp));path = value['root']/filename
                path.write_bytes(path.read_bytes()+b'changed' if path.exists() else b'injected')
                with self.assertRaises((ValueError, OSError)): load(value)

    def test_receipt_report_mode_and_all_reduced_decision_fields_rejected(self):
        for change in ('failed', 'mode', 'code', 'no_mask', 'missing_interval', 'missing_raw_p1', 'no_mass', 'no_native', 'no_handoff', 'receipt_after', 'wrong_receipt_sha', 'partial_output'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                value = fixture(Path(tmp));report = value['report']
                if change == 'failed': report['passed'] = False
                elif change == 'mode': report['mode'] = 'no_trigger'
                elif change == 'code': report['supplemental_code_sha256'] = 'a'*64
                elif change == 'no_mask': report['stock']['activity'].pop('per_step_motion_flags')
                elif change == 'missing_interval': report['stock']['activity']['per_step_motion_flags'].pop(2)
                elif change == 'missing_raw_p1': report['composed_mechanisms']['mechanisms']['spoon']['raw_p1_report'].pop('motion_per_step')
                elif change == 'no_mass': report['mass_properties'].pop('mass_properties_by_prim_path')
                elif change == 'no_native': report['static_stage'].pop('physics_attributes')
                elif change == 'no_handoff': report['stock']['handoffs'].pop(next(iter(report['stock']['handoffs'])))
                elif change == 'receipt_after': value['receipt']['recorded_at_utc'] = '2031-01-01T00:00:00Z'
                elif change == 'wrong_receipt_sha': value['record']['receipt_sha256'] = 'a'*64
                else:
                    evidence = json.loads((value['root']/'evidence-lock.json').read_text());evidence['partial'] = True;dump(value['root']/'evidence-lock.json', evidence)
                if change != 'wrong_receipt_sha': reissue(value)
                with self.assertRaises((ValueError, KeyError, OSError)): load(value)

    def test_safe_output_manifest_and_unlisted_acquired_asset_closure(self):
        for name in ('../escape', '/absolute', 'nested/file', 'bad\\name'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp);path = root/'result.json';path.write_text('{}')
                evidence = {'result_file': 'result.json', 'partial': False, 'artifacts': {'result.json': {'size': 2, 'sha256': f.sha(path)}, name: {'size': 0, 'sha256': 'a'*64}}}
                with self.assertRaises(ValueError): r.stream_original_outputs(root, evidence, f.sha(path))
        with tempfile.TemporaryDirectory() as tmp:
            value = fixture(Path(tmp), assets=True);self.assertTrue(load(value)[1]['passed'])
            package = next((value['root']/'assets').iterdir());(package/'unexpected.bin').write_bytes(b'new unlisted dependency')
            with self.assertRaises(ValueError): load(value)

    def test_valid_controls_require_contemporaneous_reference_and_prior_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp);reference = fixture(base);control = fixture(base, 'no_trigger', reference)
            with self.assertRaises(ValueError): load(control, mode='no_trigger', reference_run=reference['root'], reference_record=reference['record'])
            bind_control(base, reference, control)
            report, proof = load(control, mode='no_trigger', reference_run=reference['root'], reference_record=reference['record'])
            self.assertTrue(proof['reference']['passed']);self.assertEqual(report['mode'], 'no_trigger')

    def test_late_changed_reference_prebinding_postcheck_or_clock_rejected(self):
        for change in ('late', 'wrong_root', 'wrong_ref_report', 'bad_postcheck', 'missing_clock', 'incomplete_clock', 'changed_reference_result', 'clock_noncollapsed', 'clock_flags', 'clock_geometry', 'clock_error'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp);reference = fixture(base);control = fixture(base, 'no_trigger', reference);bp, cp = bind_control(base, reference, control)
                binding = json.loads(bp.read_text())
                if change == 'late': binding['created_at_utc'] = '2029-01-01T00:03:01Z'
                elif change == 'wrong_root': binding['reference_run_directory'] = str(control['root'])
                elif change == 'wrong_ref_report': binding['reference_full_report']['sha256'] = 'a'*64
                elif change == 'bad_postcheck': control['receipt']['reference_postcheck']['anchors']['result_sha256'] = 'a'*64
                elif change == 'missing_clock': cp.unlink()
                elif change == 'incomplete_clock':
                    clock = json.loads(cp.read_text());clock['supplemental_complete'] = False;dump(cp, clock)
                    binding['reference_clock_certificate'].update(sha256=f.sha(cp), size=cp.stat().st_size)
                    control['receipt']['reference_postcheck']['anchors']['clock_certificate_sha256'] = f.sha(cp)
                elif change.startswith('clock_'):
                    clock = json.loads(cp.read_text())
                    if change == 'clock_noncollapsed': clock['actual_first_entry_observed_step_bounds_inclusive'][1] += 1
                    if change == 'clock_flags': clock['every_possible_original_prefix']['original_full_masks_sha256'] = 'a'*64
                    if change == 'clock_geometry': clock['geometry_queries_complete'] = False
                    if change == 'clock_error': clock['errors'] = ['unknown scope']
                    dump(cp, clock);binding['reference_clock_certificate'].update(sha256=f.sha(cp), size=cp.stat().st_size)
                    control['receipt']['reference_postcheck']['anchors']['clock_certificate_sha256'] = f.sha(cp)
                else: (reference['root']/'result.json').write_bytes(b'changed')
                dump(bp, binding);control['receipt']['reference_prebinding']['sha256'] = f.sha(bp);reissue(control)
                with self.assertRaises((ValueError, OSError)): load(control, mode='no_trigger', reference_run=reference['root'], reference_record=reference['record'])

    def test_reference_full_report_is_released_before_loading_current_report(self):
        class WatchReport(dict): pass
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp);ref = fixture(base);current = fixture(base, 'no_trigger', ref);bind_control(base, ref, current)
            real = r._load_one;watched = []
            def load_one(root, *args):
                if root == current['root']:
                    self.assertEqual(len(watched), 1)
                    self.assertIsNone(watched[0](), 'reference full report retained across current load')
                report, proof, receipt = real(root, *args)
                if root == ref['root']:
                    report = WatchReport(report);watched.append(weakref.ref(report))
                return report, proof, receipt
            with patch.object(r, '_load_one', side_effect=load_one):
                self.assertTrue(load(current, mode='no_trigger', reference_run=ref['root'], reference_record=ref['record'])[1]['passed'])
            self.assertIsNone(watched[0]())

    def test_metadata_duplicate_nonfinite_nonobject_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);path = root/'bad.json'
            for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '[]', 'null'):
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    with self.assertRaises(ValueError): r._json(path)
            path.write_text('{}');link = root/'link.json';link.symlink_to(path)
            with self.assertRaises(ValueError): r._json(link)

    def test_thirteen_runtime_fields_required_and_production_validator_has_no_fixture_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = fixture(Path(tmp))
            # Restore the true frozen physical validator: this tiny bookkeeping
            # fixture is not an acceptable P3 case, even with trusted receipts.
            with self.assertRaises(ValueError):
                original = __import__('importlib').util.spec_from_file_location('true_f7_for_test', f.__file__)
                module = __import__('importlib').util.module_from_spec(original);original.loader.exec_module(module)
                module.validate_contract(value['contract'], value['case'], 1.)
        with tempfile.TemporaryDirectory() as tmp:
            value = fixture(Path(tmp));path = value['root']/'run-lock.json';lock = json.loads(path.read_text());lock.pop('gpu_selection');dump(path, lock)
            value['report']['suite_metadata']['lock'] = lock
            value['report']['run_lock_sha256'] = f.sha(path);value['report']['suite_metadata']['evidence_sha256']['run-lock.json'] = f.sha(path)
            value['receipt']['original_run_lock_sha256'] = f.sha(path);reissue(value)
            with self.assertRaisesRegex(ValueError, 'thirteen runtime'): load(value)


if __name__ == '__main__': unittest.main()
