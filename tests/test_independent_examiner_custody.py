"""Synthetic custody orchestration, not actual physics acceptance evidence.

Use real locked bytes/closure checks and original report serialization. The tiny
fixture is not P3: its physical contract validator, the expensive original f7
call, and reference static-clock proof are explicitly mocked. Those frozen
authorities retain their own complete regressions and no production bypass.
"""
import copy
import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import independent_examiner_custody as c
from test_retained_report_integrity import fixture, dump, bind_control, SOFTWARE, original_v41_source_location, original_v41_fixture_available


def invocation(base, mode='positive', reference=None):
    base.mkdir(exist_ok=True)
    current = fixture(base, mode, reference)
    if reference:
        reference['receipt']['role'] = 'main_positive_1'
        dump(reference['receiptpath'], reference['receipt'])
        reference['record']['receipt_sha256'] = c.sha(reference['receiptpath'])
        bp, cp = bind_control(base, reference, current)
        ref = {'run_directory': str(reference['root']), 'examination_record': reference['record'],
               'clock_certificate': {'path': str(cp), 'sha256': c.sha(cp)}}
    else: ref = None
    generic = base/'custody-freeze.json'
    modules = (c.__file__, c.retained.__file__, c.aggregate.__file__, c.f.__file__, c.suite.__file__, c.clock.__file__)
    dump(generic, {'schema': c.FREEZE_SCHEMA, 'frozen_at_utc': '2028-01-01T00:00:00Z',
        'source_files_sha256': {str(Path(path).resolve()): c.sha(path) for path in modules}})
    cfg = {'schema': c.SCHEMA, 'mode': mode, 'role': 'main_positive_1' if mode == 'positive' else mode,
        'run_directory': str(current['root']), 'contract_path': str(current['contractpath']),
        'static_review_path': str(current['reviewpath']), 'freeze_path': str(current['freezepath']),
        'software_freeze_path': str(SOFTWARE), 'output_directory': str(base/'new-examination'), 'additional_files': [],
        'reference': ref, 'bounded_clock': {key: str(base/(key+'.json')) for key in c.CLOCK_FIELDS} if mode == 'positive' else None,
        'custody_freeze': {'path': str(generic), 'sha256': c.sha(generic)}}
    path = base/'invocation.json';dump(path, cfg)
    return current, cfg, path


@unittest.skipUnless(original_v41_fixture_available(), 'Requires the local frozen v41 software/evidence archive')
class CustodyTests(unittest.TestCase):
    def setUp(self):
        self.counter = 0
        def now():
            self.counter += 1
            return (datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)+datetime.timedelta(seconds=self.counter)).isoformat()
        for context in (original_v41_source_location(), patch.object(c, 'now', side_effect=now),
            patch.object(c.f, 'validate_contract', new=lambda *a: True),
            patch.object(c.aggregate, 'physical_entry_clock', return_value={'passed': True, 'scope': 'synthetic existing certificate authority'})):
            context.start();self.addCleanup(context.stop)

    def test_positive_full_report_and_v1_receipt_are_retained_before_any_clock_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            value, cfg, path = invocation(Path(tmp))
            with patch.object(c.f, 'verify_one', return_value=value['report']) as f7, patch.object(c.clock, 'verify', side_effect=AssertionError('premature clock')):
                result = c.evaluate(path, c.sha(path))
            self.assertTrue(result['original_f7_passed']);self.assertFalse(result['clock_queried']);f7.assert_called_once()
            out = Path(cfg['output_directory']);receipt = json.loads((out/'independent-full-report-receipt.json').read_text())
            self.assertEqual(set(receipt), c.retained.BASE_RECEIPT_FIELDS)
            self.assertEqual((out/'full-v7-report.json').read_bytes(), value['reportpath'].read_bytes())
            self.assertEqual(receipt['full_report']['sha256'], c.sha(out/'full-v7-report.json'))
            self.assertTrue(receipt['accepted_for_clock_query']);self.assertFalse((out/'clock4').exists())
            with self.assertRaises(FileExistsError): c.evaluate(path, c.sha(path))

    def test_control_binds_prior_anchors_before_original_evaluation_and_rechecks_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp);refbase = base/'reference';refbase.mkdir();ref = fixture(refbase)
            value, cfg, path = invocation(base/'current', 'no_trigger', ref)
            out = Path(cfg['output_directory'])
            def original_f7(*args, **kwargs):
                self.assertEqual(kwargs['reference_run'], str(ref['root']))
                binding = json.loads((out/'reference-prebinding.json').read_text())
                start = json.loads((out/'evaluation-start.json').read_text())
                self.assertLess(c.suite._date(binding['created_at_utc']), c.suite._date(start['started_at_utc']))
                self.assertEqual(binding['reference_full_report'], ref['receipt']['full_report'])
                self.assertEqual(binding['reference_run_lock_sha256'], ref['receipt']['original_run_lock_sha256'])
                self.assertEqual(binding['reference_result_sha256'], ref['report']['suite_metadata']['evidence_sha256']['result.json'])
                return value['report']
            with patch.object(c.f, 'verify_one', side_effect=original_f7) as f7:
                result = c.evaluate(path, c.sha(path))
            f7.assert_called_once();receipt = json.loads((out/'independent-full-report-receipt.json').read_text())
            self.assertEqual(receipt['schema'], 'simscene.independent_full_report_custody.v2')
            self.assertEqual(set(receipt), c.retained.BASE_RECEIPT_FIELDS|{'evaluation_started_at_utc', 'reference_prebinding', 'reference_postcheck'})
            self.assertTrue(receipt['reference_postcheck']['unchanged']);self.assertFalse(receipt['accepted_for_clock_query'])
            reused, proof = c.retained.load_retained(value['root'], cfg['contract_path'], cfg['static_review_path'], cfg['freeze_path'],
                result['examination_record'], mode='no_trigger', reference_run=ref['root'], reference_record=ref['record'],
                aggregation_started_at_utc='2031-01-01T00:00:00Z', software_freeze_path=SOFTWARE)
            self.assertTrue(proof['passed']);self.assertEqual(reused, value['report'])

    def test_reference_or_current_dependency_changes_preserve_report_and_block_receipt(self):
        for target in ('reference_result', 'reference_clock', 'current_worker', 'invocation_config'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp);refbase = base/'reference';refbase.mkdir();ref = fixture(refbase)
                value, cfg, path = invocation(base/'current', 'no_trigger', ref);out = Path(cfg['output_directory'])
                def original_f7(*args, **kwargs):
                    filename = {'reference_result': ref['root']/'result.json', 'reference_clock': Path(cfg['reference']['clock_certificate']['path']),
                        'current_worker': value['root']/'runtime/simscene/worker/isaac_run.py', 'invocation_config': path}[target]
                    filename.write_bytes(filename.read_bytes()+b'changed')
                    return value['report']
                with patch.object(c.f, 'verify_one', side_effect=original_f7):
                    with self.assertRaises(ValueError): c.evaluate(path, c.sha(path))
                self.assertTrue((out/'full-v7-report.json').exists());self.assertTrue((out/'evaluation-error.json').exists())
                self.assertFalse((out/'independent-full-report-receipt.json').exists())

    def test_bad_prior_reference_fails_before_original_evaluation(self):
        for target in ('failed_reference', 'wrong_receipt_sha', 'failed_clock', 'later_repeat'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp);refbase = base/'reference';refbase.mkdir();ref = fixture(refbase)
                value, cfg, path = invocation(base/'current', 'no_trigger', ref)
                if target == 'failed_reference':
                    ref['report']['passed'] = False;dump(ref['reportpath'], ref['report'])
                if target == 'wrong_receipt_sha':
                    cfg['reference']['examination_record']['receipt_sha256'] = 'a'*64;dump(path, cfg)
                if target == 'later_repeat':
                    ref['receipt']['role'] = 'main_positive_2';dump(ref['receiptpath'], ref['receipt'])
                    cfg['reference']['examination_record']['receipt_sha256'] = c.sha(ref['receiptpath']);dump(path, cfg)
                with patch.object(c.f, 'verify_one') as f7:
                    if target == 'failed_clock':
                        with patch.object(c.aggregate, 'physical_entry_clock', return_value={'passed': False}):
                            with self.assertRaises(ValueError): c.evaluate(path, c.sha(path))
                    else:
                        with self.assertRaises(ValueError): c.evaluate(path, c.sha(path))
                f7.assert_not_called()

    def test_output_under_any_sealed_run_is_rejected_before_original_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp);_, cfg, path = invocation(base)
            other = base/'unrelated-sealed-run';other.mkdir();dump(other/'run-lock.json', {'synthetic': True})
            cfg['output_directory'] = str(other/'new-audit');dump(path, cfg)
            with patch.object(c.f, 'verify_one') as f7:
                with self.assertRaisesRegex(ValueError, 'any sealed-run subtree'): c.evaluate(path, c.sha(path))
                f7.assert_not_called()

    def test_failed_original_report_stays_failed_and_cannot_query_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            value, cfg, path = invocation(Path(tmp));failed = copy.deepcopy(value['report']);failed['passed'] = False
            with patch.object(c.f, 'verify_one', return_value=failed): result = c.evaluate(path, c.sha(path))
            self.assertFalse(result['original_f7_passed'])
            receipt = json.loads(Path(result['examination_record']['receipt_path']).read_text())
            self.assertFalse(receipt['accepted_for_clock_query']);self.assertFalse(receipt['full_summary']['passed'])
            with patch.object(c.clock, 'verify', side_effect=AssertionError('failed clock query')) as original_clock:
                with self.assertRaises(ValueError):
                    c.verify_clock(path, c.sha(path), result['record_file']['path'], result['record_file']['sha256'])
                original_clock.assert_not_called()

    def test_clock_is_separate_and_receives_only_prior_retained_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            value, cfg, path = invocation(Path(tmp))
            with patch.object(c.f, 'verify_one', return_value=value['report']): result = c.evaluate(path, c.sha(path))
            receipt = json.loads(Path(result['examination_record']['receipt_path']).read_text())
            expected = [receipt['full_report']['path'], receipt['full_report']['sha256'], receipt['original_run_lock_sha256'], receipt['original_evidence_lock_sha256']]
            def original_clock(*args):
                self.assertEqual(list(args[-4:]), expected)
                self.assertTrue(Path(result['record_file']['path']).exists())
                return {'schema': c.clock.SCHEMA, 'file_integrity_verified': True, 'supplemental_complete': True, 'scope': 'Synthetic orchestration only'}
            with patch.object(c.clock, 'verify', side_effect=original_clock) as called:
                clock = c.verify_clock(path, c.sha(path), result['record_file']['path'], result['record_file']['sha256'])
            called.assert_called_once();self.assertTrue(clock['clock_complete'])
            self.assertTrue((Path(cfg['output_directory'])/'clock4/clock-custody-receipt.json').is_file())

    def test_late_generic_freeze_forbids_retrospective_original_case_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            value, cfg, path = invocation(Path(tmp));p = Path(cfg['custody_freeze']['path'])
            generic = json.loads(p.read_text());generic['frozen_at_utc'] = '2029-01-01T00:00:01Z';dump(p, generic)
            cfg['custody_freeze']['sha256'] = c.sha(p);dump(path, cfg)
            with patch.object(c.f, 'verify_one') as f7:
                with self.assertRaisesRegex(ValueError, 'no retrospective conversion'): c.evaluate(path, c.sha(path))
                f7.assert_not_called()
            self.assertFalse(Path(cfg['output_directory']).exists())

    def test_original_exception_preserves_durable_diagnostic_without_accepted_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, cfg, path = invocation(Path(tmp))
            with patch.object(c.f, 'verify_one', side_effect=RuntimeError('synthetic interruption')):
                with self.assertRaises(RuntimeError): c.evaluate(path, c.sha(path))
            out = Path(cfg['output_directory'])
            self.assertTrue((out/'evaluation-start.json').exists());self.assertTrue((out/'evaluation-error.json').exists())
            self.assertFalse((out/'independent-full-report-receipt.json').exists())


if __name__ == '__main__': unittest.main()
