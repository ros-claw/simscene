"""Read passive joint coordinates from measured body transforms; never actuate."""
import math

def geometry_settings():
    """Read the actual backend's cylinder representation without changing it."""
    import carb
    from omni.physx.bindings import _physx
    key=getattr(_physx,'SETTING_COLLISION_APPROXIMATE_CYLINDERS',None)
    value=carb.settings.get_settings().get(key) if key else None
    return {'cylinder_setting_available':type(value) is bool,'approximate_cylinders_with_convex_meshes':value,'setting_path':key}

def configuration(stage,objects):
    """Read actual loaded schemas/settings once, before task physics starts."""
    from pxr import UsdPhysics,PhysxSchema
    bodies={};joints=[]
    names={'linear_damping':'linearDamping','angular_damping':'angularDamping','sleep_threshold':'sleepThreshold','solver_position_iterations':'solverPositionIterationCount','solver_velocity_iterations':'solverVelocityIterationCount','enable_ccd':'enableCCD'}
    for name,obj in objects.items():
        if not obj.get('physics'):continue
        prim=stage.GetPrimAtPath('/World/'+name.replace('-','_'));actual={}
        if not prim and obj.get('spawn_step',0)>0:continue
        if not prim:raise RuntimeError('passive body missing: '+name)
        if any(k in obj['physics'] for k in names) and not prim.HasAPI(PhysxSchema.PhysxRigidBodyAPI):raise RuntimeError('PhysX body schema not loaded: '+name)
        for key,attribute in names.items():
            if key not in obj['physics']:continue
            value=prim.GetAttribute('physxRigidBody:'+attribute).Get();wanted=obj['physics'][key]
            if value is None or abs(float(value)-float(wanted))>1e-5:raise RuntimeError('passive physics setting not applied: '+name+' '+key)
            actual[key]=value
        bodies[name]=actual
    for prim in stage.Traverse():
        if not prim.IsA(UsdPhysics.Joint):continue
        api=UsdPhysics.Joint(prim)
        record={'path':str(prim.GetPath()),'type':prim.GetTypeName(),'enabled':api.GetJointEnabledAttr().Get(),'body0':[str(p) for p in api.GetBody0Rel().GetTargets()],'body1':[str(p) for p in api.GetBody1Rel().GetTargets()],'drives':[s for s in prim.GetAppliedSchemas() if 'DriveAPI' in s],'drive_attributes':[a.GetName() for a in prim.GetAttributes() if a.GetName().startswith('drive:')]}
        if prim.GetTypeName()=='PhysicsJoint':
            from simscene.d6 import read_limits,read_frames
            record.update(read_limits(prim));record.update(read_frames(prim))
        joints.append(record)
    for name,obj in objects.items():
        cfg=obj.get('joint',{})
        if cfg.get('type')!='d6':continue
        prim=stage.GetPrimAtPath('/World/'+name.replace('-','_'))
        from simscene.d6 import validate_loaded
        validate_loaded(prim,cfg)
    needs_ccd=any(obj.get('physics',{}).get('enable_ccd') for obj in objects.values())
    scene=stage.GetPrimAtPath('/World/PhysicsScene');ccd=scene.GetAttribute('physxScene:enableCCD').Get() if scene else None
    if needs_ccd and ccd is not True:raise RuntimeError('CCD requested on a body but not enabled on the physics scene')
    return {'body_settings':bodies,'joints':joints,'scene_enable_ccd':ccd,'geometry_settings':geometry_settings(),'scope':'Loaded USD/PhysX passive settings and joint inventory; observed coordinates are derived separately from simulated transforms.'}

def sample(stage,objects,previous=None,native_state=None):
    from pxr import UsdGeom,Gf
    cache=UsdGeom.XformCache();result={};previous=previous or {}
    for name,obj in objects.items():
        if obj.get('kind')!='joint':continue
        cfg=obj['joint'];frames=[]
        prim=stage.GetPrimAtPath('/World/'+name.replace('-','_'))
        actual=None
        if cfg['type']=='d6':
            from simscene.d6 import read_frames,read_limits
            actual={**read_frames(prim),**read_limits(prim)}
        for i in (0,1):
            body=cfg.get('body'+str(i));matrix=Gf.Matrix4d(1)
            body_path=(actual['body_paths'][i][0] if actual['body_paths'][i] else None) if actual is not None else ('/World/'+body.replace('-','_') if body else None)
            if actual is not None and native_state is not None:
                position=Gf.Vec3d(0);body_rotation=Gf.Quatd(1)
                if body_path:
                    if body_path not in native_state.get('positions',{}) or body_path not in native_state.get('orientations_wxyz',{}):
                        raise RuntimeError('D6 body missing from same-sample physics tensors: '+body_path)
                    from simscene.d6 import measured_pose_valid
                    body_position=native_state['positions'][body_path];nq=native_state['orientations_wxyz'][body_path]
                    if not measured_pose_valid(body_position,nq):raise RuntimeError('D6 endpoint physics tensor pose is invalid: '+body_path)
                    position=Gf.Vec3d(*body_position)
                    body_rotation=Gf.Quatd(nq[0],Gf.Vec3d(*nq[1:]))
                point=position+body_rotation.Transform(Gf.Vec3d(*actual['local_positions_m'][i]))
                q=actual['local_rotations_wxyz'][i];rotation=body_rotation*Gf.Quatd(q[0],Gf.Vec3d(*q[1:]))
                frames.append((point,rotation));continue
            if body_path:
                body_prim=stage.GetPrimAtPath(body_path)
                if not body_prim:raise RuntimeError('joint body missing: '+body_path)
                matrix=cache.GetLocalToWorldTransform(body_prim).RemoveScaleShear()
            point=matrix.Transform(Gf.Vec3d(*(actual['local_positions_m'][i] if actual is not None else cfg.get('local_pos'+str(i),[0,0,0]))))
            q=actual['local_rotations_wxyz'][i] if actual is not None else cfg.get('local_rot'+str(i)+'_wxyz',[1,0,0,0]);rotation=matrix.ExtractRotationQuat()*Gf.Quatd(q[0],Gf.Vec3d(*q[1:]))
            frames.append((point,rotation))
        p0,q0=frames[0];p1,q1=frames[1];difference=p1-p0
        values={'type':cfg['type'],'enabled':cfg.get('enabled',True),'anchor0_world_m':list(p0),'anchor1_world_m':list(p1),'drive_present':False}
        if cfg['type'] in ('revolute','prismatic'):
            axis=('X','Y','Z').index(cfg.get('axis','X'));unit=Gf.Vec3d(*[float(i==axis) for i in range(3)]);world_axis=q0.Transform(unit)
            if cfg['type']=='prismatic':
                coordinate=Gf.Dot(difference,world_axis);values.update(position_m=coordinate,anchor_error_m=float((difference-world_axis*coordinate).GetLength()))
            else:
                relative=q0.GetInverse()*q1;angle=math.degrees(2*math.atan2(relative.GetImaginary()[axis],relative.GetReal()));angle=(angle+180)%360-180
                last=previous.get(name,{}).get('angle_degrees',angle);angle=last+(angle-last+180)%360-180
                values.update(angle_degrees=angle,anchor_error_m=float(difference.GetLength()))
        elif cfg['type']=='d6':
            from simscene.d6 import relative_observation
            relative=q0.GetInverse()*q1
            values.update(relative_observation(list(q0.GetInverse().Transform(difference)),
                [relative.GetReal(),*relative.GetImaginary()],actual['dof_limits']))
            values['enabled']=actual['enabled']
            values['pose_source']='same_sample_PhysX_rigid_body_tensors' if native_state is not None else 'loaded_USD_body_xforms'
        else:values['anchor_error_m']=float(difference.GetLength())
        prim=stage.GetPrimAtPath('/World/'+name.replace('-','_'))
        values['drive_present']=any('DriveAPI' in value for value in prim.GetAppliedSchemas()) or any(attr.GetName().startswith('drive:') for attr in prim.GetAttributes())
        result[name]=values
    return result
