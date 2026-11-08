import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from simscene.workflows import wait_job


class WaitTests(unittest.TestCase):
    def test_preparation_phases_wait_for_durable_completion_without_inventing_exit(self):
        rows=[{'state':phase,'type':'asset_preparation'} for phase in ('queued','acquiring','converting','inspecting')]
        rows.append({'state':'completed','type':'asset_preparation','completion_confirmed':True,
                     'record_path':'/job/job.json','result':{'manifest_path':'/cache/manifest.json','manifest_sha256':'a'*64}})
        with tempfile.TemporaryDirectory() as d,patch('simscene.jobs.status',side_effect=rows) as status,patch('simscene.workflows.time.sleep'):
            path=Path(d)/'receipt.json';result=wait_job('prep-fixture',path)
            self.assertEqual(status.call_count,5)
            self.assertTrue(result['completion_confirmed'])
            self.assertIsNone(result['exit_code'])
            self.assertFalse(result['exit_code_observed'])
            self.assertFalse(result['physics_accepted'])
            self.assertEqual(json.loads(path.read_text())['prepared_manifest_sha256'],'a'*64)

    def test_wait_never_restarts_and_does_not_claim_physics(self):
        rows = [{'state': 'queued'}, {'state': 'running'}, {'state': 'completed', 'exit_code': 0,
                'exit_code_inferred': False, 'run_id': 'real-run', 'result_file': '/real/result.json'}]
        with tempfile.TemporaryDirectory() as d, patch('simscene.jobs.status', side_effect=rows) as status, patch('simscene.workflows.time.sleep'):
            p = Path(d)/'receipt.json'; result = wait_job('same-id', p)
            self.assertEqual([c.args[0] for c in status.call_args_list], ['same-id']*3)
            self.assertTrue(result['exit_code_observed'])
            self.assertFalse(result['physics_accepted'])
            self.assertFalse(json.loads(p.read_text())['new_job_started'])

    def test_inferred_zero_is_explicit_and_timeout_preserves_job(self):
        with tempfile.TemporaryDirectory() as d, patch('simscene.jobs.status', return_value={'state': 'completed', 'exit_code': 0, 'exit_code_inferred': True}):
            self.assertFalse(wait_job('legacy', Path(d)/'legacy.json')['exit_code_observed'])
        with tempfile.TemporaryDirectory() as d, patch('simscene.jobs.status', return_value={'state': 'running'}), patch('simscene.workflows.time.monotonic', side_effect=[0, 2]):
            p = Path(d)/'timeout.json'
            with self.assertRaises(TimeoutError):wait_job('same-id', p, timeout_s=1)
            self.assertFalse(p.exists())
