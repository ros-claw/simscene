import hashlib
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from simscene.catalog.store import CatalogStore
from simscene.catalog.providers.simready_package import USDCraftProvider,SimReadyPackageProvider,package_record
from test_catalog_hf_manifest import source,SHA


def native_row():
    return {'object_id':'part_01','path':'rigid/cabinet/part_01','group':'cabinet','category':'Cabinet','title':'Original hinged cabinet',
            'physics_type':'articulated','part_count':'2','joint_count':'1','joint_types':'revolute','has_textures':'false','physx_sha256':'b'*64}


def package():
    bom={'format_version':'1.0','items':[{'relative_path':'simready_usd/model.usd','size':1234,'hash':{'sha256':'b'*64}},
        {'relative_path':'simready_usd/textures/base.png','size':55,'hash':{'sha256':'c'*64}},
        {'relative_path':'simready_usd/.thumbs/256x256/preview.png','size':9999,'hash':{'sha256':'d'*64}}]}
    raw=json.dumps(bom).encode();descriptor={'format_version':'1.0','package_id':'original-package','license':'cc-by-4.0',
        'metadata':[{'name':'com.nvidia.simready.packaging.bom.json','hash':{'sha256':hashlib.sha256(raw).hexdigest()}},
                    {'name':'root_usds.json','hash':{'sha256':'e'*64}}]}
    return descriptor,bom,json.dumps(descriptor).encode(),raw

class NativeMetadataTests(unittest.TestCase):
    def test_usdcraft_native_projection_does_not_assert_measured_physics_or_complete_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider=USDCraftProvider(CatalogStore(temporary),source('nvidia/USDCraft-10K','csv','manifest.csv','usdcraft'))
            record=provider._record(native_row());descriptor=record.availability['acquisition']
            self.assertEqual(descriptor['path'],'rigid/cabinet/part_01/physx/model.usdc')
            self.assertEqual(descriptor['files'][0]['sha256'],'b'*64);self.assertIsNone(descriptor['files'][0]['size'])
            self.assertFalse(descriptor['files_complete']);self.assertEqual(record.physics['joint_count']['evidence'],'declared')
            self.assertEqual(record.license['license'],'Apache-2.0')
            with self.assertRaises(ValueError):USDCraftProvider(CatalogStore(temporary),source('other/thirdparty'))

    def test_individual_package_license_hash_inventory_and_metadata_gaps(self):
        src=source('projectsim/simready-assets','json','valve/com.nvidia.simready.packaging.json','projectsim')
        descriptor,bom,raw,bom_raw=package();record=package_record(src,src.metadata_entries[0].path,descriptor,bom,packaging_bytes=raw,bom_bytes=bom_raw)
        acquisition=record.availability['acquisition'];self.assertEqual(record.license['basis'],'individual_package_descriptor')
        self.assertEqual(record.license['license'],'CC-BY-4.0');self.assertFalse(acquisition['metadata_complete'])
        self.assertFalse(acquisition['files_complete']);self.assertEqual(acquisition['unverified_metadata'],['root_usds.json'])
        paths=[f['path'] for f in acquisition['files']];self.assertFalse(any('.thumbs' in p for p in paths));self.assertEqual(len(paths),4)
        self.assertIsNone(record.physics)
        unknown=dict(descriptor,license=None)
        self.assertEqual(package_record(src,src.metadata_entries[0].path,unknown,bom,packaging_bytes=json.dumps(unknown).encode(),bom_bytes=bom_raw).license['status'],'unknown')
        with self.assertRaises(ValueError):package_record(src,src.metadata_entries[0].path,descriptor,bom,packaging_bytes=raw,bom_bytes=b'changed')

    def test_package_refresh_fetches_only_descriptor_and_hashed_bom(self):
        with tempfile.TemporaryDirectory() as temporary:
            src=source('projectsim/simready-assets','json','valve/com.nvidia.simready.packaging.json','projectsim')
            provider=SimReadyPackageProvider(CatalogStore(temporary),src);descriptor,bom,raw,bom_raw=package();urls=[]
            def fetch(url,**kwargs):urls.append(url);return raw if url.endswith('packaging.json') else bom_raw
            with patch('simscene.catalog.providers.simready_package.fetch_metadata',side_effect=fetch):result=provider.refresh()
            self.assertEqual(result['records'],1);self.assertEqual(result['model_bytes'],0);self.assertEqual(len(urls),2)
            self.assertTrue(all(url.endswith('.json') for url in urls))

if __name__=='__main__':unittest.main()
