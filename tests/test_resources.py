import os,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from simscene.worker.resources import sample

class ResourcesTest(unittest.TestCase):
    def test_process_gpu_memory_is_counted_only_for_own_pid(self):
        output=f'12345, 900\n{os.getpid()}, 250\n{os.getpid()}, 30\n'
        with patch('simscene.worker.resources.subprocess.run',return_value=SimpleNamespace(stdout=output)):
            result=sample(3600,time.monotonic())
        self.assertEqual(result['gpu_process_memory_bytes'],280*1024*1024)
        self.assertEqual(result['physics_steps'],3600)
        self.assertGreater(result['peak_rss_bytes'],0)

    def test_unavailable_gpu_is_unknown(self):
        with patch('simscene.worker.resources.subprocess.run',side_effect=OSError('unavailable')):
            self.assertIsNone(sample(0,time.monotonic())['gpu_process_memory_bytes'])
