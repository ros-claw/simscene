import hashlib
import tempfile
import unittest
from pathlib import Path,PurePosixPath
from unittest.mock import patch
from urllib.parse import unquote
from pxr import Sdf,Usd,UsdGeom
from simscene.assets import SearchError
from simscene.huggingface_cache import acquire,_udim_matches


class HuggingFaceUdimTest(unittest.TestCase):
    def payload(self, directory):
        stage=Usd.Stage.CreateNew(str(Path(directory)/'root.usda'));prim=UsdGeom.Xform.Define(stage,'/Root').GetPrim();stage.SetDefaultPrim(prim)
        prim.CreateAttribute('texture',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath('Textures/wood.<UDIM>.png'));stage.GetRootLayer().Save()
        return {'root.usda':Path(directory,'root.usda').read_bytes(),'Textures/wood.1001.png':b'tile1','Textures/wood.1002.png':b'tile2'}

    def download(self,payload):
        def fetch(url,target,budget):
            name=unquote(url.split('/resolve/'+'a'*40+'/')[1])
            if name not in payload:raise SearchError('missing tile')
            data=payload[name]
            if len(data)>budget:raise SearchError('over capacity')
            target.write_bytes(data);return len(data),hashlib.sha256(data).hexdigest()
        return fetch

    def test_pinned_pagination_filters_and_preserves_all_tiles(self):
        pages=[([{'type':'file','path':'Textures/wood.1001.png'},{'type':'file','path':'Other/wood.1003.png'},{'type':'file','path':'Textures/other.1001.png'}],'<https://huggingface.co/api/datasets/org/repo/tree/'+('a'*40)+'/Textures?cursor=next>; rel="next"'),([{'type':'file','path':'Textures/wood.1002.png'}],'')]
        with patch('simscene.huggingface_assets._get',side_effect=pages) as listing:
            result=_udim_matches('org/repo','a'*40,PurePosixPath('Textures/wood.<UDIM>.png'))
        self.assertEqual([p.name for p in result],['wood.1001.png','wood.1002.png']);self.assertEqual(listing.call_args.args[1]['cursor'],'next')

    def test_acquisition_downloads_each_tile_and_cache_keeps_content_lock(self):
        with tempfile.TemporaryDirectory() as d:
            payload=self.payload(d);listing=([{'type':'file','path':p} for p in payload if p.endswith('.png')],'')
            with patch('simscene.huggingface_assets._get',return_value=listing),patch('simscene.huggingface_cache._download',side_effect=self.download(payload)):
                result=acquire('org/repo','a'*40,'root.usda',Path(d)/'cache',100000)
            self.assertEqual(result['dependency_status'],'resolved_locally');self.assertEqual(len(result['files']),3)
            self.assertEqual(result['udim_patterns'],{'Textures/wood.<UDIM>.png':['Textures/wood.1001.png','Textures/wood.1002.png']})
            with patch('simscene.huggingface_cache._download',side_effect=AssertionError('network')):
                again=acquire('org/repo','a'*40,'root.usda',Path(d)/'cache',100000)
            self.assertEqual(result['package_sha256'],again['package_sha256'])

    def test_partial_tile_failure_does_not_pass_when_usd_resolves_first_tile(self):
        with tempfile.TemporaryDirectory() as d:
            payload=self.payload(d);del payload['Textures/wood.1002.png']
            listing=([{'type':'file','path':'Textures/wood.1001.png'},{'type':'file','path':'Textures/wood.1002.png'}],'')
            with patch('simscene.huggingface_assets._get',return_value=listing),patch('simscene.huggingface_cache._download',side_effect=self.download(payload)):
                result=acquire('org/repo','a'*40,'root.usda',Path(d)/'cache',100000)
            self.assertEqual(result['dependency_status'],'missing');self.assertTrue(any('<UDIM>' in x for x in result['unresolved_dependencies']))

    def test_partial_cached_package_is_upgraded_without_replacing_original(self):
        with tempfile.TemporaryDirectory() as d:
            payload=self.payload(d);first=[{'type':'file','path':'Textures/wood.1001.png'},{'type':'file','path':'Textures/wood.1002.png'}]
            reduced=dict(payload);del reduced['Textures/wood.1002.png']
            with patch('simscene.huggingface_assets._get',return_value=(first,'')),patch('simscene.huggingface_cache._download',side_effect=self.download(reduced)):
                old=acquire('org/repo','a'*40,'root.usda',Path(d)/'cache',100000)
            old_root=Path(old['root']);old_bytes=old_root.read_bytes()
            with patch('simscene.huggingface_assets._get',return_value=(first,'')),patch('simscene.huggingface_cache._download',side_effect=self.download(payload)):
                new=acquire('org/repo','a'*40,'root.usda',Path(d)/'cache',100000)
            self.assertEqual(new['dependency_status'],'resolved_locally');self.assertNotEqual(old['package_sha256'],new['package_sha256']);self.assertEqual(old_root.read_bytes(),old_bytes)

    def test_page_tile_and_origin_budgets_reject_incomplete_listing(self):
        pattern=PurePosixPath('Textures/wood.<UDIM>.png')
        for link in ('<https://evil.test/api/datasets/org/repo/tree/'+('a'*40)+'/Textures?cursor=n>; rel="next"','<https://huggingface.co/api/datasets/org/repo/tree/main/Textures?cursor=n>; rel="next"'):
            with patch('simscene.huggingface_assets._get',return_value=([],link)):
                with self.assertRaises(SearchError):_udim_matches('org/repo','a'*40,pattern)
        with patch('simscene.huggingface_assets._get',return_value=([{'type':'file','path':'Textures/wood.1001.png'},{'type':'file','path':'Textures/wood.1002.png'}],'')):
            with self.assertRaises(SearchError):_udim_matches('org/repo','a'*40,pattern,max_tiles=1)
        with patch('simscene.huggingface_assets._get',return_value=([],'')):
            with self.assertRaises(SearchError):_udim_matches('org/repo','a'*40,pattern)
