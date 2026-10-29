"""Experimental cuMotion pose-follow controller for an Isaac worker.

This module is loaded only inside Isaac after SimulationApp starts. Optional
reactive planning against specified static obstacles does not validate a
complete path; independent physical evidence remains necessary.
"""
class PoseFollower:
    @staticmethod
    def _inside_workspace(position, phase):
        import math
        if not all(math.isfinite(float(value)) for value in position):return False
        if 'workspace_min' not in phase:return True
        return all(lo<=float(value)<=hi for value,lo,hi in zip(position,phase['workspace_min'],phase['workspace_max']))
    def __init__(self, prim_path, config):
        import numpy as np
        from isaacsim.core.experimental.prims import Articulation
        self.config=config
        self.prim_path=prim_path
        self.robot=Articulation(prim_path)
        self.names=self.robot.dof_names
        self._last_root_pose=None

    def initialize(self):
        import numpy as np
        import warp as wp
        import isaacsim.robot_motion.experimental.motion_generation as mg
        from isaacsim.core.experimental.prims import GeomPrim
        from isaacsim.robot_motion.cumotion import load_cumotion_robot,CumotionWorldInterface,RmpFlowController
        self.wp=wp; self.mg=mg
        initial=self.robot.get_dof_positions().numpy().reshape(-1).copy()
        for name,value in self.config.get('initial_joints',{}).items():
            if name not in self.names: raise ValueError(f'joint not found: {name}')
            initial[self.names.index(name)]=value
        self.robot.set_default_state(dof_positions=initial.tolist())
        self.robot.reset_to_default_state()
        import omni.kit.app
        omni.kit.app.get_app().update()
        observed=self.robot.get_dof_positions().numpy().reshape(-1)
        self.initial_joint_positions={name:float(observed[index]) for index,name in enumerate(self.names)}
        self.model=load_cumotion_robot(directory=self.config['model_directory'])
        self.arm_drive_gains=None
        if self.config.get('arm_drives_enabled',True) is False:
            indices=[self.names.index(name) for name in self.model.controlled_joint_names]
            self.robot.set_dof_gains(stiffnesses=0.,dampings=0.,dof_indices=indices)
            stiffness,damping=self.robot.get_dof_gains(dof_indices=indices)
            self.arm_drive_gains={'joint_names':list(self.model.controlled_joint_names),
                                  'stiffness':stiffness.numpy().reshape(-1).tolist(),
                                  'damping':damping.numpy().reshape(-1).tolist()}
            if any(abs(value)>1e-6 for values in (self.arm_drive_gains['stiffness'],self.arm_drive_gains['damping']) for value in values):
                raise RuntimeError('could not disable all requested arm drives')
        self.tool=self.config['tool_frame']
        if self.tool not in self.model.robot_description.tool_frame_names(): raise ValueError('tool_frame not present in model')
        self.tcp=GeomPrim(self.prim_path+'/'+self.config['tcp_prim'])
        self.tracked_obstacles=['/World/'+name.replace('-', '_') for name in self.config.get('avoid_obstacles',[])]
        strategy=mg.ObstacleStrategy()
        if self.tracked_obstacles:
            import omni.usd
            from pxr import UsdPhysics
            stage=omni.usd.get_context().get_stage()
            for path in self.tracked_obstacles:
                prim=stage.GetPrimAtPath(path)
                if not prim or not prim.HasAPI(UsdPhysics.CollisionAPI):
                    raise ValueError(f'obstacle has no collision shape: {path}')
            strategy.set_default_safety_tolerance(float(self.config.get('obstacle_margin_m',.01)))
        self.binding=mg.WorldBinding(world_interface=CumotionWorldInterface(),obstacle_strategy=strategy,tracked_prims=self.tracked_obstacles,tracked_collision_api=mg.TrackableApi.PHYSICS_COLLISION)
        self.binding.initialize();self._sync()
        self.controller=RmpFlowController(cumotion_robot=self.model,cumotion_world_interface=self.binding.get_world_interface(),robot_joint_space=self.names,robot_site_space=[self.tool],tool_frame=self.tool)
        self.controller.get_rmp_flow_config().set_param('cspace_target_rmp/metric_scalar',1.)
        if 'max_joint_speed' in self.config:
            self.controller.get_rmp_flow_config().set_param('joint_velocity_cap_rmp/max_velocity',self.config['max_joint_speed'])
        _, raw_orientation=self.tcp.get_world_poses()
        w,x,y,z=raw_orientation.numpy()[0]
        a,b,c,d=self.config.get('tcp_orientation_wxyz',[1,0,0,0])
        rotated=[w*a-x*b-y*c-z*d,w*b+x*a+y*d-z*c,w*c-x*d+y*a+z*b,w*d+x*c-y*b+z*a]
        self.orientation=wp.array([rotated],dtype=wp.float32)
        self.initial=self._tcp_position().tolist()
        self.target=np.asarray(self.config['target_position'],dtype=np.float32)
        if not self.controller.reset(self._state(),self._setpoint(),t=0.0): raise RuntimeError('RMPflow reset failed')
        self.suction=None
        if 'suction' in self.config:
            from isaacsim.robot.surface_gripper import GripperView, _surface_gripper
            _surface_gripper.acquire_surface_gripper_interface().set_write_to_usd(True)
            cfg=self.config['suction']; force=cfg.get('force_limit',100.)
            self.suction=GripperView(paths=self.prim_path+'/'+cfg['prim'],max_grip_distance=[cfg.get('max_grip_distance',.02)],coaxial_force_limit=[force],shear_force_limit=[force],retry_interval=[1.])
            if self.config.get('suction_enabled',True) is False:
                self.suction.apply_gripper_action([-.5])
        self.sequence=self.config.get('sequence',[])
        self.sequence_index=0
        self.phase_steps=0
        self.grip_commands=None
        self.sequence_error=None
        self.expected_gripped=None
        self.suction_events=[]
        self.transitions=[{'index':0,'physics_step':0}] if self.sequence else []
        self._new_phase()

    def _tcp_position(self):
        import numpy as np
        position, orientation=self.tcp.get_world_poses()
        q=orientation.numpy()[0]; vector=np.asarray(self.config.get('tcp_offset',[0,0,0]),dtype=np.float32)
        rotated=vector+2*np.cross(q[1:],np.cross(q[1:],vector)+q[0]*vector)
        return position.numpy()[0]+rotated

    def _object_position(self, object_id):
        import numpy as np
        import omni.usd
        from simscene.worker.object_pose import position
        return np.asarray(position(omni.usd.get_context().get_stage(),object_id),dtype=np.float32)

    def _sync(self):
        import numpy as np
        pose=self.robot.get_world_poses()
        current=(pose[0].numpy().copy(),pose[1].numpy().copy())
        if self._last_root_pose is None or any(not np.allclose(a,b,rtol=0,atol=1e-6) for a,b in zip(current,self._last_root_pose)):
            self.binding.get_world_interface().update_world_to_robot_root_transforms(pose)
            self._last_root_pose=current
        self.binding.synchronize_transforms()

    def _state(self):
        mg=self.mg
        return mg.RobotState(joints=mg.JointState.from_name(robot_joint_space=self.names,positions=(self.names,self.robot.get_dof_positions()),velocities=(self.names,self.robot.get_dof_velocities())))

    def _setpoint(self):
        return self.mg.RobotState(sites=self.mg.SpatialState.from_name(spatial_space=[self.tool],positions=([self.tool],self.wp.array([self.target.tolist()],dtype=self.wp.float32)),orientations=([self.tool],self.orientation)))

    def _new_phase(self):
        import numpy as np
        if self.sequence_index >= len(self.sequence): return
        phase=self.sequence[self.sequence_index]
        self.phase_steps=0
        self.settled_steps=0
        if 'max_joint_speed' in self.config:
            limit=phase.get('rmp_max_joint_speed',self.config['max_joint_speed'])
            self.controller.get_rmp_flow_config().set_param('joint_velocity_cap_rmp/max_velocity',limit)
        if phase['type'] in ('move','track'):
            if 'object' in phase:
                self.track_object=phase['object']
                position=self._object_position(self.track_object)
                if not self._inside_workspace(position,phase):
                    self.sequence_error=f'object outside workspace in phase {self.sequence_index}';return
                self.target=position+np.asarray(phase['offset'],dtype=np.float32)
            else:
                self.target=np.asarray(phase['position'],dtype=np.float32)
            if not self.controller.reset(self._state(),self._setpoint(),t=0.0): raise RuntimeError('RMPflow reset failed')
        if phase['type']=='gripper' or (phase['type']=='track' and 'gripper_value' in phase):
            value=phase['value'] if phase['type']=='gripper' else phase['gripper_value']
            if self.suction is not None:
                if value<0 or self.config.get('suction_enabled',True):
                    self.suction.apply_gripper_action([value])
            else:
                from simscene.robotics.gripper import coupled_commands
                commands=coupled_commands(self.config['gripper_urdf'],self.config['gripper_joint'],value,self.config.get('gripper_mapping'))
                self.grip_commands=([self.names.index(name) for name in commands], np.asarray(list(commands.values()),dtype=np.float32))

    def step(self, t):
        import numpy as np
        if self.sequence_error: return
        if self.sequence and self.sequence_index >= len(self.sequence): return
        if self.suction is not None and self.expected_gripped and self.sequence:
            phase=self.sequence[self.sequence_index]
            releasing=phase['type']=='gripper' and phase['value']<0
            if not releasing and self.expected_gripped not in [str(x) for x in self.suction.get_gripped_objects()[0]]:
                self.sequence_error=f'suction lost {self.expected_gripped}'
                self.suction_events.append({'event':'lost','object':self.expected_gripped,'physics_step':round(t*60)})
                return
        if self.sequence and self.sequence[self.sequence_index]['type']=='wait_object':
            import omni.usd
            from pxr import UsdGeom
            phase=self.sequence[self.sequence_index]
            path='/World/'+phase['object'].replace('-', '_')
            prim=omni.usd.get_context().get_stage().GetPrimAtPath(path)
            self.phase_steps+=1
            if prim:
                pos=UsdGeom.XformCache().GetLocalToWorldTransform(prim).ExtractTranslation()
                value=pos[('x','y','z').index(phase['axis'])]
                if phase['minimum']<=value<=phase['maximum'] and self._inside_workspace(pos,phase):
                    self.sequence_index+=1
                    self.transitions.append({'index':self.sequence_index,'physics_step':round(t*60)})
                    self._new_phase()
                    return
            if self.phase_steps>=phase['max_steps']:self.sequence_error=f'wait_object phase {self.sequence_index} timed out'
            return
        self._sync()
        if self.sequence and self.sequence[self.sequence_index]['type']=='track':
            phase=self.sequence[self.sequence_index]
            position=self._object_position(self.track_object)
            if not self._inside_workspace(position,phase):
                self.sequence_error=f'object outside workspace in phase {self.sequence_index}';return
            self.target=position+np.asarray(phase['offset'],dtype=np.float32)
        desired=self.controller.forward(self._state(),self._setpoint(),self.phase_steps/60.0 if self.sequence else t)
        if desired is not None and desired.joints.positions is not None:
            self.robot.set_dof_position_targets(positions=desired.joints.positions,dof_indices=desired.joints.position_indices)
        if self.grip_commands:
            indices,values=self.grip_commands
            self.robot.set_dof_position_targets(positions=values,dof_indices=indices)
        if not self.sequence: return
        phase=self.sequence[self.sequence_index]
        self.phase_steps+=1
        done=False
        if phase['type']=='gripper':
            done=self.phase_steps >= phase['steps']
            if done and self.suction is not None:
                gripped=[str(x) for x in self.suction.get_gripped_objects()[0]]
                self.suction_events.append({'event':'close' if phase['value']>0 else 'open','gripped':gripped,'status':int(self.suction.get_surface_gripper_status()[0]),'physics_step':round(t*60)})
                expected='/World/'+phase['required_object'].replace('-', '_') if phase.get('required_object') else None
                if phase['value']>0 and expected and expected not in gripped:
                    self.sequence_error=f'suction did not acquire {expected}'; done=False
                elif phase['value']<0 and gripped:
                    self.sequence_error='suction did not release objects'; done=False
                elif phase['value']<0:
                    self.expected_gripped=None
                elif expected:
                    self.expected_gripped=expected
        elif phase['type']=='track' and self.phase_steps >= phase['steps']:
            position=self._tcp_position()
            error=float(np.linalg.norm(position-self.target))
            if error > phase.get('max_tracking_error_m',.03):
                self.sequence_error=f'track phase {self.sequence_index} alignment error {error:.4f} m'
            elif self.suction is not None and phase.get('required_object'):
                expected='/World/'+phase['required_object'].replace('-', '_')
                gripped=[str(x) for x in self.suction.get_gripped_objects()[0]]
                self.suction_events.append({'event':'close','gripped':gripped,'status':int(self.suction.get_surface_gripper_status()[0]),'physics_step':round(t*60)})
                if expected not in gripped: self.sequence_error=f'suction did not acquire {expected}'
                else: self.expected_gripped=expected;done=True
            else: done=True
        elif phase['type']=='move':
            position=self._tcp_position()
            error=float(np.linalg.norm(position-self.target))
            settled=error <= phase.get('tolerance_m',.02)
            if 'max_joint_speed' in phase:
                velocities=self.robot.get_dof_velocities().numpy().reshape(-1)
                settled=settled and max(abs(velocities[self.names.index(n)]) for n in self.model.controlled_joint_names)<=phase['max_joint_speed']
            self.settled_steps=self.settled_steps+1 if settled else 0
            done=self.phase_steps >= phase.get('min_steps',30) and self.settled_steps>=phase.get('settle_steps',1)
            if not done and self.phase_steps >= phase.get('max_steps',300):
                self.sequence_error=f'move phase {self.sequence_index} timed out; position error {error:.4f} m'
        if done:
            self.sequence_index+=1
            self.transitions.append({'index':self.sequence_index,'physics_step':round(t*60)})
            self._new_phase()

    def sample_state(self):
        suction={'status':int(self.suction.get_surface_gripper_status()[0]),'gripped':[str(x) for x in self.suction.get_gripped_objects()[0]]} if self.suction is not None else None
        joint=self.config.get('gripper_joint')
        gripper_position=float(self.robot.get_dof_positions().numpy().reshape(-1)[self.names.index(joint)]) if joint and joint in self.names else None
        velocities=self.robot.get_dof_velocities().numpy().reshape(-1)
        max_speed=max(float(abs(velocities[self.names.index(n)])) for n in self.model.controlled_joint_names)
        return {'sequence_index':self.sequence_index,'sequence_error':self.sequence_error,'tcp_position':self._tcp_position().tolist(),'suction':suction,'gripper_joint_position':gripper_position,'max_arm_joint_speed':max_speed}

    def observe(self):
        joint=self.config.get('gripper_joint')
        gripper_position=float(self.robot.get_dof_positions().numpy().reshape(-1)[self.names.index(joint)]) if joint and joint in self.names else None
        velocities=self.robot.get_dof_velocities().numpy().reshape(-1)
        max_speed=max(float(abs(velocities[self.names.index(n)])) for n in self.model.controlled_joint_names)
        suction_state={'status':int(self.suction.get_surface_gripper_status()[0]),'gripped':[str(x) for x in self.suction.get_gripped_objects()[0]]} if self.suction is not None else None
        return {'suction':suction_state,'max_arm_joint_speed':max_speed, 'gripper_joint_position':gripper_position, 'initial_position':self.initial,'initial_joint_positions':self.initial_joint_positions,'arm_drive_gains':self.arm_drive_gains,'target_position':self.target.tolist(),'tcp_position':self._tcp_position().tolist(), 'validation':'experimental_obstacle_planning_not_certified' if self.tracked_obstacles else 'experimental_no_collision_check', 'tracked_obstacles':self.tracked_obstacles, 'sequence_index':self.sequence_index, 'sequence_length':len(self.sequence), 'sequence_error':self.sequence_error, 'transitions':self.transitions, 'suction_events':self.suction_events}
