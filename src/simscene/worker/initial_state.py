"""Strict passive-task initialization and read-only physics tensor snapshots.

Isaac 6.2 physics setup advances two warmup steps. Restore initial state once,
while paused and before the task clock; never call setters during the task.
"""
import numpy as np

def capture_authored_state(stage, objects, body_bindings=None):
    """Capture world reset targets and local USD ops before any physics warmup."""
    from pxr import UsdGeom
    bindings=body_bindings or {};cache=UsdGeom.XformCache();bodies={}
    for name,obj in objects.items():
        if not obj.get('dynamic') or obj.get('spawn_step',0):continue
        paths=bindings.get(name,{}).get('motion_bodies') or [bindings.get(name,{}).get('motion_body','/World/'+name.replace('-','_'))]
        for path in paths:
            prim=stage.GetPrimAtPath(path)
            if not prim or not prim.IsActive():raise RuntimeError('authored initial body missing: '+path)
            matrix=cache.GetLocalToWorldTransform(prim).RemoveScaleShear();q=matrix.ExtractRotationQuat()
            position=list(matrix.ExtractTranslation());orientation=[q.GetReal(),*q.GetImaginary()]
            if not np.isfinite(position+orientation).all():raise RuntimeError('nonfinite authored initial pose')
            local={attr.GetName():{'type':attr.GetTypeName(),'value':attr.Get()}
                   for attr in prim.GetAttributes() if attr.GetName().startswith('xformOp:') or attr.GetName()=='xformOpOrder'}
            bodies[path]={'object_id':name,'position':position,'orientation_wxyz':orientation,'local_ops':local}
    return {'bodies':bodies,'phase':'before_sdk_warmup'}


def restore_local_ops(stage, authored_state):
    """Restore local defaults after tensor world reset; never author world translation."""
    from pxr import Usd
    for path,body in authored_state['bodies'].items():
        prim=stage.GetPrimAtPath(path);saved=body['local_ops']
        names=[attr.GetName() for attr in prim.GetAttributes() if attr.GetName().startswith('xformOp:') or attr.GetName()=='xformOpOrder']
        # Physics may introduce ops on the root/session layers during warmup.
        # Referenced source layers are deliberately never edited.
        for layer in stage.GetLayerStack():
            if layer.permissionToEdit:
                with Usd.EditContext(stage,layer):
                    for name in names:
                        if name not in saved:prim.RemoveProperty(name)
        for name,record in saved.items():
            attr=prim.GetAttribute(name) or prim.CreateAttribute(name,record['type'])
            if record['value'] is None:attr.Clear()
            else:attr.Set(record['value'])


def visual_bounds(stage, objects, body_bindings=None):
    """Fresh world bounds of mapped rendered roots for this exact observation."""
    from pxr import Usd,UsdGeom,Gf
    bindings=body_bindings or {};cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render]);result={}
    for name,obj in objects.items():
        if not obj.get('dynamic'):continue
        roots=bindings.get(name,{}).get('visual_roots',['/World/'+name.replace('-','_')])
        merged=Gf.Range3d()
        for path in roots:
            prim=stage.GetPrimAtPath(path)
            if not prim or not prim.IsActive():continue
            box=cache.ComputeWorldBound(prim).ComputeAlignedRange()
            if not box.IsEmpty():merged.UnionWith(box)
        if not merged.IsEmpty():result[name]={'min':list(merged.GetMin()),'max':list(merged.GetMax())}
    return result

class PassiveState:
    def __init__(self,stage,objects,body_bindings=None,authored_state=None):
        self.delegate=None
        if any(binding.get('articulation_roots') for binding in (body_bindings or {}).values()):
            from .mechanism import PreparedArticulationState
            self.delegate=PreparedArticulationState(stage,objects,body_bindings,authored_state)
            return
        import omni.physics.tensors as tensors
        import omni.usd
        self.stage=stage;self.objects=objects;self.body_bindings=body_bindings or {};self.authored_state=authored_state;self._reset_count=0
        self.sim=tensors.create_simulation_view('numpy',stage_id=omni.usd.get_context().get_stage_id());self.sim.set_subspace_roots('/')
        self.refresh()

    def refresh(self):
        if getattr(self,'delegate',None) is not None:return self.delegate.refresh()
        self.view=self.sim.create_rigid_body_view('/World/**' if self.body_bindings else '/World/*')
        self.paths=list(self.view.prim_paths)

    def read(self):
        if getattr(self,'delegate',None) is not None:return self.delegate.read()
        transforms=np.asarray(self.view.get_transforms()).copy();velocities=np.asarray(self.view.get_velocities()).copy()
        if not np.isfinite(transforms).all() or not np.isfinite(velocities).all():raise RuntimeError('non-finite physics tensor state')
        return {'positions':{p:[float(v) for v in transforms[i,:3]] for i,p in enumerate(self.paths)},
                'orientations_wxyz':{p:[float(transforms[i,6]),*[float(v) for v in transforms[i,3:6]]] for i,p in enumerate(self.paths)},
                'linear_velocities_m_s':{p:[float(v) for v in velocities[i,:3]] for i,p in enumerate(self.paths)},
                'angular_velocities_rad_s':{p:[float(v) for v in velocities[i,3:]] for i,p in enumerate(self.paths)}}

    def mass_properties(self,physics_step):
        """Read cooked mass properties, without changing the physical model.

        Omni Physics 110.4 tensors/api.py specifies the COM/principal frame
        relative to the rigid prim, and column-major inertia at the COM,
        expressed in rigid-prim axes. The stage uses metres and kilograms.
        """
        if getattr(self,'delegate',None) is not None:return self.delegate.mass_properties(physics_step)
        count=len(self.paths)
        masses=np.asarray(self.view.get_masses()).reshape(count)
        coms=np.asarray(self.view.get_coms()).reshape(count,7)
        inertias=np.asarray(self.view.get_inertias()).reshape(count,9)
        if not all(np.isfinite(v).all() for v in (masses,coms,inertias)) or np.any(masses<=0):
            raise RuntimeError('invalid cooked rigid-body mass properties')
        result={}
        for i,path in enumerate(self.paths):
            inertia=inertias[i].reshape(3,3,order='F')
            if not np.allclose(inertia,inertia.T,atol=1e-8,rtol=1e-5) or np.min(np.linalg.eigvalsh(inertia))<=0:
                raise RuntimeError('non-positive cooked rigid-body inertia: '+path)
            result[path]={'mass_kg':float(masses[i]),'center_of_mass_local_m':[float(v) for v in coms[i,:3]],
                          'principal_axes_local_wxyz':[float(coms[i,6]),*[float(v) for v in coms[i,3:6]]],
                          'inertia_at_com_in_prim_axes_kg_m2':[[float(v) for v in row] for row in inertia],
                          'observed_at_physics_step':physics_step,
                          'source':'PhysX tensor readback after cooking authored collision geometry and total mass; no explicit COM/inertia override'}
        return result

    def reset_before_task(self):
        if getattr(self,'delegate',None) is not None:return self.delegate.reset_before_task()
        if self._reset_count:raise RuntimeError('strict initialization reset may run only once')
        if self.authored_state is None:
            if self.body_bindings:raise RuntimeError('nested strict reset requires pre-warmup authored state')
            self.authored_state=capture_authored_state(self.stage,self.objects)
            from pxr import Gf,Sdf
            self.authored_state['phase']='legacy_primitive_spec_pose'
            for body in self.authored_state['bodies'].values():
                obj=self.objects[body['object_id']];body['position']=obj.get('position',[0,0,0]);body['orientation_wxyz']=obj.get('orientation_wxyz',[1,0,0,0]);q=body['orientation_wxyz']
                body['local_ops']['xformOp:translate']={'type':Sdf.ValueTypeNames.Double3,'value':Gf.Vec3d(*body['position'])}
                body['local_ops']['xformOp:orient']={'type':Sdf.ValueTypeNames.Quatf,'value':Gf.Quatf(q[0],Gf.Vec3f(*q[1:]))}
        expected=self.authored_state['bodies']
        if set(self.paths)!=set(expected):raise RuntimeError('strict initialization body set does not match explicit authored motion bodies')
        transforms=np.asarray(self.view.get_transforms()).copy()
        for i,path in enumerate(self.paths):
            obj=expected[path];q=obj['orientation_wxyz'];transforms[i,:3]=obj['position'];transforms[i,3:]=[*q[1:],q[0]]
        indices=np.arange(len(self.paths),dtype=np.uint32)
        self.view.set_transforms(np.asarray(transforms,dtype=np.float32),indices)
        self.view.set_velocities(np.zeros((len(self.paths),6),dtype=np.float32),indices)
        restore_local_ops(self.stage,self.authored_state)
        self._reset_count=1
        observed=self.read();position_error=0.;rotation_error=0.;orientation_degrees=0.;linear_speed=0.;angular_speed=0.;speed=0.
        for path,obj in expected.items():
            position_error=max(position_error,float(np.linalg.norm(np.asarray(observed['positions'][path])-obj.get('position',[0,0,0]))))
            a=np.asarray(observed['orientations_wxyz'][path]);b=np.asarray(obj.get('orientation_wxyz',[1,0,0,0]));rotation_error=max(rotation_error,float(min(np.linalg.norm(a-b),np.linalg.norm(a+b))))
            orientation_degrees=max(orientation_degrees,float(np.degrees(2*np.arccos(min(1.,abs(np.dot(a/np.linalg.norm(a),b/np.linalg.norm(b))))))))
            linear_speed=max(linear_speed,float(np.linalg.norm(observed['linear_velocities_m_s'][path])))
            angular_speed=max(angular_speed,float(np.linalg.norm(observed['angular_velocities_rad_s'][path])))
            speed=max(speed,float(np.linalg.norm(observed['linear_velocities_m_s'][path])),float(np.linalg.norm(observed['angular_velocities_rad_s'][path])))
        if position_error>1e-6 or rotation_error>1e-6 or speed>1e-7:raise RuntimeError('strict initial state readback mismatch')
        return {'applied':True,'phase':'before_task_start','reset_count':1,'body_ids':[obj['object_id'] for obj in expected.values()],'authored_pose_capture_phase':self.authored_state['phase'],'local_xform_ops_restored':True,'authored_world_poses':{path:{'position_m':body['position'],'orientation_wxyz':body['orientation_wxyz']} for path,body in expected.items()},'restored_local_xform_op_names':{path:sorted(body['local_ops']) for path,body in expected.items()},'body_paths':self.paths,'authored_pose_readback_max_error_m':position_error,'authored_orientation_readback_max_error_degrees':orientation_degrees,'max_linear_speed_m_s':linear_speed,'max_angular_speed_rad_s':angular_speed,'max_quaternion_error':rotation_error,'setters_during_task':False,'scope':'One initialization reset after SDK warmup, before the task clock. No scheduled downstream motion or later resets.'}
