"""Rigid USD hierarchy attachments for acquired, purely visual asset meshes.

The parent carries mass/colliders/joints. No runtime transform follower exists.
"""
import copy

def prim_path(scene,name):
    obj=scene['objects'][name];attachment=obj.get('rigid_attachment')
    root='/World/'+name.replace('-','_')
    if attachment:
        root='/World/'+attachment['body'].replace('-','_')+'/_visuals/'+name.replace('-','_')
    return root

def world_object(scene,obj):
    """Resolve an authored local visual pose for measurement, without mutation."""
    result=copy.deepcopy(obj);attachment=result.pop('rigid_attachment',None)
    if attachment is None:return result
    from .placement import rotate
    parent=scene['objects'][attachment['body']]
    a=parent.get('orientation_wxyz',[1,0,0,0]);b=result.get('orientation_wxyz',[1,0,0,0])
    offset=rotate(a,result.get('position',[0,0,0]))
    result['position']=[x+y for x,y in zip(parent.get('position',[0,0,0]),offset)]
    w,x,y,z=a;v,i,j,k=b
    result['orientation_wxyz']=[w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v]
    return result

def validate_attachment(scene,obj):
    cfg=obj.get('rigid_attachment')
    if not isinstance(cfg,dict) or set(cfg)!={'body'} or not isinstance(cfg['body'],str):
        return ['rigid_attachment requires exactly a parent body ID']
    parent=scene['objects'].get(cfg['body'],{})
    if not isinstance(parent,dict) or parent.get('kind')!='compound' or not parent.get('dynamic') or parent.get('spawn_step',0):
        return ['rigid_attachment requires an initially present dynamic compound parent']
    if obj.get('kind')!='asset' or obj.get('asset_physics')!='visual_only' or obj.get('asset_lights')!='disabled' or obj.get('pose_follower') or obj.get('spawn_step',0):
        return ['attached assets require visual_only physics, disabled asset lights and no controller or scheduled spawn']
    return []

def sample_world(stage,scene):
    """Read rendered hierarchy poses. This function never writes transforms."""
    from pxr import UsdGeom
    cache=UsdGeom.XformCache();result={}
    for name,obj in scene['objects'].items():
        attachment=obj.get('rigid_attachment')
        if not attachment:continue
        body=attachment['body'];visual=stage.GetPrimAtPath(prim_path(scene,name));parent=stage.GetPrimAtPath(prim_path(scene,body))
        if not visual or not parent:raise RuntimeError('missing rigid visual hierarchy: '+name)
        def pose(prim):
            matrix=cache.GetLocalToWorldTransform(prim);q=matrix.RemoveScaleShear().ExtractRotationQuat()
            return {'position_m':list(matrix.ExtractTranslation()),'orientation_wxyz':[q.GetReal(),*q.GetImaginary()]}
        result[name]={'body_id':body,'prim_path':str(visual.GetPath()),'world_pose':pose(visual),'parent_render_world_pose':pose(parent),'scope':'USD hierarchy readback; source-axis/unit normalization is included, no independent body or runtime follower'}
    return result
