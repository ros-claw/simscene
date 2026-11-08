"""Explicit single-DOF imported-joint commands and measured frame coordinates.

This module never sets body poses or joint coordinates. An empty command list
leaves native drives untouched. Observation reconstructs coordinates from joint
frames and actual body poses; it is not an independent SDK joint-angle getter.
"""
import copy
import math


def _number(value, name, *, positive=False, nonnegative=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name + ' must be finite numeric')
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(name + ' is out of range')
    return float(value)


def _vector(value, count, name):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError(name + ' has invalid length')
    return [_number(v, name) for v in value]


def _quaternion(value):
    q = _vector(value, 4, 'joint frame quaternion')
    if abs(sum(v * v for v in q) - 1) > 1e-5:
        raise ValueError('joint frame quaternion must be normalized')
    return q


def _path(value):
    return (isinstance(value, str) and value.startswith('/World/')
            and not any(p in ('', '.', '..') for p in value.split('/')[1:])
            and not any(c in value for c in ('\\', '%', '?', '#', ':')))


def validate_binding(binding):
    """Validate already-resolved canonical bindings, never infer joint paths."""
    joints = binding.get('joints') if isinstance(binding, dict) else None
    if not isinstance(joints, dict) or len(joints) != 1:
        raise ValueError('M2 mechanism requires exactly one declared single-DOF joint')
    for joint_id, joint in joints.items():
        if not isinstance(joint_id, str) or not joint_id or not isinstance(joint, dict):
            raise ValueError('invalid mechanism joint identity')
        if not _path(joint.get('joint_path')) or not _path(joint.get('child_body')):
            raise ValueError('mechanism joint/child path must be explicit')
        parent = joint.get('parent_body')
        if parent is not None and not _path(parent) or parent == joint['child_body']:
            raise ValueError('invalid mechanism parent body')
        expected = {'revolute': 'rad', 'prismatic': 'm'}.get(joint.get('type'))
        if expected is None or joint.get('position_unit') != expected:
            raise ValueError('unsupported joint type or noncanonical position units')
        if joint.get('axis') not in ('X', 'Y', 'Z'):
            raise ValueError('mechanism requires an explicit joint axis')
        limits = _vector(joint.get('limits'), 2, 'joint limits')
        if limits[0] >= limits[1] or expected == 'rad' and limits[1] - limits[0] >= 2 * math.pi:
            raise ValueError('mechanism requires finite ordered single-turn limits')
        for suffix in ('0', '1'):
            _vector(joint.get('local_pos' + suffix + '_m'), 3, 'joint local position')
            _quaternion(joint.get('local_rot' + suffix + '_wxyz'))
        if type(joint.get('passive')) is not bool or 'drive' not in joint:
            raise ValueError('mechanism requires explicit native drive/passive declaration')
        if joint['passive'] != (joint['drive'] is None):
            raise ValueError('native passive declaration conflicts with its drive')
        if joint['drive'] is not None:
            _drive(joint['drive'])
    return binding


def _drive(value):
    if not isinstance(value, dict):
        raise ValueError('invalid drive parameters')
    for name in ('stiffness', 'damping'):
        _number(value.get(name), name, nonnegative=True)
    _number(value.get('max_effort'), 'max_effort', positive=True)


def validate_config(binding, config):
    """Freeze commands before physics; only explicit physics-step triggers exist."""
    validate_binding(binding)
    if not isinstance(config, dict) or set(config) - {'commands'}:
        raise ValueError('mechanism supports only an explicit commands list')
    commands = config.get('commands', [])
    if not isinstance(commands, list) or len(commands) > 256:
        raise ValueError('mechanism commands must be a bounded list')
    occupied = set()
    required = {'joint_id', 'trigger', 'target_position', 'position_unit', 'stiffness', 'damping', 'max_effort'}
    for command in commands:
        if not isinstance(command, dict) or set(command) != required:
            raise ValueError('mechanism command requires joint, at_step target and drive parameters')
        joint_id = command['joint_id']
        if not isinstance(joint_id, str) or joint_id not in binding['joints']:
            raise ValueError('command references an undeclared joint')
        trigger = command['trigger']
        if (not isinstance(trigger, dict) or set(trigger) != {'type', 'physics_step'}
                or trigger['type'] != 'at_step' or type(trigger['physics_step']) is not int
                or trigger['physics_step'] < 0):
            raise ValueError('M2 supports only explicit at_step physics-step triggers')
        identity = (joint_id, trigger['physics_step'])
        if identity in occupied:
            raise ValueError('conflicting commands for the same joint and physics step')
        occupied.add(identity)
        joint = binding['joints'][joint_id]
        target = _number(command['target_position'], 'target_position')
        if command['position_unit'] != joint['position_unit']:
            raise ValueError('command position_unit differs from its joint binding')
        if not joint['limits'][0] <= target <= joint['limits'][1]:
            raise ValueError('command target_position exceeds measured joint limits')
        _drive(command)
        if command['stiffness'] <= 0:
            raise ValueError('position commands require positive stiffness')
    return copy.deepcopy(config)


class MechanismController:
    """Apply declared drive targets once, with actual observations kept separate."""
    def __init__(self, binding, config, *, backend):
        self.binding = copy.deepcopy(validate_binding(binding))
        self.config = validate_config(self.binding, config)
        self.backend = backend
        self.events = []
        self.targets = {}
        self._last_step = -1
        self._executed = set()

    def step(self, physics_step, events=None):
        if type(physics_step) is not int or physics_step < 0 or physics_step < self._last_step:
            raise ValueError('mechanism physics steps must be monotonic nonnegative integers')
        self._last_step = physics_step
        for index, command in enumerate(self.config.get('commands', [])):
            due = command['trigger']['physics_step']
            if index in self._executed or due > physics_step:
                continue
            if due != physics_step:
                raise RuntimeError('missed mechanism command physics step; refusing a late target')
            joint_id = command['joint_id']
            readback = self.backend.apply_drive(self.binding['joints'][joint_id], command)
            self.events.append({'command_index': index, 'joint_id': joint_id,
                                'physics_step': physics_step, 'trigger': copy.deepcopy(command['trigger']),
                                'target_position': command['target_position'], 'position_unit': command['position_unit'],
                                'drive_readback': readback, 'cause': 'declared_at_step_schedule'})
            self.targets[joint_id] = copy.deepcopy(command)
            self._executed.add(index)
        # Contact events are deliberately not interpreted as triggers in M2.
        return copy.deepcopy(self.events)

    def observe(self, physics_step=None, native_state=None):
        step = self._last_step if physics_step is None else physics_step
        if type(step) is not int or step < 0:
            raise ValueError('mechanism observation requires an actual nonnegative physics step')
        measured = self.backend.observe(self.binding, step, native_state=native_state)
        return {'physics_step': step, 'joints': measured,
                'runtime_targets': copy.deepcopy(self.targets), 'command_events': copy.deepcopy(self.events),
                'control_scope': 'explicit single-DOF at_step drive targets; no body pose setters'}


def _mul(a, b):
    w, x, y, z = a; v, i, j, k = b
    return [w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j, w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v]


def _inverse(q):
    return [q[0], -q[1], -q[2], -q[3]]


def _rotate(q, p):
    return _mul(_mul(q, [0., *p]), _inverse(q))[1:]


def measure_joint(joint, native_state, previous=None, *, physics_step, physics_dt_s):
    """Reconstruct a signed coordinate from two same-sample body tensor poses."""
    frames = []
    for suffix, body in [('0', joint['parent_body']), ('1', joint['child_body'])]:
        if body is None:
            p, q = [0., 0., 0.], [1., 0., 0., 0.]
        else:
            p = _vector(native_state.get('positions', {}).get(body), 3, 'actual mechanism body position')
            q = _quaternion(native_state.get('orientations_wxyz', {}).get(body))
        local = _rotate(q, joint['local_pos' + suffix + '_m'])
        frames.append(([a+b for a, b in zip(p, local)], _mul(q, joint['local_rot' + suffix + '_wxyz'])))
    (p0, q0), (p1, q1) = frames
    axis = ('X', 'Y', 'Z').index(joint['axis'])
    difference = [a-b for a, b in zip(p1, p0)]
    relative_p = _rotate(_inverse(q0), difference)
    relative_q = _mul(_inverse(q0), q1)
    if joint['type'] == 'prismatic':
        position = relative_p[axis]
        anchor_error = math.sqrt(sum(v*v for i, v in enumerate(relative_p) if i != axis))
    else:
        position = 2 * math.atan2(relative_q[axis+1], relative_q[0])
        position = (position + math.pi) % (2*math.pi) - math.pi
        if previous is not None:
            last = previous['position']
            position = last + (position - last + math.pi) % (2*math.pi) - math.pi
        else:
            # Choose the unique representative inside the frozen finite range.
            candidates = [position + 2*math.pi*k for k in (-1, 0, 1)
                          if joint['limits'][0]-1e-4 <= position+2*math.pi*k <= joint['limits'][1]+1e-4]
            if len(candidates) == 1:
                position = candidates[0]
        anchor_error = math.sqrt(sum(v*v for v in difference))
    velocity = None
    if previous is not None:
        delta = physics_step - previous['physics_step']
        if delta < 0:
            raise ValueError('mechanism observations went backwards')
        if delta == 0:
            if abs(position - previous['position']) > 1e-7:
                raise ValueError('mechanism pose changed without a physics step')
            velocity = previous['velocity']
        else:
            velocity = (position - previous['position']) / (delta * physics_dt_s)
    return {'position': position, 'velocity': velocity, 'position_unit': joint['position_unit'],
            'velocity_unit': joint['position_unit'] + '/s', 'physics_step': physics_step,
            'anchor_error_m': anchor_error, 'parent_body': joint['parent_body'], 'child_body': joint['child_body'],
            'joint_path': joint['joint_path'], 'measurement_source': 'same_sample_PhysX_body_poses_joint_frame_reconstruction'}


def usd_drive_values(joint, command):
    """Convert SI command gains as well as angular targets to USD degrees.

    https://docs.omniverse.nvidia.com/kit/docs/omni_physics/latest/dev_guide/simulation_control/simulation_control.html
    Angular USD stiffness/damping are torque per degree, not per radian.
    """
    angular = joint['type'] == 'revolute'
    factor = math.pi / 180 if angular else 1.
    return {'instance': 'angular' if angular else 'linear', 'type': 'force',
            'target_position': math.degrees(command['target_position']) if angular else command['target_position'],
            'target_velocity': 0., 'stiffness': command['stiffness'] * factor,
            'damping': command['damping'] * factor, 'max_force': command['max_effort'],
            'position_unit': 'degree' if angular else 'm'}


class UsdMechanismBackend:
    """Author drive APIs only; obtain actual poses through the physics state reader."""
    def __init__(self, stage, state_reader, *, physics_dt_s=1/60):
        self.stage = stage
        self.state_reader = state_reader
        self.physics_dt_s = _number(physics_dt_s, 'physics_dt_s', positive=True)
        self.previous = {}

    def apply_drive(self, joint, command):
        from pxr import UsdPhysics
        prim = self.stage.GetPrimAtPath(joint['joint_path'])
        expected = UsdPhysics.RevoluteJoint if joint['type'] == 'revolute' else UsdPhysics.PrismaticJoint
        if not prim or not prim.IsA(expected):
            raise ValueError('declared source joint is missing or has changed type')
        values = usd_drive_values(joint, command)
        drive = UsdPhysics.DriveAPI.Apply(prim, values['instance'])
        for name, value in [('Type', values['type']), ('TargetPosition', values['target_position']),
                            ('TargetVelocity', 0.), ('Stiffness', values['stiffness']),
                            ('Damping', values['damping']), ('MaxForce', values['max_force'])]:
            getattr(drive, 'Create' + name + 'Attr')(value)
        readback = {name: getattr(drive, 'Get' + attr + 'Attr')().Get()
                    for name, attr in [('type', 'Type'), ('target_position', 'TargetPosition'),
                                       ('target_velocity', 'TargetVelocity'), ('stiffness', 'Stiffness'),
                                       ('damping', 'Damping'), ('max_force', 'MaxForce')]}
        for name in readback:
            if isinstance(values[name], str):
                valid = readback[name] == values[name]
            else:
                valid = abs(readback[name] - values[name]) <= max(1e-6, abs(values[name])*1e-5)
            if not valid:
                raise RuntimeError('mechanism USD drive readback differs from command: ' + name)
        readback.update(instance=values['instance'], position_unit=values['position_unit'], scope='loaded_USD_drive_attributes')
        return readback

    def observe(self, binding, physics_step, native_state=None):
        if native_state is None:
            native_state = self.state_reader.read() if hasattr(self.state_reader, 'read') else self.state_reader()
        result = {}
        for name, joint in binding['joints'].items():
            result[name] = measure_joint(joint, native_state, self.previous.get(name),
                                         physics_step=physics_step, physics_dt_s=self.physics_dt_s)
            if joint['joint_path'] in native_state.get('native_joint_positions',{}):
                result[name].update(native_position=native_state['native_joint_positions'][joint['joint_path']],native_velocity=native_state['native_joint_velocities'][joint['joint_path']],native_measurement_source=native_state['native_joint_measurement_source'])
        self.previous = copy.deepcopy(result)
        return result


class PreparedArticulationState:
    """Strict initialization and tensor readback for imported articulation links.

    Setters exist only in reset_before_task(), once while paused before task zero.
    Runtime read() is read-only and includes independent native DOF readback.
    """
    def __init__(self, stage, objects, body_bindings, authored_state):
        import numpy as np
        import omni.physics.tensors as tensors
        import omni.usd
        self.np=np;self.stage=stage;self.objects=objects;self.bindings=body_bindings
        self.authored=authored_state;self.reset_count=0
        if authored_state is None:raise RuntimeError('articulated strict reset requires pre-warmup authored state')
        self.sim=tensors.create_simulation_view('numpy',stage_id=omni.usd.get_context().get_stage_id())
        self.sim.set_subspace_roots('/')
        self.articulations=[];art_paths=set()
        for binding in body_bindings.values():
            for root in binding.get('articulation_roots',[]):
                view=self.sim.create_articulation_view(root)
                if view.count!=1 or view.max_dofs!=1:
                    raise RuntimeError('prepared native articulation must expose exactly one actual tensor DOF')
                paths=list(view.link_paths[0]);dofs=list(view.dof_paths[0])
                if set(paths)!=set(binding['motion_bodies']) or set(dofs)!={j['joint_path'] for j in binding['joints'].values()}:
                    raise RuntimeError('native articulation tensor graph differs from frozen body/joint binding')
                self.articulations.append((view,paths,dofs,binding));art_paths.update(paths)
        expected=set(authored_state['bodies'])
        remaining=sorted(expected-art_paths)
        self.rigid=self.sim.create_rigid_body_view(remaining) if remaining else None
        self.rigid_paths=list(self.rigid.prim_paths) if self.rigid else []
        self.paths=self.rigid_paths+[p for _,paths,_,_ in self.articulations for p in paths]
        if len(set(self.paths))!=len(self.paths) or set(self.paths)!=expected:
            raise RuntimeError('strict articulated tensor body set differs from authored bodies')

    def refresh(self):
        raise RuntimeError('scheduled body spawning with native articulation strict reset is unsupported')

    def read(self):
        np=self.np;transforms=[];velocities=[];paths=[];positions={};speeds={}
        if self.rigid:
            transforms.extend(np.asarray(self.rigid.get_transforms()).copy());velocities.extend(np.asarray(self.rigid.get_velocities()).copy());paths.extend(self.rigid_paths)
        for view,links,dofs,_ in self.articulations:
            transforms.extend(np.asarray(view.get_link_transforms())[0,:len(links)].copy())
            velocities.extend(np.asarray(view.get_link_velocities())[0,:len(links)].copy());paths.extend(links)
            q=np.asarray(view.get_dof_positions())[0];v=np.asarray(view.get_dof_velocities())[0]
            positions.update({p:float(q[i]) for i,p in enumerate(dofs)});speeds.update({p:float(v[i]) for i,p in enumerate(dofs)})
        transforms=np.asarray(transforms);velocities=np.asarray(velocities)
        if not np.isfinite(transforms).all() or not np.isfinite(velocities).all() or not all(math.isfinite(x) for x in list(positions.values())+list(speeds.values())):
            raise RuntimeError('nonfinite native articulation tensor state')
        return {'positions':{p:[float(v) for v in transforms[i,:3]] for i,p in enumerate(paths)},
                'orientations_wxyz':{p:[float(transforms[i,6]),*[float(v) for v in transforms[i,3:6]]] for i,p in enumerate(paths)},
                'linear_velocities_m_s':{p:[float(v) for v in velocities[i,:3]] for i,p in enumerate(paths)},
                'angular_velocities_rad_s':{p:[float(v) for v in velocities[i,3:]] for i,p in enumerate(paths)},
                'native_joint_positions':positions,'native_joint_velocities':speeds,
                'native_joint_measurement_source':'PhysX_articulation_tensor_DOF_readback_SI'}

    def mass_properties(self,physics_step):
        np=self.np;result={}
        groups=[]
        if self.rigid:groups.append((self.rigid_paths,np.asarray(self.rigid.get_masses()),np.asarray(self.rigid.get_coms()),np.asarray(self.rigid.get_inertias())))
        for view,paths,_,_ in self.articulations:
            groups.append((paths,np.asarray(view.get_masses())[0,:len(paths)],np.asarray(view.get_coms())[0,:len(paths)],np.asarray(view.get_inertias())[0,:len(paths)]))
        for paths,masses,coms,inertias in groups:
            masses=masses.reshape(len(paths));coms=coms.reshape(len(paths),7);inertias=inertias.reshape(len(paths),9)
            for i,path in enumerate(paths):
                inertia=inertias[i].reshape(3,3,order='F')
                if (not np.isfinite(inertia).all() or not np.isfinite(coms[i]).all() or not math.isfinite(float(masses[i]))
                        or masses[i]<=0 or not np.allclose(inertia,inertia.T,atol=1e-8,rtol=1e-5) or np.min(np.linalg.eigvalsh(inertia))<=0):
                    raise RuntimeError('invalid native cooked mass/inertia: '+path)
                result[path]={'mass_kg':float(masses[i]),'center_of_mass_local_m':[float(v) for v in coms[i,:3]],
                    'principal_axes_local_wxyz':[float(coms[i,6]),*[float(v) for v in coms[i,3:6]]],
                    'inertia_at_com_in_prim_axes_kg_m2':[[float(v) for v in row] for row in inertia],
                    'observed_at_physics_step':physics_step,'source':'PhysX native articulation/rigid tensor cooked mass properties; source mass/collision preserved'}
        return result

    def reset_before_task(self):
        if self.reset_count:raise RuntimeError('strict articulated initialization reset may run only once')
        np=self.np;expected=self.authored['bodies']
        def transform(path):
            body=expected[path];q=body['orientation_wxyz'];return [*body['position'],*q[1:],q[0]]
        if self.rigid:
            indices=np.arange(len(self.rigid_paths),dtype=np.uint32)
            self.rigid.set_transforms(np.asarray([transform(p) for p in self.rigid_paths],dtype=np.float32),indices)
            self.rigid.set_velocities(np.zeros((len(indices),6),dtype=np.float32),indices)
        authored_native={'positions':{p:b['position'] for p,b in expected.items()},'orientations_wxyz':{p:b['orientation_wxyz'] for p,b in expected.items()}}
        for view,paths,dofs,binding in self.articulations:
            indices=np.asarray([0],dtype=np.uint32)
            view.set_root_transforms(np.asarray([transform(paths[0])],dtype=np.float32),indices)
            view.set_root_velocities(np.zeros((1,6),dtype=np.float32),indices)
            values=[]
            for dof in dofs:
                joint=next(j for j in binding['joints'].values() if j['joint_path']==dof)
                values.append(measure_joint(joint,authored_native,physics_step=0,physics_dt_s=1/60)['position'])
            view.set_dof_positions(np.asarray([values],dtype=np.float32),indices)
            view.set_dof_velocities(np.zeros((1,len(values)),dtype=np.float32),indices)
        self.sim.update_articulations_kinematic()
        from .initial_state import restore_local_ops
        restore_local_ops(self.stage,self.authored);self.reset_count=1
        observed=self.read();position_error=0.;rotation_error=0.;speed=0.
        for path,body in expected.items():
            position_error=max(position_error,float(np.linalg.norm(np.asarray(observed['positions'][path])-body['position'])))
            a=np.asarray(observed['orientations_wxyz'][path]);b=np.asarray(body['orientation_wxyz'])
            rotation_error=max(rotation_error,float(min(np.linalg.norm(a-b),np.linalg.norm(a+b))))
            speed=max(speed,float(np.linalg.norm(observed['linear_velocities_m_s'][path])),float(np.linalg.norm(observed['angular_velocities_rad_s'][path])))
        if position_error>1e-6 or rotation_error>1e-6 or speed>1e-7:
            raise RuntimeError('native articulation strict authored-pose/zero-velocity reset mismatch')
        return {'applied':True,'phase':'before_task_start','reset_count':1,'body_paths':self.paths,
                'authored_pose_capture_phase':self.authored['phase'],'authored_pose_readback_max_error_m':position_error,
                'max_quaternion_error':rotation_error,'max_speed':speed,'local_xform_ops_restored':True,
                'setters_during_task':False,'native_articulation_joint_reset':True,
                'scope':'one paused pre-task native articulation root/DOF reset; runtime readback only'}
