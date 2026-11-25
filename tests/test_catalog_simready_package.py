import csv
from dataclasses import replace
import hashlib
import io
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from simscene.catalog.store import CatalogStore
from simscene.catalog import AssetRecord, AssetRef, SearchRequest, load_registry
from simscene.catalog.registry import Registry
from simscene.acquisition.plans import make_plan
from simscene.catalog.search import resolve_asset,search_assets
from simscene.catalog.providers.simready_package import USDCraftProvider,SimReadyPackageProvider,package_record
from test_catalog_abo import metadata_server
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

    def test_usdcraft_structure_is_explicitly_declared_and_not_a_dof_or_runtime_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider=USDCraftProvider(CatalogStore(temporary),source('nvidia/USDCraft-10K','csv','manifest.csv','usdcraft'))
            row=dict(native_row(),part_count='3',joint_count='2',joint_types='prismatic|revolute',has_textures='true')
            record=provider._record(row)
            self.assertEqual(record.physics.get('part_count'),{'value':3,'evidence':'declared'})
            self.assertEqual(record.physics.get('joint_count'),{'value':2,'evidence':'declared'})
            self.assertEqual(record.physics.get('joint_types'),{'value':['prismatic','revolute'],'evidence':'declared'})
            self.assertEqual(record.provenance.get('has_textures'),{'value':True,'evidence':'declared'})
            self.assertEqual(record.provenance['original_metadata']['joint_types'],'prismatic|revolute')
            self.assertEqual(provider._record(native_row()).provenance.get('has_textures'),{'value':False,'evidence':'declared'})
            self.assertNotIn('dof_count',record.physics)
            self.assertFalse(record.has_capability('openable'))
            self.assertFalse(record.has_capability('runtime_verified'))

    def test_usdcraft_joint_type_capabilities_are_conservative_for_inconsistent_rows(self):
        cases=(
            ('revolute','1','articulated',True,False,True),
            ('continuous','1','articulated',True,False,True),
            ('prismatic','1','articulated',False,True,True),
            ('prismatic|revolute','2','articulated',True,True,False),
            ('continuous|prismatic|revolute','3','articulated',True,True,False),
            ('','0','static_rigid',False,False,False),
            ('mystery','1','articulated',None,None,None),
            ('revolute|mystery','2','articulated',None,None,None),
            ('revolute|','2','articulated',None,None,None),
            ('revolute|revolute','2','articulated',None,None,None),
            ('prismatic|revolute','1','articulated',None,None,None),
            ('','1','articulated',None,None,None),
            ('','2','static_rigid',None,None,None),
            ('revolute','1','static_rigid',None,None,None),
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider=USDCraftProvider(CatalogStore(temporary),source('nvidia/USDCraft-10K','csv','manifest.csv','usdcraft'))
            for joint_types,count,physics_type,rotational,translational,single in cases:
                with self.subTest(joint_types=joint_types,count=count,physics_type=physics_type):
                    row=dict(native_row(),joint_types=joint_types,joint_count=count,physics_type=physics_type)
                    record=provider._record(row)
                    for name,value in (('declared_rotational_joint',rotational),('declared_translational_joint',translational),('declared_single_joint',single)):
                        self.assertEqual(record.capabilities.get(name),{'value':value,'evidence':'unknown' if value is None else 'declared'})

    def test_contradictory_physics_type_does_not_claim_articulation_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider=USDCraftProvider(CatalogStore(temporary),source('nvidia/USDCraft-10K','csv','manifest.csv','usdcraft'))
            for row in (dict(native_row(),physics_type='static_rigid',joint_count='1',joint_types='revolute'),
                        dict(native_row(),physics_type='articulated',joint_count='0',joint_types='')):
                record=provider._record(row)
                self.assertEqual(record.capabilities['articulated'],{'value':None,'evidence':'unknown'})
                self.assertEqual(record.provenance['original_metadata']['physics_type'],row['physics_type'])

    def test_old_structural_projection_is_refreshed_before_new_articulation_semantics(self):
        row=dict(native_row(),physics_type='static_rigid',joint_count='1',joint_types='revolute')
        output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=list(row));writer.writeheader();writer.writerow(row)
        payload=output.getvalue().encode()
        selected=load_registry().get('usdcraft');revision=selected.metadata_entries[0].revision
        path=f'/datasets/nvidia/USDCraft-10K/resolve/{revision}/manifest.csv'
        with tempfile.TemporaryDirectory() as directory, metadata_server({path:{'payload':payload}}) as (url,trace):
            store=CatalogStore(directory);provider=USDCraftProvider(store,selected,base_url=url)
            old=provider._record(row)
            old.capabilities['articulated']={'value':False,'evidence':'declared'}
            old_snapshot=revision+':'+('a'*64)+':usdcraft-structure-v1'
            store.replace_index('usdcraft',[old],old_snapshot)
            self.assertEqual(provider.snapshot,'index_not_refreshed')
            with self.assertRaisesRegex(ValueError, 'stale'):
                resolve_asset(old.ref,index_directory=directory)
            with self.assertRaisesRegex(ValueError, 'stale'):
                provider.resolve(old.ref)
            refreshed=provider.refresh()
            self.assertTrue(refreshed['snapshot'].endswith(':usdcraft-structure-v2'))
            self.assertNotEqual(refreshed['snapshot'],old_snapshot)
            self.assertEqual(store.get(old.ref).capabilities['articulated'],{'value':None,'evidence':'unknown'})
            self.assertEqual(resolve_asset(old.ref,index_directory=directory).capabilities['articulated'],{'value':None,'evidence':'unknown'})
            self.assertEqual(provider.resolve(old.ref).capabilities['articulated'],{'value':None,'evidence':'unknown'})
            # A still-running old process can overwrite a single row after the
            # new snapshot commit. New reads must not trust its projection.
            store.remember(old)
            self.assertEqual(resolve_asset(old.ref,index_directory=directory).capabilities['articulated'],{'value':None,'evidence':'unknown'})
            page=provider.search(SearchRequest('cabinet',source_ids=('usdcraft',),limit=8))
            self.assertEqual(page.items[0].capabilities['articulated'],{'value':None,'evidence':'unknown'})
            self.assertEqual([entry['path'] for entry in trace],[path])

    def test_usdcraft_custom_source_id_and_revision_use_configured_projection(self):
        original=load_registry().get('usdcraft')
        custom=replace(original,source_id='usdcraft-alias',metadata_entries=(replace(original.metadata_entries[0],revision='d'*40),))
        registry=Registry((custom,))
        with tempfile.TemporaryDirectory() as directory:
            store=CatalogStore(directory);provider=USDCraftProvider(store,custom)
            row=dict(native_row(),physics_type='static_rigid',joint_count='1',joint_types='revolute')
            record=provider._record(row)
            record.capabilities['articulated']={'value':False,'evidence':'declared'}
            store.replace_index(custom.source_id,[record],provider.snapshot_identity(b'pinned-index'))
            with patch('simscene.catalog.search.load_registry',return_value=registry):
                resolved=resolve_asset(record.ref,index_directory=directory)
            self.assertEqual(resolved.ref.revision,'d'*40)
            self.assertEqual(resolved.capabilities['articulated'],{'value':None,'evidence':'unknown'})

    def test_plan_uses_explicit_custom_registry_and_mixed_revisions_fail_closed(self):
        from pathlib import Path
        from test_asset_plans import config_fixture,runtime_fixture
        original=load_registry().get('usdcraft')
        source_d=replace(original,source_id='usdcraft-alias',metadata_entries=(replace(original.metadata_entries[0],revision='d'*40),))
        source_e=replace(source_d,metadata_entries=(replace(source_d.metadata_entries[0],revision='e'*40),))
        with tempfile.TemporaryDirectory() as directory:
            store=CatalogStore(Path(directory)/'index')
            old=USDCraftProvider(store,source_d);new=USDCraftProvider(store,source_e)
            old_record=old._record(native_row());new_record=new._record(native_row())
            store.replace_index(source_e.source_id,[new_record],new.snapshot_identity(b'new-revision'))
            store.remember(old_record)  # an older process completed after the new commit
            self.assertEqual(old.snapshot,'index_not_refreshed')
            with self.assertRaisesRegex(ValueError,'stale'):
                old.resolve(old_record.ref)
            page=new.search(SearchRequest('cabinet',source_ids=(source_e.source_id,),limit=8))
            self.assertEqual([record.ref.revision for record in page.items],['e'*40])
            store.fts=False
            fallback=new.search(SearchRequest('cabinet',source_ids=(source_e.source_id,),limit=8))
            self.assertEqual([record.ref.revision for record in fallback.items],['e'*40])
            registry_path=Path(directory)/'registry.json'
            registry_path.write_text(json.dumps(Registry((source_e,)).to_dict()))
            config=config_fixture(directory);config['registry_path']=str(registry_path)
            plan=make_plan(new_record.ref,runtime=runtime_fixture(),config=config)
            self.assertEqual(plan['asset_ref']['revision'],'e'*40)

    def test_usdcraft_filtered_search_refreshes_stale_projection_using_only_manifest(self):
        rows=[dict(native_row(),object_id='hinge',joint_types='revolute'),
              dict(native_row(),object_id='slider',joint_types='prismatic'),
              dict(native_row(),object_id='mixed',joint_count='2',joint_types='prismatic|revolute'),
              dict(native_row(),object_id='continuous',joint_types='continuous'),
              dict(native_row(),object_id='unknown',joint_types='revolute|mystery',joint_count='2'),
              dict(native_row(),object_id='static',physics_type='static_rigid',joint_types='revolute')]
        output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        payload=output.getvalue().encode()
        selected=load_registry().get('usdcraft');revision=selected.metadata_entries[0].revision
        index_path=f'/datasets/nvidia/USDCraft-10K/resolve/{revision}/manifest.csv'
        with tempfile.TemporaryDirectory() as directory, metadata_server({index_path:{'payload':payload}}) as (url,trace):
            store=CatalogStore(directory)
            old=AssetRecord(AssetRef('usdcraft','hinge',revision),'Original hinged cabinet',
                physics={'joint_count':{'value':1,'evidence':'declared'}},
                capabilities={'articulated':{'value':True,'evidence':'declared'}})
            store.replace_index('usdcraft',[old],revision+':'+('a'*64))
            provider=USDCraftProvider(store,selected,base_url=url)
            request=SearchRequest('cabinet',source_ids=('usdcraft',),required_capabilities=('declared_rotational_joint',),
                allow_unknown_constraints=True,limit=20)
            page=search_assets(request,providers={'usdcraft':provider},index_directory=directory)
            self.assertEqual(page.status,'ok')
            self.assertEqual({item['ref']['asset_id'] for item in page.items},{'hinge','mixed','continuous'})
            self.assertEqual(page.budgets['metadata_bytes'],len(payload))
            self.assertEqual(page.budgets['model_bytes'],0)
            self.assertLessEqual(len(json.dumps(page.to_dict()).encode()),12*1024)
            detail_path=next(item['detail_ref'] for item in page.items if item['ref']['asset_id']=='hinge')
            with open(detail_path,encoding='utf8') as stream: detail=json.load(stream)
            self.assertEqual(detail['physics']['joint_types'],{'value':['revolute'],'evidence':'declared'})
            self.assertEqual(detail['provenance']['has_textures'],{'value':False,'evidence':'declared'})
            request=SearchRequest('cabinet',source_ids=('usdcraft',),required_capabilities=('declared_translational_joint',),limit=20)
            warm=search_assets(request,providers={'usdcraft':provider},index_directory=directory)
            self.assertEqual({item['ref']['asset_id'] for item in warm.items},{'slider','mixed'})
            self.assertEqual(warm.budgets['metadata_bytes'],0)
            request=SearchRequest('cabinet',source_ids=('usdcraft',),required_capabilities=('declared_rotational_joint','declared_single_joint'),limit=20)
            single=search_assets(request,providers={'usdcraft':provider},index_directory=directory)
            self.assertEqual({item['ref']['asset_id'] for item in single.items},{'hinge','continuous'})
            self.assertEqual(single.budgets['metadata_bytes'],0)
            self.assertEqual([entry['path'] for entry in trace],[index_path])

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
