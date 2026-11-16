"""Explicit derived-asset repairs must preserve source and fail closed."""
import copy
import math

import pytest

from simscene.preparation.profiles import PreparationError, preparation_key, validate_parameters


def parameters():
    return {'source_physics_policy': 'repair_explicit', 'collision_method': 'preserve',
            'proxy_tolerance_m': .002, 'native_physics_repairs': {
                'missing_masses_kg': {'Base': 12., 'Door': 8.},
                'neutralize_drives': {'Hinge': 50.},
                'reason': 'Experimental masses and disabled source acceleration drive; not manufacturer data.'}}


def source_stage():
    from pxr import Usd, UsdGeom, UsdPhysics
    stage = Usd.Stage.CreateInMemory()
    root = UsdGeom.Xform.Define(stage, '/Native')
    stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    for name in ('Base', 'Door'):
        body = UsdGeom.Xform.Define(stage, '/Native/' + name).GetPrim()
        UsdPhysics.RigidBodyAPI.Apply(body)
        shape = UsdGeom.Cube.Define(stage, '/Native/' + name + '/Collider')
        UsdPhysics.CollisionAPI.Apply(shape.GetPrim()).CreateCollisionEnabledAttr(True)
    joint = UsdPhysics.RevoluteJoint.Define(stage, '/Native/Hinge')
    joint.CreateBody0Rel().SetTargets(['/Native/Base'])
    joint.CreateBody1Rel().SetTargets(['/Native/Door'])
    joint.CreateAxisAttr('Z')
    joint.CreateLowerLimitAttr(-80.)
    joint.CreateUpperLimitAttr(80.)
    drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), 'angular')
    drive.CreateTypeAttr('acceleration')
    drive.CreateStiffnessAttr(10.)
    drive.CreateDampingAttr(4.)
    drive.CreateMaxForceAttr(float('inf'))
    drive.CreateTargetPositionAttr(30.)
    return stage


def test_repairs_are_explicit_bounded_and_part_of_preparation_identity():
    chosen = parameters()
    normalized = validate_parameters('articulated_prop_v1', chosen)
    assert normalized['native_physics_repairs']['missing_masses_kg'] == {'Base': 12., 'Door': 8.}
    target = {'engine': 'physx', 'version': 'fixture'}
    first = preparation_key('a' * 64, 'articulated_prop_v1', chosen, target, {'backend': 'usd'})
    changed = copy.deepcopy(chosen)
    changed['native_physics_repairs']['missing_masses_kg']['Door'] = 9.
    assert preparation_key('a' * 64, 'articulated_prop_v1', changed, target, {'backend': 'usd'}) != first
    for bad in ({'reason': '', 'missing_masses_kg': {'Door': 2}, 'neutralize_drives': {}},
                {'reason': 'test', 'missing_masses_kg': {'../Door': 2}, 'neutralize_drives': {}},
                {'reason': 'test', 'missing_masses_kg': {'Door': True}, 'neutralize_drives': {}},
                {'reason': 'test', 'missing_masses_kg': {'Door': float('nan')}, 'neutralize_drives': {}},
                {'reason': 'test', 'missing_masses_kg': {}, 'neutralize_drives': {}},
                {'reason': 'test', 'missing_masses_kg': {}, 'neutralize_drives': {'Hinge': -1}}):
        with pytest.raises(PreparationError):
            validate_parameters('articulated_prop_v1', dict(chosen, native_physics_repairs=bad))
    with pytest.raises(PreparationError):
        validate_parameters('visual_prop_v1', chosen)
    with pytest.raises(PreparationError):
        validate_parameters('articulated_prop_v1', dict(chosen, source_physics_policy='preserve_valid'))


def test_repairs_apply_only_to_derived_stage_and_keep_native_joint():
    from pxr import Usd, UsdPhysics
    from simscene.preparation.articulation import inspect_articulation
    from simscene.preparation.native_repairs import apply_native_repairs
    source = source_stage()
    before = source.GetRootLayer().ExportToString()
    with pytest.raises(PreparationError, match='lacks explicit mass'):
        inspect_articulation(source)
    derived = Usd.Stage.Open(source.Flatten())
    report = apply_native_repairs(derived, parameters()['native_physics_repairs'])
    measured = inspect_articulation(derived)
    assert source.GetRootLayer().ExportToString() == before
    assert {item['relative_prim_path']: item['mass_kg'] for item in report['masses']} == {'Base': 12., 'Door': 8.}
    assert report['drives'][0]['source']['type'] == 'acceleration'
    assert report['drives'][0]['source']['max_effort'] == {'USD_sentinel': 'positive_infinity'}
    assert report['drives'][0]['derived']['type'] == 'force'
    assert measured['joint_map']['main']['limits'] == pytest.approx([-math.radians(80), math.radians(80)])
    assert measured['joint_map']['main']['drive']['stiffness'] == 0.
    assert UsdPhysics.MassAPI(source.GetPrimAtPath('/Native/Door')).GetMassAttr().HasAuthoredValueOpinion() is False


def test_cooked_mass_readback_does_not_claim_source_mass_was_preserved():
    import numpy as np
    from simscene.worker.mechanism import PreparedArticulationState
    class FakeView:
        def get_masses(self): return np.array([[8.]])
        def get_coms(self): return np.array([[[0., 0., 0., 0., 0., 0., 1.]]])
        def get_inertias(self): return np.array([[[1., 0., 0., 0., 1., 0., 0., 0., 1.]]])
    state=PreparedArticulationState.__new__(PreparedArticulationState)
    state.np=np;state.rigid=None;state.articulations=[(FakeView(),['/World/door'],[],{})];state.two_dof_articulations=[]
    state.bindings={'door': {'bodies': {'link1': {'motion_body': '/World/door',
        'mass_provenance': 'explicit_experimental_assumption'}},
        'native_repairs_ref': {'manifest_sha256': 'a'*64, 'json_pointer': '/physics_repairs'}}}
    observed=state.mass_properties(0)['/World/door']
    assert observed['mass_kg'] == 8.
    assert 'source mass/collision preserved' not in observed['source']
    assert 'prepared manifest' in observed['source']
    assert observed['mass_provenance'] == 'explicit_experimental_assumption'
    assert observed['native_repairs_ref']['manifest_sha256'] == 'a'*64


@pytest.mark.parametrize('mutation', ['malformed_path', 'boolean_mass', 'nonzero_target', 'missing_source', 'empty_source'])
def test_repair_report_rejects_malformed_or_inconsistent_provenance(mutation):
    from simscene.preparation.native_repairs import apply_native_repairs, validate_repair_report
    repairs=parameters()['native_physics_repairs']
    report=apply_native_repairs(source_stage(),repairs)
    if mutation == 'malformed_path': report['masses'][0]['relative_prim_path'] = ['Base']
    elif mutation == 'boolean_mass': report['masses'][0]['mass_kg'] = True
    elif mutation == 'nonzero_target': report['drives'][0]['derived']['target_position'] = 1.
    elif mutation == 'missing_source': report['drives'][0].pop('source')
    else: report['drives'][0]['source']={}
    with pytest.raises(ValueError, match='repair report'):
        validate_repair_report(repairs,report)


def test_explicit_repair_wont_neutralize_an_otherwise_supported_source_drive():
    from pxr import UsdPhysics
    from simscene.preparation.native_repairs import apply_native_repairs
    stage=source_stage(); drive=UsdPhysics.DriveAPI(stage.GetPrimAtPath('/Native/Hinge'),'angular')
    drive.GetTypeAttr().Set('force');drive.GetMaxForceAttr().Set(25.)
    before=stage.GetRootLayer().ExportToString()
    with pytest.raises(PreparationError, match='already supported'):
        apply_native_repairs(stage,parameters()['native_physics_repairs'])
    assert stage.GetRootLayer().ExportToString()==before


@pytest.mark.parametrize('units', [.1, 10., float('nan')])
def test_native_mass_units_must_be_canonical_before_any_repair(units):
    from pxr import UsdPhysics
    from simscene.preparation.native_repairs import apply_native_repairs
    stage=source_stage();UsdPhysics.SetStageKilogramsPerUnit(stage,units)
    before=stage.GetRootLayer().ExportToString()
    with pytest.raises(PreparationError,match='kilogram'):
        apply_native_repairs(stage,parameters()['native_physics_repairs'])
    assert stage.GetRootLayer().ExportToString()==before


@pytest.mark.parametrize('attribute', ['mass', 'density'])
def test_repair_rejects_authored_descendant_mass_or_density(attribute):
    from pxr import UsdPhysics
    from simscene.preparation.native_repairs import apply_native_repairs
    stage=source_stage();api=UsdPhysics.MassAPI.Apply(stage.GetPrimAtPath('/Native/Door/Collider'))
    (api.CreateMassAttr(99.) if attribute=='mass' else api.CreateDensityAttr(700.))
    before=stage.GetRootLayer().ExportToString()
    with pytest.raises(PreparationError,match='descendant|density'):
        apply_native_repairs(stage,parameters()['native_physics_repairs'])
    assert stage.GetRootLayer().ExportToString()==before


def test_repair_rejects_inherited_mass_api_density():
    from pxr import UsdPhysics
    from simscene.preparation.native_repairs import apply_native_repairs
    stage=source_stage()
    UsdPhysics.MassAPI.Apply(stage.GetDefaultPrim()).CreateDensityAttr(700.)
    before=stage.GetRootLayer().ExportToString()
    with pytest.raises(PreparationError,match='inherited.*density'):
        apply_native_repairs(stage,parameters()['native_physics_repairs'])
    assert stage.GetRootLayer().ExportToString()==before


def test_material_density_override_must_be_explicit_and_reported():
    from pxr import UsdPhysics, UsdShade
    from simscene.preparation.native_repairs import apply_native_repairs, validate_repair_report
    stage=source_stage();shape=stage.GetPrimAtPath('/Native/Door/Collider')
    mat=UsdShade.Material.Define(stage,'/Native/Steel')
    UsdPhysics.MaterialAPI.Apply(mat.GetPrim()).CreateDensityAttr(700.)
    UsdShade.MaterialBindingAPI.Apply(shape).Bind(mat,materialPurpose='physics')
    repairs=copy.deepcopy(parameters()['native_physics_repairs'])
    before=stage.GetRootLayer().ExportToString()
    with pytest.raises(PreparationError,match='material density'):
        apply_native_repairs(stage,repairs)
    assert stage.GetRootLayer().ExportToString()==before
    repairs['material_density_overrides']={'Door/Collider':{'material_path':'Steel','density_kg_m3':700.}}
    report=apply_native_repairs(stage,repairs)
    validate_repair_report(repairs,report)
    assert report['material_density_overrides'] == [{'collider_path':'Door/Collider','material_path':'Steel',
        'density_kg_m3':700.,'provenance':'authored_material_density_overridden_by_explicit_body_mass'}]
    forged=copy.deepcopy(report);forged['material_density_overrides'][0]['density_kg_m3']=999.
    with pytest.raises(ValueError,match='repair report'):
        validate_repair_report(repairs,forged)


def test_repairs_accept_usd_float32_rounding_without_changing_requested_values():
    from simscene.preparation.articulation import inspect_articulation
    from simscene.preparation.native_repairs import apply_native_repairs, annotate_repaired_graph
    from pxr import Usd,UsdGeom
    chosen=copy.deepcopy(parameters()['native_physics_repairs'])
    chosen['missing_masses_kg']['Door']=8.3
    chosen['neutralize_drives']['Hinge']=50.1
    source=source_stage();report=apply_native_repairs(source,chosen)
    stage=Usd.Stage.CreateInMemory();root=UsdGeom.Xform.Define(stage,'/Asset');stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    # Nest a copy under the same Native wrapper used by the producer.
    from pxr import Sdf
    Sdf.CopySpec(source.GetRootLayer(),'/Native',stage.GetRootLayer(),'/Asset/Native')
    graph=annotate_repaired_graph(inspect_articulation(stage),chosen)
    door=next(item for item in graph['body_map'].values() if item['relative_prim_path']=='Native/Door')
    assert door['mass_kg'] == pytest.approx(8.3,rel=1e-6)
    assert graph['joint_map']['main']['drive']['max_effort'] == pytest.approx(50.1,rel=1e-6)
    assert report['masses'][1]['mass_kg'] == 8.3


@pytest.mark.parametrize('mutation', ['missing_mass', 'extra_mass', 'overwrite_mass', 'unknown_drive', 'unlisted_drive'])
def test_incomplete_or_unauthorized_repairs_do_not_partially_edit_derived_stage(mutation):
    from pxr import UsdPhysics
    from simscene.preparation.native_repairs import apply_native_repairs
    stage = source_stage()
    requested = copy.deepcopy(parameters()['native_physics_repairs'])
    if mutation == 'missing_mass':
        del requested['missing_masses_kg']['Door']
    elif mutation == 'extra_mass':
        requested['missing_masses_kg']['Missing'] = 1.
    elif mutation == 'overwrite_mass':
        UsdPhysics.MassAPI.Apply(stage.GetPrimAtPath('/Native/Door')).CreateMassAttr(4.)
    elif mutation == 'unknown_drive':
        requested['neutralize_drives']['Missing'] = 1.
    else:
        requested['neutralize_drives'] = {}
    before = stage.GetRootLayer().ExportToString()
    with pytest.raises(PreparationError):
        apply_native_repairs(stage, requested)
    assert stage.GetRootLayer().ExportToString() == before


def test_prepared_native_package_records_repairs_and_preserves_source_bytes(tmp_path, monkeypatch):
    import hashlib
    import json
    import pxr
    from pxr import Usd, UsdGeom
    from simscene.physics_binding import validate_asset_binding
    from simscene.preparation.articulation import inspect_articulation
    from simscene.preparation.usd_layers import prepare_acquired
    stage = source_stage()
    mesh = UsdGeom.Mesh.Define(stage, '/Native/Visual')
    mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
    mesh.CreateFaceVertexCountsAttr([3, 3, 3, 3])
    mesh.CreateFaceVertexIndicesAttr([0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3])
    source = tmp_path / 'original.usda'
    stage.GetRootLayer().Export(str(source))
    before = source.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    dependency=tmp_path/'dependency.bin';dependency.write_bytes(b'original dependency bytes')
    acquired = {'root': str(source), 'source_ref': {'source_id': 'fixture', 'asset_id': 'hinge', 'revision': 'v1'},
                'files': [{'path': source.name, 'sha256': digest, 'size_bytes': len(before)},
                          {'path':dependency.name,'sha256':hashlib.sha256(dependency.read_bytes()).hexdigest(),
                           'size_bytes':dependency.stat().st_size}], 'license': 'CC0-1.0'}
    acquired['manifest_sha256']=hashlib.sha256(json.dumps(acquired['files'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    # Native USD preparation does not call PhysxSchema; the real Isaac worker
    # supplies it. This CPU fixture tests the source-to-derived contract.
    monkeypatch.setattr(pxr, 'PhysxSchema', object(), raising=False)
    target = {'engine': 'physx', 'usd_version': '.'.join(map(str, Usd.GetVersion()))}
    report = prepare_acquired(acquired, 'articulated_prop_v1', parameters(), target, tmp_path / 'prepared')
    assert source.read_bytes() == before
    manifest = validate_asset_binding({'manifest_path': report['manifest_path'],
                                       'manifest_sha256': report['manifest_sha256']}, require_dynamic=True,
                                      asset_path=report['asset_path'])
    assert manifest['physics_repairs']['reason'] == parameters()['native_physics_repairs']['reason']
    assert len(manifest['physics_repairs']['masses']) == 2
    assert len(manifest['physics_repairs']['drives']) == 1
    assert all(entry['physics_provenance'] == 'native_link_with_explicit_experimental_mass'
               for entry in manifest['body_map'].values())
    assert manifest['joint_map']['main']['drive']['provenance'] == 'explicit_neutral_drive_not_original_behavior'
    assert manifest['articulation_report']['scope'].startswith('inspected derived graph')
    assert manifest['runtime_validation']['status'] == 'not_run'
    from simscene.preparation.contracts import prepared_contract
    summary = prepared_contract(manifest, manifest_path=report['manifest_path'], manifest_sha256=report['manifest_sha256'])
    assert summary['physics_report']['experimental_mass'] is True
    assert summary['physics_report']['native_repairs_ref']['json_pointer'] == '/physics_repairs'
    assert 'experimental_native_link_masses' in summary['warnings']
    assert 'source_native_drive_neutralized' in summary['warnings']
    prepared = Usd.Stage.Open(report['asset_path'])
    assert inspect_articulation(prepared)['joint_map']['main']['drive']['stiffness'] == 0.
    # Resolved scene and every cooked mass readback carry the pinned repair
    # disclosure, rather than making users infer provenance from a separate log.
    from simscene.physics_binding import resolve_body_bindings
    stage = Usd.Stage.CreateInMemory()
    from pxr import UsdGeom
    UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    UsdGeom.Xform.Define(stage,'/World/door/Asset').GetPrim().GetReferences().AddReference(report['asset_path'])
    spec={'objects':{'door':{'kind':'asset','dynamic':True,'asset_path':report['asset_path'],
          'asset_binding':{'manifest_path':report['manifest_path'],'manifest_sha256':report['manifest_sha256']}}}}
    binding=resolve_body_bindings(stage,spec)['door']
    assert binding['native_repairs_ref']['manifest_sha256'] == report['manifest_sha256']
    assert {item['mass_provenance'] for item in binding['bodies'].values()} == {'explicit_experimental_assumption'}
    assert (tmp_path / 'prepared' / 'source' / source.name).read_bytes() == before
    json.loads((tmp_path / 'prepared' / 'manifest.json').read_text())
    # A self-consistent replacement manifest and new pin cannot relabel a
    # repaired source as a preservation-only package. Reinspect its hashed
    # source snapshot, not only the prepared USD and manifest assertions.
    manifest_path = tmp_path / 'prepared' / 'manifest.json'
    clean_bytes=manifest_path.read_bytes()
    forged=copy.deepcopy(manifest)
    forged['source_ref']['revision']='f'*40
    manifest_path.write_text(json.dumps(forged))
    spec['objects']['door']['asset_binding']['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='source attribution'):
        validate_asset_binding(spec['objects']['door']['asset_binding'])
    forged=copy.deepcopy(manifest)
    forged['parameters']['source_physics_policy']='preserve_valid'
    forged['parameters'].pop('native_physics_repairs')
    forged.pop('physics_repairs')
    forged['articulation_report']=inspect_articulation(prepared)
    forged['body_map']=forged['articulation_report']['body_map']
    forged['joint_map']=forged['articulation_report']['joint_map']
    manifest_path.write_text(json.dumps(forged))
    spec['objects']['door']['asset_binding']['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='source|mass'):
        resolve_body_bindings(stage,spec)
    forged=copy.deepcopy(manifest)
    forged['physics_repairs']['drives'][0]['source']['type']='force'
    manifest_path.write_text(json.dumps(forged))
    spec['objects']['door']['asset_binding']['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='source physics repair report'):
        resolve_body_bindings(stage,spec)
    manifest_path.write_bytes(clean_bytes)
    acquired_file=tmp_path/'prepared'/'source'/'acquired.json'
    acquired_before=acquired_file.read_bytes();altered_acquired=json.loads(acquired_before)
    altered_acquired['files']=altered_acquired['files'][:1];acquired_file.write_text(json.dumps(altered_acquired))
    forged=copy.deepcopy(manifest)
    row=next(item for item in forged['files'] if item['path']=='source/acquired.json')
    row.update(sha256=hashlib.sha256(acquired_file.read_bytes()).hexdigest(),size_bytes=acquired_file.stat().st_size)
    manifest_path.write_text(json.dumps(forged))
    spec['objects']['door']['asset_binding']['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='source acquisition'):
        validate_asset_binding(spec['objects']['door']['asset_binding'])
    acquired_file.write_bytes(acquired_before);manifest_path.write_bytes(clean_bytes)
    # A changed collider transform must not be treated as preserved collision
    # merely because its prim path and the updated file hash are consistent.
    derived_file=tmp_path/'prepared'/'derived'/'visual.usda'
    derived_before=derived_file.read_bytes()
    modified=Usd.Stage.Open(str(derived_file))
    collider=modified.GetPrimAtPath('/Native/Door/Collider')
    UsdGeom.Xformable(collider).AddTranslateOp().Set((10.,0.,0.))
    modified.GetRootLayer().Save()
    forged=copy.deepcopy(manifest)
    file_row=next(item for item in forged['files'] if item['path']=='derived/visual.usda')
    file_row.update(sha256=hashlib.sha256(derived_file.read_bytes()).hexdigest(),size_bytes=derived_file.stat().st_size)
    manifest_path.write_text(json.dumps(forged))
    spec['objects']['door']['asset_binding']['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='source|collision|physics'):
        resolve_body_bindings(stage,spec)
    derived_file.write_bytes(derived_before)
    modified.GetRootLayer().Reload()
    manifest_path.write_bytes(clean_bytes)
    # Re-hashing a changed source dependency cannot erase the frozen transfer
    # record, even when that particular dependency does not alter the graph.
    copied_dependency=tmp_path/'prepared'/'source'/'dependency.bin'
    original_dependency=copied_dependency.read_bytes();copied_dependency.write_bytes(b'replaced dependency')
    forged=copy.deepcopy(manifest)
    file_row=next(item for item in forged['files'] if item['path']=='source/dependency.bin')
    file_row.update(sha256=hashlib.sha256(copied_dependency.read_bytes()).hexdigest(),size_bytes=copied_dependency.stat().st_size)
    manifest_path.write_text(json.dumps(forged))
    spec['objects']['door']['asset_binding']['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='source.*(closure|attribution|acquisition)'):
        validate_asset_binding(spec['objects']['door']['asset_binding'])
    copied_dependency.write_bytes(original_dependency)
    manifest_path.write_bytes(clean_bytes)
    # Even if the local acquisition file list is also edited, its previously
    # recorded acquisition-manifest hash must still describe that exact list.
    copied_dependency.write_bytes(b'replaced dependency')
    modified_acquired=json.loads(acquired_before)
    dep_record=next(item for item in modified_acquired['files'] if item['path']=='dependency.bin')
    dep_record.update(sha256=hashlib.sha256(copied_dependency.read_bytes()).hexdigest(),size_bytes=copied_dependency.stat().st_size)
    acquired_file.write_text(json.dumps(modified_acquired))
    forged=copy.deepcopy(manifest)
    for name,path in [('source/dependency.bin',copied_dependency),('source/acquired.json',acquired_file)]:
        row=next(item for item in forged['files'] if item['path']==name)
        row.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    source_rows=[{'path':item['path'][len('source/'):],'sha256':item['sha256'],'size_bytes':item['size_bytes']}
                 for item in forged['files'] if item['path'].startswith('source/') and item['path']!='source/acquired.json']
    forged['source_closure_sha256']=hashlib.sha256(json.dumps(sorted(source_rows,key=lambda x:x['path']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    manifest_path.write_text(json.dumps(forged))
    spec['objects']['door']['asset_binding']['manifest_sha256']=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='source acquisition manifest'):
        validate_asset_binding(spec['objects']['door']['asset_binding'])
    copied_dependency.write_bytes(original_dependency);acquired_file.write_bytes(acquired_before);manifest_path.write_bytes(clean_bytes)
    # Scene admission cannot silently lose the derivation disclosures, even if
    # the caller pins a freshly recalculated hash of the altered manifest.
    manifest['physics_repairs']['masses'][0]['mass_kg'] = 99.
    manifest_path.write_text(json.dumps(manifest))
    altered_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='repair report'):
        validate_asset_binding({'manifest_path': str(manifest_path), 'manifest_sha256': altered_sha},
                               require_dynamic=True, asset_path=report['asset_path'])
