import hashlib
import io
from http.client import IncompleteRead
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simscene.acquisition.hf_package import acquire_hf_package
from simscene.acquisition.transfer import TransferBudget, transfer_scope
from simscene.assets import SearchError


class NativePackageAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payloads = {'object/model.usda': b'#usda 1.0\n(defaultPrim="Asset")\ndef Xform "Asset" {}\n',
                         'object/license.txt': b'Original test fixture: CC0'}
        self.calls = []
        self.ref = {'source_id': 'test-native', 'asset_id': 'one', 'revision': 'a'*40}
        self.descriptor = {'kind': 'hf_usd_package', 'repository': 'owner/repo', 'revision': 'a'*40,
                           'path': 'object/model.usda', 'package_path': 'object', 'files_complete': False,
                           'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                                     for name, data in self.payloads.items()]}
        self.limits = dict(download_bytes=100000, unpacked_bytes=100000, staging_bytes=100000)
        self.config = {'asset_cache_directory': str(self.root/'cache'), 'asset_cache_capacity_bytes': 1000000}

    def tearDown(self):
        self.temp.cleanup()

    def download(self, budget, url, destination=None, **kwargs):
        name = url.split('/resolve/'+'a'*40+'/')[1]
        self.calls.append(name)
        data = self.payloads.get(name)
        if data is None:
            raise SearchError('acquisition HTTP 404')
        if len(data) > min(budget.remaining, kwargs.get('max_bytes') or budget.remaining):
            raise SearchError('acquisition budget exceeded')
        budget.actual_download_bytes += len(data)
        budget.ledger.append({'endpoint': url, 'bytes': len(data), 'status': 'ok'})
        Path(destination).write_bytes(data)
        return len(data), hashlib.sha256(data).hexdigest()

    def acquire(self, **kwargs):
        test = self
        def transfer(budget, *args, **options):
            return test.download(budget, *args, **options)
        with patch.object(TransferBudget, 'download', transfer):
            return acquire_hf_package(self.descriptor, self.ref, self.limits, self.config,
                                      {'ref': self.ref}, {'license': 'CC0-1.0'}, {'fixture': True}, **kwargs)

    def test_selected_declared_members_warm_restore_and_corruption(self):
        first = self.acquire(job_directory=self.root/'job')
        self.assertEqual(set(self.calls), set(self.payloads))
        self.assertEqual(first['actual_download_bytes'], sum(map(len, self.payloads.values())))
        self.assertTrue(Path(first['root']).is_relative_to(self.root/'job'))
        self.calls.clear()
        second = self.acquire()
        self.assertFalse(self.calls)
        self.assertEqual(second['actual_download_bytes'], 0)
        self.assertEqual(first['asset_handle'], second['asset_handle'])
        Path(second['root']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(SearchError, 'integrity'):
            self.acquire()

    def test_declared_hash_mismatch_rejected(self):
        self.descriptor['files'][1]['sha256'] = '0'*64
        with self.assertRaisesRegex(SearchError, 'declared native package') as raised:
            self.acquire()
        self.assertGreater(raised.exception.actual_download_bytes, 0)
        self.assertFalse(list((self.root/'cache').glob('.native-source-*')))

    def test_dependency_repair_and_complete_descriptor(self):
        self.payloads['object/model.usda'] = b'#usda 1.0\n(defaultPrim="Asset")\ndef Xform "Asset" (references=@child.usda@) {}\n'
        self.payloads['object/child.usda'] = b'#usda 1.0\n(defaultPrim="Child")\ndef Xform "Child" {}\n'
        entry = self.descriptor['files'][0]
        entry.update(size=len(self.payloads[entry['path']]), sha256=hashlib.sha256(self.payloads[entry['path']]).hexdigest())
        self.descriptor['files_complete'] = True
        with self.assertRaisesRegex(SearchError, 'omitted discovered'):
            self.acquire()
        self.descriptor['files_complete'] = False
        result = self.acquire()
        self.assertEqual(result['dependency_status'], 'resolved_locally')
        self.assertIn('object/child.usda', {item['path'] for item in result['files']})

    def test_missing_dependency_requires_explicit_successful_repair(self):
        root = 'object/model.usda'
        self.payloads[root] = b'#usda 1.0\n(defaultPrim="Asset")\ndef Xform "Asset" (references=@child.usda@) {}\n'
        self.descriptor['files'][0].update(size=len(self.payloads[root]), sha256=hashlib.sha256(self.payloads[root]).hexdigest())
        with self.assertRaisesRegex(SearchError, 'dependency_missing'):
            self.acquire()
        self.payloads['object/child.usda'] = b'#usda 1.0\n(defaultPrim="Child")\ndef Xform "Child" {}\n'
        self.calls.clear()
        result = self.acquire()
        self.assertEqual(result['dependency_status'], 'resolved_locally')
        self.assertNotIn(root, self.calls)

    def test_warm_package_still_honors_staging_limit(self):
        self.acquire()
        self.limits['staging_bytes'] = 1
        with self.assertRaisesRegex(SearchError, 'staging/unpacked'):
            self.acquire()

    def test_global_capacity_is_independent_of_package_budget(self):
        from simscene.cache import AssetCache
        capacities = []
        def construct(*args, **kwargs):
            capacities.append(args[2] if len(args) > 2 else kwargs.get('max_bytes'))
            return AssetCache(*args, **kwargs)
        with patch('simscene.huggingface_cache.AssetCache', side_effect=construct):
            self.acquire()
        self.assertEqual(capacities, [self.config['asset_cache_capacity_bytes']])

    def test_active_shared_hook_accounts_prefix_on_ordinary_io_error(self):
        from simscene.huggingface_cache import _download
        from simscene.acquisition import transfer
        class Response:
            headers = {}
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): raise IncompleteRead(b'prefix', 20)
        budget = TransferBudget(100, 100, 100)
        with patch.object(transfer, 'build_opener') as opener, transfer_scope(budget):
            opener.return_value.open.return_value = Response()
            destination = self.root/'partial'
            with self.assertRaises(SearchError):
                _download('https://huggingface.co/fixture', destination, 100)
        self.assertEqual(budget.actual_download_bytes, 6)
        self.assertFalse(destination.exists())
        self.assertEqual(budget.ledger[0]['status'], 'error')
