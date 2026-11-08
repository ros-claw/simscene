import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch
from simscene.catalog.models import SearchRequest
from simscene.catalog.store import CatalogStore
from simscene.catalog.network import MetadataError
from simscene.catalog.providers.hf_manifest import HFManifestProvider

SHA='a'*40

def source(repository='codepawl/scanned-objects-glb',format='jsonl',path='metadata.jsonl',source_id='gso-glb'):
    return SimpleNamespace(source_id=source_id,repository=repository,
                           metadata_entries=[SimpleNamespace(path=path,format=format,revision=SHA)])

def row(identity='Original_Box'):
    return {'id':identity,'file':f'objects/{identity}/{identity}.glb','file_name':f'engine/{identity}/{identity}.glb',
            'name':'Original box','category':'box','pack_bytes':1024,'size_metres':[.1,.2,.3],
            'license':'CC-BY-4.0','source':'https://example.invalid/original','source_categories':['Box'],
            'thumb':'thumbs/'+identity+'.webp','mass_estimate_kg':.2}

class HFManifestTests(unittest.TestCase):
    def test_metadata_only_lazy_refresh_reuses_pinned_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=CatalogStore(temporary);provider=HFManifestProvider(store,source());ledger=[]
            provider.configure(time.monotonic()+5,ledger);payload=(json.dumps(row())+'\n').encode();urls=[]
            def fetch(url,**kwargs):
                urls.append(url);kwargs['ledger'].append({'category':'metadata','bytes':len(payload)});return payload
            with patch('simscene.catalog.providers.hf_manifest.fetch_metadata',side_effect=fetch):
                first=provider.search(SearchRequest('box'));second=provider.search(SearchRequest('box'))
            self.assertEqual(len(urls),1);self.assertTrue(urls[0].endswith('/'+SHA+'/metadata.jsonl'))
            self.assertEqual(first.bytes_read,len(payload));self.assertEqual(second.bytes_read,0)
            record=first.items[0];self.assertEqual(record.entry_path,row()['file'])
            self.assertNotEqual(record.entry_path,row()['file_name']);self.assertEqual(record.license['basis'],'object_metadata_row')
            self.assertIsNone(record.physics);self.assertEqual(record.availability['acquisition']['kind'],'hf_single_glb')
            self.assertEqual(provider.resolve(record.ref),record)

    def test_schema_drift_duplicate_or_unsafe_row_preserves_previous_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider=HFManifestProvider(CatalogStore(temporary),source());good=(json.dumps(row())+'\n').encode()
            with patch('simscene.catalog.providers.hf_manifest.fetch_metadata',return_value=good):provider.refresh()
            previous=provider.snapshot
            cases=[{},dict(row(),file='../outside.glb'),dict(row(),pack_bytes=-1),dict(row(),license={'bad':'schema'})]
            for case in cases[:3]:
                with patch('simscene.catalog.providers.hf_manifest.fetch_metadata',return_value=json.dumps(case).encode()),self.assertRaises(MetadataError):provider.refresh()
                self.assertEqual(provider.snapshot,previous)
            with patch('simscene.catalog.providers.hf_manifest.fetch_metadata',return_value=good+good),self.assertRaises(MetadataError):provider.refresh()

    def test_unicode_object_identity_unknown_license_and_zero_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider=HFManifestProvider(CatalogStore(temporary),source())
            record=provider._record(dict(row('Pokémon_Box'),license=None,size_metres=[0,.2,.3]))
            self.assertEqual(record.ref.asset_id,'Pokémon_Box');self.assertIsNone(record.dimensions_m)
            self.assertEqual(record.license['status'],'unknown');self.assertIn('%C3%A9',provider.url(record.entry_path))

if __name__=='__main__':unittest.main()
