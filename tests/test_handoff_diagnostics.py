import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from simscene.diagnostics import diagnose, write_diagnosis


class DiagnosticTests(unittest.TestCase):
    def fixture(self, d):
        case = {'handoffs': [
            {'id': 'late', 'source_event': 'B', 'target_event': 'C', 'body_path': ['second', 'third'], 'maximum_lag_steps': 30},
            {'id': 'early', 'source_event': 'A', 'target_event': 'B', 'body_path': ['first', 'second'], 'maximum_lag_steps': 30}],
            'controls': {'broken_rope': {'upstream_event_ids': ['C'], 'cut_handoff_id': 'late'}}}
        c = Path(d)/'case.json'; c.write_text(json.dumps(case))
        stock = {'passed': False, 'timeline': {'passed': True}, 'input_integrity': {'passed': True},
                 'output_integrity': {'passed': True}, 'case_sha256': hashlib.sha256(c.read_bytes()).hexdigest(),
                 'events': {'A': {'onset_step': 20}, 'B': {'onset_step': None}, 'C': {'onset_step': None}},
                 'tiles': {'first': {'maximum_tilt_degrees': 9.46, 'first_tipped_step': None, 'final_tilt_degrees': 9.46}}}
        r = Path(d)/'report.json'; r.write_text(json.dumps({'stock': stock, 'mode': 'broken_rope'}))
        return c, r

    def test_first_causal_failure_not_last_symptom_or_dict_order(self):
        with tempfile.TemporaryDirectory() as d:
            c, r = self.fixture(d); v = diagnose(r, c)
            self.assertEqual(v['observed']['handoff_id'], 'early')
            self.assertEqual(v['observed']['required_control_upstream_missing'], ['C'])
            self.assertIn('cannot validate', v['observed']['control_conclusion'])
            self.assertNotIn('10', json.dumps(v['hypotheses']))

    def test_missing_records_or_different_case_cannot_diagnose(self):
        with tempfile.TemporaryDirectory() as d:
            c, r = self.fixture(d); v = json.loads(r.read_text()); v['stock']['timeline']['passed'] = False
            r.write_text(json.dumps(v)); self.assertEqual(diagnose(r, c)['status'], 'unknown')
            v['stock']['timeline']['passed'] = True; r.write_text(json.dumps(v)); c.write_text(c.read_text()+' ')
            self.assertEqual(diagnose(r, c)['observed']['reason'], 'supplied_case_does_not_match_report')

    def test_successful_intervention_is_not_a_broken_positive(self):
        with tempfile.TemporaryDirectory() as d:
            c, r = self.fixture(d); v = json.loads(r.read_text()); v['stock']['passed'] = True; r.write_text(json.dumps(v))
            self.assertEqual(diagnose(r, c)['status'], 'expected_control_block')
            p = Path(d)/'diagnostic.json'; summary = write_diagnosis(r, c, p)
            self.assertLessEqual(len(json.dumps(summary, ensure_ascii=False).encode()), 2048)
            self.assertFalse(summary['acceptance_claimed'])
