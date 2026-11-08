import copy
import unittest
from simscene.catalog.providers.http_assets import polyhaven_record


class HTTPAssetMetadataTests(unittest.TestCase):
    def data(self, kind):
        info = {'type': 0 if kind == 'hdri' else 1, 'name': 'Original fixture', 'tags': ['test']}
        keys = ['hdri'] if kind == 'hdri' else ['Diffuse', 'Rough', 'nor_gl', 'Metal']
        files = {key: {resolution: {encoding: {'url': 'https://dl.polyhaven.org/test/'+key+'_'+resolution+'.'+encoding,
                    'size': 100 if resolution == '1k' else 999999, 'md5': 'a'*32}}
                    for resolution in ['1k', '8k']} for key in keys
                    for encoding in ['exr' if kind == 'hdri' else 'jpg']}
        return info, files

    def test_selected_material_maps_only_no_physics_claim(self):
        info, files = self.data('material')
        record = polyhaven_record('fixture', info, files, kind='material')
        descriptor = record.availability['acquisition']
        self.assertEqual(len(descriptor['files']), 4)
        self.assertEqual(record.availability['estimated_download_bytes'], 400)
        self.assertEqual(record.license['license'], 'CC0-1.0')
        self.assertIsNone(record.physics)
        self.assertEqual(record.capabilities, {})
        self.assertEqual({x['role']: x['color_space'] for x in descriptor['files']},
                         {'base_color':'sRGB','roughness':'raw','normal_opengl':'raw','metallic':'raw'})
        self.assertTrue(all('_1k.' in item['path'] for item in descriptor['files']))

    def test_hdri_and_changed_metadata_have_distinct_identity(self):
        info, files = self.data('hdri')
        first = polyhaven_record('fixture', info, files, kind='hdri')
        changed = copy.deepcopy(files); changed['hdri']['1k']['exr']['md5'] = 'b'*32
        second = polyhaven_record('fixture', info, changed, kind='hdri')
        self.assertNotEqual(first.ref, second.ref)
        self.assertEqual(first.ref.variant_id, '1k-exr')
        self.assertEqual(len(first.availability['acquisition']['files']), 1)

    def test_missing_map_wrong_type_and_untrusted_origin_fail(self):
        info, files = self.data('material')
        del files['Metal']
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            polyhaven_record('fixture', info, files, kind='material')
        info, files = self.data('hdri')
        with self.assertRaises(ValueError): polyhaven_record('fixture', info, files, kind='material')
        files['hdri']['1k']['exr']['url'] = 'https://attacker.test/asset.exr'
        with self.assertRaises(ValueError): polyhaven_record('fixture', info, files, kind='hdri')


class PolyHavenProviderTests(unittest.TestCase):
    def test_bounded_curated_metadata_refresh_and_cached_search(self):
        import json
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from simscene.catalog.store import CatalogStore
        from simscene.catalog.models import SearchRequest
        from simscene.catalog.providers.http_assets import PolyHavenProvider
        info, files = HTTPAssetMetadataTests().data('hdri')
        source=SimpleNamespace(source_id='polyhaven',metadata_entries=[SimpleNamespace(path='hdris/fixture')])
        with tempfile.TemporaryDirectory() as temporary:
            provider=PolyHavenProvider(CatalogStore(temporary),source)
            def fetch(url,**kwargs):
                self.assertIn('SimScene',kwargs['headers']['User-Agent'])
                return json.dumps(info if '/info/' in url else files).encode()
            with patch('simscene.catalog.network.fetch_metadata',side_effect=fetch) as fetcher:
                page=provider.search(SearchRequest('fixture'));provider.search(SearchRequest('fixture'))
            self.assertEqual(fetcher.call_count,2)
            self.assertEqual(len(page.items),1)
            self.assertEqual(provider.resolve(page.items[0].ref),page.items[0])
