"""Two-coordinate assets must prepare and bind without changing v1 semantics."""
import hashlib

import pytest

from simscene.preparation.profiles import PreparationError, validate_parameters


def parameters():
    return {'source_physics_policy':'preserve_valid','collision_method':'preserve','proxy_tolerance_m':.002}


def source_stage():
    from test_articulation_v2 import TwoDofInspectionTests
    from pxr import UsdGeom
    stage=TwoDofInspectionTests().stage()
    mesh=UsdGeom.Mesh.Define(stage,'/Asset/Visual')
    mesh.CreatePointsAttr([(0,0,0),(1,0,0),(0,1,0),(0,0,1)])
    mesh.CreateFaceVertexCountsAttr([3,3,3,3])
    mesh.CreateFaceVertexIndicesAttr([0,2,1,0,1,3,0,3,2,1,2,3])
    return stage


def test_two_dof_profile_is_preserve_only_and_has_distinct_identity():
    from simscene.preparation.profiles import preparation_key
    p=validate_parameters('articulated_prop_v2',parameters())
    assert p['source_physics_policy']=='preserve_valid'
    target={'engine':'physx','version':'fixture'}
    assert preparation_key('a'*64,'articulated_prop_v2',parameters(),target,{'backend':'usd'}) != \
           preparation_key('a'*64,'articulated_prop_v1',parameters(),target,{'backend':'usd'})
    with pytest.raises(PreparationError):
        validate_parameters('articulated_prop_v2',dict(parameters(),source_physics_policy='repair_explicit'))


def test_two_dof_package_preserves_source_and_binds_both_joints(tmp_path,monkeypatch):
    import pxr
    from pxr import Usd,UsdGeom
    from simscene.preparation.usd_layers import prepare_acquired
    from simscene.physics_binding import resolve_body_bindings,validate_asset_binding
    from simscene.scene import validate
    stage=source_stage();source=tmp_path/'source.usda';stage.GetRootLayer().Export(str(source));before=source.read_bytes()
    acquired={'root':str(source),'source_ref':{'source_id':'fixture','asset_id':'tree','revision':'v1'},
              'files':[{'path':source.name,'sha256':hashlib.sha256(before).hexdigest(),'size_bytes':len(before)}]}
    monkeypatch.setattr(pxr,'PhysxSchema',object(),raising=False)
    report=prepare_acquired(acquired,'articulated_prop_v2',parameters(),{'engine':'physx','usd_version':'.'.join(map(str,Usd.GetVersion()))},tmp_path/'package')
    assert source.read_bytes()==before
    manifest=validate_asset_binding({'manifest_path':report['manifest_path'],'manifest_sha256':report['manifest_sha256']},require_dynamic=True,asset_path=report['asset_path'])
    assert manifest['profile_id']=='articulated_prop_v2' and len(manifest['joint_map'])==2
    assert manifest['runtime_validation']['status']=='not_run'
    composed=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(composed,1.);UsdGeom.SetStageUpAxis(composed,UsdGeom.Tokens.z)
    UsdGeom.Xform.Define(composed,'/World/asset/Asset').GetPrim().GetReferences().AddReference(report['asset_path'])
    obj={'kind':'asset','asset_path':report['asset_path'],'asset_binding':{'manifest_path':report['manifest_path'],'manifest_sha256':report['manifest_sha256']},'dynamic':True,'position':[0,0,0]}
    config={'commands':[{'joint_id':'joint1','trigger':{'type':'at_step','physics_step':0},'target_position':.25,'position_unit':'m','stiffness':12.,'damping':4.,'max_effort':150.}]}
    obj['mechanism']=config
    scene={'scene_id':'test','revision':1,'objects':{'asset':obj},'observation':{'strict_start':True,'sample_interval_steps':1}}
    assert validate(scene)==[]
    binding=resolve_body_bindings(composed,scene)['asset']
    assert binding['profile_id']=='articulated_prop_v2' and len(binding['motion_bodies'])==3
    assert binding['root_body'].endswith('/Links/Base')
    assert {j['joint_path'].split('/')[-1] for j in binding['joints'].values()}=={'Hinge','Slide'}
    slide=next(j for j in binding['joints'].values() if j['type']=='prismatic')
    assert slide['drive']['max_effort']==150. and slide['drive']['stiffness']==12.


def test_two_dof_runtime_rejects_unbounded_or_acceleration_source_drive():
    from pxr import UsdPhysics
    from simscene.preparation.articulation_v2 import runtime_joint
    from simscene.preparation.articulation_v2 import inspect_articulation_v2
    stage=source_stage();drive=UsdPhysics.DriveAPI(stage.GetPrimAtPath('/Asset/Joints/Slide'),'linear')
    for value in ('acceleration','infinity'):
        if value=='acceleration':drive.GetTypeAttr().Set('acceleration')
        else:drive.GetTypeAttr().Set('force');drive.GetMaxForceAttr().Set(float('inf'))
        graph=inspect_articulation_v2(stage)
        with pytest.raises(PreparationError):runtime_joint(graph['joint_map']['joint1'])


def test_two_dof_preparation_rejects_unmapped_static_colliders(tmp_path,monkeypatch):
    import pxr
    from pxr import Usd,UsdGeom,UsdPhysics
    from simscene.preparation.usd_layers import prepare_acquired
    stage=source_stage();box=UsdGeom.Cube.Define(stage,'/Asset/UnownedCollider')
    UsdPhysics.CollisionAPI.Apply(box.GetPrim())
    source=tmp_path/'source.usda';stage.GetRootLayer().Export(str(source));payload=source.read_bytes()
    acquired={'root':str(source),'files':[{'path':source.name,'sha256':hashlib.sha256(payload).hexdigest(),'size_bytes':len(payload)}]}
    monkeypatch.setattr(pxr,'PhysxSchema',object(),raising=False)
    with pytest.raises(PreparationError,match='static collider'):
        prepare_acquired(acquired,'articulated_prop_v2',parameters(),{'engine':'physx','usd_version':'.'.join(map(str,Usd.GetVersion()))},tmp_path/'package')


def test_two_dof_fixed_world_frame_cannot_be_silently_changed(tmp_path):
    from pxr import Gf,Usd,UsdGeom,UsdPhysics
    from simscene.preparation.articulation_v2 import inspect_articulation_v2,resolve_instance_v2
    source=source_stage();fixed=UsdPhysics.FixedJoint.Define(source,'/Asset/Joints/Anchor')
    fixed.CreateBody1Rel().SetTargets(['/Asset/Links/Base']);p=tmp_path/'source.usda';source.GetRootLayer().Export(str(p))
    stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    anchor=UsdGeom.Xform.Define(stage,'/World/object/Asset').GetPrim()
    UsdGeom.Xform.Define(stage,'/World/object/Asset/Native').GetPrim().GetReferences().AddReference(str(p))
    manifest={'articulation_report':inspect_articulation_v2(stage,anchor)}
    assert resolve_instance_v2(stage,anchor,manifest)['root_body'].endswith('/Links/Base')
    joint=UsdPhysics.Joint(stage.GetPrimAtPath('/World/object/Asset/Native/Joints/Anchor'))
    joint.CreateLocalPos0Attr(Gf.Vec3f(10,0,0))
    with pytest.raises(PreparationError,match='world.*anchor'):
        resolve_instance_v2(stage,anchor,manifest)


def test_two_dof_world_anchor_follows_explicit_rigid_instance_placement(tmp_path):
    from pxr import Gf,Usd,UsdGeom,UsdPhysics
    from simscene.preparation.articulation import transform_world_anchors
    from simscene.preparation.articulation_v2 import inspect_articulation_v2,resolve_instance_v2
    source=source_stage();fixed=UsdPhysics.FixedJoint.Define(source,'/Asset/Joints/Anchor')
    fixed.CreateBody1Rel().SetTargets(['/Asset/Links/Base']);p=tmp_path/'source.usda';source.GetRootLayer().Export(str(p))
    stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage,1.);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    parent=UsdGeom.Xform.Define(stage,'/World/object');anchor=UsdGeom.Xform.Define(stage,'/World/object/Asset').GetPrim()
    UsdGeom.Xform.Define(stage,'/World/object/Asset/Native').GetPrim().GetReferences().AddReference(str(p))
    manifest={'articulation_report':inspect_articulation_v2(stage,anchor)}
    parent.AddTranslateOp().Set(Gf.Vec3d(1,2,3));parent.AddRotateZOp().Set(35.)
    transform_world_anchors(stage,anchor)
    assert resolve_instance_v2(stage,anchor,manifest)['root_body'].endswith('/Links/Base')
