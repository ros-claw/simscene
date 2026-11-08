import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from simscene.preparation.glb_convert import validate_glb,CONVERTER
from simscene.preparation.profiles import PreparationError


def fixture(document):
    raw=json.dumps(document).encode();raw+=b' '*(-len(raw)%4)
    return struct.pack('<4sII',b'glTF',2,20+len(raw))+struct.pack('<II',len(raw),0x4e4f534a)+raw

class PreparationGlbAdmissionTests(unittest.TestCase):
    def test_codec_and_animation_rejected_before_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'asset.glb'
            for extension in ['KHR_draco_mesh_compression','KHR_texture_basisu','UNKNOWN_codec']:
                path.write_bytes(fixture({'asset':{'version':'2.0'},'extensionsRequired':[extension]}))
                with self.subTest(extension=extension),self.assertRaises(PreparationError) as caught:validate_glb(path)
                self.assertEqual(caught.exception.code,'unsupported_codec')
            path.write_bytes(fixture({'asset':{'version':'2.0'},'animations':[{}]}))
            with self.assertRaises(PreparationError):validate_glb(path,rigid=True)
            path.write_bytes(fixture({'asset':{'version':'2.0'},'nodes':[{'extras':{'joint':{}}}]}))
            with self.assertRaises(PreparationError):validate_glb(path,rigid=True)

    def test_optional_decoder_installation_is_explicit(self):
        from simscene.preparation.glb_convert import predecoder_fingerprint
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PreparationError) as caught:predecoder_fingerprint(directory)
            self.assertEqual(caught.exception.code,'dependency_missing')

    def test_invalid_and_empty_geometry_inputs_have_deterministic_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'asset.glb';path.write_bytes(b'bad')
            with self.assertRaises(PreparationError) as caught:validate_glb(path)
            self.assertEqual(caught.exception.code,'conversion_failed')
            # Legal empty GLB framing is accepted by decoder admission; USD inspection rejects empty meshes.
            path.write_bytes(fixture({'asset':{'version':'2.0'}}))
            self.assertEqual(validate_glb(path)['size'],path.stat().st_size)


class PreparationSnapshotTests(unittest.TestCase):
    def test_closure_is_copied_verified_and_identity_independent_of_location(self):
        from simscene.preparation.usd_layers import _snapshot
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'cache';(source/'models').mkdir(parents=True)
            model=source/'models'/'asset.glb';model.write_bytes(fixture({'asset':{'version':'2.0'}}))
            license_file=source/'LICENSE';license_file.write_text('original fixture CC0')
            files=[{'path':str(path.relative_to(source)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size} for path in [model,license_file]]
            acquired={'root':str(model),'files':files,'license':'CC0-1.0'}
            out1=root/'job1';out2=root/'job2';out1.mkdir();out2.mkdir()
            copied,sha,identity=_snapshot(acquired,out1)
            acquired['files']=list(reversed(files));_,_,second=_snapshot(acquired,out2)
            self.assertEqual(identity,second);self.assertEqual(copied.read_bytes(),model.read_bytes())
            self.assertTrue((out1/'source'/'LICENSE').is_file());self.assertTrue((out1/'licenses'/'source-license.json').is_file())
            license_file.write_text('tampered')
            with self.assertRaises(PreparationError) as caught:_snapshot(acquired,root/'bad')
            self.assertEqual(caught.exception.code,'verification_failed')


@unittest.skipUnless(os.environ.get('SIMSCENE_SDK_PREPARATION_FIXTURE'), 'opt-in actual initialized Isaac SDK worker required')
class ActualSdkPreparationTests(unittest.TestCase):
    def test_fixture_real_conversion_materials_axes_body_and_immutable_source(self):
        from simscene.preparation import prepare_acquired
        from pxr import Usd,UsdGeom,UsdPhysics
        path=Path(os.environ['SIMSCENE_SDK_PREPARATION_FIXTURE']).resolve();before=hashlib.sha256(path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            report=prepare_acquired({'root':str(path),'source_sha256':before,'license':'CC0-1.0'},'rigid_prop_v1',
                {'source_physics_policy':'reject_if_physics','proxy_tolerance_m':.002,'mass_kg':.12,'mass_note':'experimental original fixture'},
                {'usd_version':'0.25.11','converter_version':'6.1.0'},Path(directory)/'prepared')
            stage=Usd.Stage.Open(report['asset_path']);self.assertEqual(str(stage.GetDefaultPrim().GetPath()),'/Asset')
            self.assertEqual(UsdGeom.GetStageMetersPerUnit(stage),1);self.assertEqual(UsdGeom.GetStageUpAxis(stage),'Z')
            self.assertEqual(len([p for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)]),1)
            body=stage.GetPrimAtPath('/Asset/Body');self.assertTrue(body.HasAPI(UsdPhysics.RigidBodyAPI))
            self.assertFalse(any(a.GetName().startswith('xformOp:scale') for a in body.GetAttributes()))
            expected=[.2,.4,.3]
            for actual,want in zip(report['bounds']['dimensions'],expected):self.assertAlmostEqual(actual,want,places=5)
            self.assertEqual(report['toolchain'],CONVERTER);self.assertTrue(report['collision_report']['accepted'])
            self.assertTrue(report['body_map']['main']['collider_relative_prim_paths'])
            for entry in report['files']:
                file=Path(report['root'])/entry['path'];self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),entry['sha256'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            self.assertIn('/Asset/Body/Visual/Source/Looks/FourColourCC0', [str(p.GetPath()) for p in stage.Traverse()])

@unittest.skipUnless(os.environ.get('SIMSCENE_SDK_MESHOPT_FIXTURE'), 'opt-in original meshopt/WebP fixture and initialized SDK required')
class ActualSdkMeshoptPreparationTests(unittest.TestCase):
    def test_compressed_source_is_immutable_and_canonical_wrapper_handles_quantization(self):
        from simscene.preparation import prepare_acquired
        from simscene.physics_binding import validate_asset_binding
        path=Path(os.environ['SIMSCENE_SDK_MESHOPT_FIXTURE']).resolve();before=hashlib.sha256(path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            report=prepare_acquired({'root':str(path),'sha256':before,'license':'CC0-1.0'},'rigid_prop_v1',
                {'source_physics_policy':'reject_if_physics','proxy_tolerance_m':.002,'mass_kg':.12,'mass_note':'explicit experimental fixture mass'},
                {'usd_version':'0.25.11'},Path(directory)/'prepared')
            self.assertTrue(report['conversion']['predecode']['source_unchanged'])
            self.assertEqual(report['toolchain']['codec_policy_version'],2)
            for actual,expected in zip(report['bounds']['dimensions'],[.2,.4,.3]):self.assertAlmostEqual(actual,expected,places=5)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            validate_asset_binding({'manifest_path':report['manifest_path'],'manifest_sha256':report['manifest_sha256']},require_dynamic=True)

if __name__=='__main__':unittest.main()
