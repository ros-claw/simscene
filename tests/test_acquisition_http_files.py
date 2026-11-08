import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from simscene.acquisition.http_files import acquire_http_files
from simscene.acquisition.transfer import TransferBudget
from simscene.assets import SearchError


class HTTPFileAcquisitionTests(unittest.TestCase):
    def test_selected_files_hashes_restore_drift_and_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); payload=b'original HDR fixture bytes'; calls=[]
            descriptor={'kind':'http_files','source':'polyhaven','asset_type':'hdri','resolution':'1k','files':[
                {'path':'fixture.exr','url':'https://dl.polyhaven.org/fixture.exr','size':len(payload),
                 'md5':hashlib.md5(payload).hexdigest(),'role':'environment','color_space':'linear'}]}
            ref={'source_id':'polyhaven','asset_id':'fixture','revision':'a'*64,'variant_id':'1k-exr'}
            limits={'download_bytes':10000,'unpacked_bytes':10000,'staging_bytes':10000}
            config={'asset_cache_directory':str(root/'cache'),'asset_cache_capacity_bytes':100000}
            def download(budget,url,target,**kwargs):
                calls.append(kwargs);Path(target).write_bytes(payload);budget.actual_download_bytes+=len(payload)
                return len(payload),hashlib.sha256(payload).hexdigest()
            def acquire(**kwargs):
                with patch.object(TransferBudget,'download',download):
                    return acquire_http_files(descriptor,ref,limits,config,{}, {'license':'CC0'}, {},**kwargs)
            first=acquire(job_directory=root/'job');self.assertEqual(first['actual_download_bytes'],len(payload))
            self.assertIn('User-Agent',calls[0]['headers']);self.assertTrue(Path(first['root']).is_relative_to(root/'job'))
            second=acquire();self.assertEqual(second['actual_download_bytes'],0);self.assertEqual(len(calls),1)
            limits['staging_bytes']=1
            with self.assertRaisesRegex(SearchError,'staging'):acquire()
            limits['staging_bytes']=10000
            Path(second['root']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(SearchError,'integrity'):acquire()

    def test_download_hash_mismatch_never_publishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            descriptor={'kind':'http_files','source':'polyhaven','files':[{'path':'f.exr','url':'https://dl.polyhaven.org/f.exr',
                'size':1,'md5':'a'*32,'role':'environment','color_space':'linear'}]}
            def download(budget,url,target,**kwargs):
                Path(target).write_bytes(b'x');return 1,hashlib.sha256(b'x').hexdigest()
            with patch.object(TransferBudget,'download',download),self.assertRaisesRegex(SearchError,'MD5'):
                acquire_http_files(descriptor,{'source_id':'polyhaven','asset_id':'f','revision':'a'*64},
                    dict(download_bytes=10000,unpacked_bytes=10000,staging_bytes=10000),
                    {'asset_cache_directory':temporary,'asset_cache_capacity_bytes':100000},{},{},{})
            self.assertFalse(list(root.glob('.http-source-*')))
