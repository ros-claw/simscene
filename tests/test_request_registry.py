"""Repeated and interrupted requests cannot launch duplicate workers."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time
import unittest
from simscene.request_registry import invoke
from simscene.scene import SceneError


class RequestRegistryTest(unittest.TestCase):
    def test_concurrent_retries_launch_once_and_reject_different_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[];known={}
            def launch(request,digest):
                calls.append(request);time.sleep(.1)
                result={'job_id':'job','run_id':'run','revision':2};known[(request,digest)]=result;return result
            def recover(request,digest):return known.get((request,digest),False)
            with ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(lambda _:invoke(directory,'request_a',{'steps':100},launch,recover),range(4)))
            self.assertEqual(len(calls),1)
            self.assertEqual(sum(not r['replayed'] for r in results),1)
            self.assertTrue(all(r['job_id']=='job' for r in results))
            with self.assertRaises(SceneError):invoke(directory,'request_a',{'steps':101},launch,lambda *_:False)
            known.clear()
            with self.assertRaisesRegex(SceneError,'missing or inconsistent'):
                invoke(directory,'request_a',{'steps':100},launch,recover)
            self.assertEqual(len(calls),1)

    def test_interrupted_launch_recovers_or_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            known={}
            def crash(request,digest):
                known[(request,digest)]={'job_id':'job','run_id':'run','revision':1}
                raise RuntimeError('interrupted after launch')
            def recover(request,digest):return known.get((request,digest),False)
            with self.assertRaises(RuntimeError):invoke(directory,'request_b',{'steps':10},crash,recover)
            result=invoke(directory,'request_b',{'steps':10},lambda *_:self.fail('duplicate launch'),recover)
            self.assertTrue(result['replayed']);self.assertEqual(result['job_id'],'job')
            p=Path(directory)/'job-requests'/'request_c.json';p.write_text(json.dumps({'payload_sha256':__import__('hashlib').sha256(b'{"steps":10}').hexdigest(),'state':'starting'}))
            with self.assertRaisesRegex(SceneError,'uncertain'):
                invoke(directory,'request_c',{'steps':10},lambda *_:self.fail('must fail closed'),lambda *_:None)


if __name__=='__main__':unittest.main()
