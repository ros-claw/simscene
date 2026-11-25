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
    two_dof = isinstance(binding, dict) and binding.get('profile_id') == 'articulated_prop_v2'
    if not isinstance(joints, dict) or len(joints) != (2 if two_dof else 1):
        raise ValueError('M2 mechanism requires exactly one declared single-DOF joint')
    if two_dof:
        from .mechanism_v2 import TwoDofTensorState
        TwoDofTensorState._validate_binding(binding)
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
            event = {'command_index': index, 'joint_id': joint_id,
                     'physics_step': physics_step, 'trigger': copy.deepcopy(command['trigger']),
                     'target_position': command['target_position'], 'position_unit': command['position_unit'],
                     'drive_readback': readback, 'cause': 'declared_at_step_schedule'}
            if self.binding.get('profile_id') == 'articulated_prop_v2':
                event['joint_path'] = self.binding['joints'][joint_id]['joint_path']
            self.events.append(event)
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
                'control_scope': ('explicit two-DOF at_step drive targets; no body pose setters'
                                  if self.binding.get('profile_id') == 'articulated_prop_v2' else
                                  'explicit single-DOF at_step drive targets; no body pose setters')}


def _mul(a, b):
    w, x, y, z = a; v, i, j, k = b
    return [w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j, w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v]


def _inverse(q):
    return [q[0], -q[1], -q[2], -q[3]]


def _rotate(q, p):
    return _mul(_mul(q, [0., *p]), _inverse(q))[1:]


def measure_joint(joint, native_state, previous=None, *, physics_step, physics_dt_s,
                  require_unique_initial=False):
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
        locked_rotation_error = 2 * math.atan2(math.sqrt(sum(v*v for v in relative_q[1:])), abs(relative_q[0]))
    else:
        position = 2 * math.atan2(relative_q[axis+1], relative_q[0])
        position = (position + math.pi) % (2*math.pi) - math.pi
        if previous is not None:
            last = previous['position']
            position = last + (position - last + math.pi) % (2*math.pi) - math.pi
        else:
            # Find the unique integer turn inside the finite frozen range,
            # without assuming the authored interval lies within one turn of 0.
            period = 2 * math.pi
            lower = math.ceil((joint['limits'][0] - position) / period)
            upper = math.floor((joint['limits'][1] - position) / period)
            if lower > upper:
                # Permit the existing small endpoint tolerance only when no
                # exact representative exists, without making one exact angle
                # appear ambiguous in a near-single-turn interval.
                lower = math.ceil((joint['limits'][0] - 1e-4 - position) / period)
                upper = math.floor((joint['limits'][1] + 1e-4 - position) / period)
            if lower == upper:
                position += period * lower
            elif require_unique_initial:
                raise ValueError('joint pose has no unique initial angle in its frozen limits')
        anchor_error = math.sqrt(sum(v*v for v in difference))
        perpendicular = math.sqrt(sum(v*v for i, v in enumerate(relative_q[1:]) if i != axis))
        twist = math.hypot(relative_q[0], relative_q[axis+1])
        locked_rotation_error = 2 * math.atan2(perpendicular, twist)
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
            'anchor_error_m': anchor_error, 'locked_rotation_error_rad': locked_rotation_error,
            'parent_body': joint['parent_body'], 'child_body': joint['child_body'],
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
            if binding.get('profile_id') == 'articulated_prop_v2':
                path = joint['joint_path']
                positions = native_state.get('native_joint_positions')
                velocities = native_state.get('native_joint_velocities')
                if (not isinstance(positions, dict) or not isinstance(velocities, dict)
                        or path not in positions or path not in velocities
                        or native_state.get('native_joint_measurement_source') != 'PhysX_articulation_tensor_DOF_readback_SI'):
                    raise RuntimeError('two-DOF observation requires native position and velocity for every frozen joint')
                _number(positions[path], 'native DOF position')
                _number(velocities[path], 'native DOF velocity')
            if joint['joint_path'] in native_state.get('native_joint_positions',{}):
                result[name].update(native_position=native_state['native_joint_positions'][joint['joint_path']],native_velocity=native_state['native_joint_velocities'][joint['joint_path']],native_measurement_source=native_state['native_joint_measurement_source'])
        self.previous = copy.deepcopy(result)
        return result


class PreparedArticulationState:
    """Strict initialization and tensor readback for imported articulation links.

    Setters exist only in reset_before_task(), once while paused before task zero.
    Runtime read() is read-only and includes independent native DOF readback.
    """
    def __init__(self, stage, objects, body_bindings, authored_state, *,
                 simulation_view=None, root_link_type=None, is_paused=None):
        import numpy as np
        self.np=np;self.stage=stage;self.objects=objects;self.bindings=body_bindings
        self.authored=authored_state;self.reset_count=0;self._is_paused=is_paused
        self._reset_attempted=False;self._reset_verified=False;self._task_started=False
        if authored_state is None:raise RuntimeError('articulated strict reset requires pre-warmup authored state')
        has_v2=any(binding.get('profile_id')=='articulated_prop_v2' for binding in body_bindings.values())
        if simulation_view is None:
            import omni.physics.tensors as tensors
            import omni.usd
            self.sim=tensors.create_simulation_view('numpy',stage_id=omni.usd.get_context().get_stage_id())
            self.sim.set_subspace_roots('/')
            if has_v2:
                try:root_link_type=tensors.ObjectType.ArticulationRootLink
                except AttributeError as error:raise RuntimeError('PhysX root-link enum is unavailable') from error
        else:
            self.sim=simulation_view
        if has_v2 and (root_link_type is None or not callable(is_paused)):
            raise RuntimeError('two-DOF state requires the engine root-link enum and a paused-state query')
        self.articulations=[];self.two_dof_articulations=[];art_paths=set();joint_paths=set()
        for binding in body_bindings.values():
            roots=binding.get('articulation_roots',[])
            is_v2=binding.get('profile_id')=='articulated_prop_v2'
            if is_v2:
                validate_binding(binding)
                if not isinstance(roots,list) or len(roots)!=1:
                    raise RuntimeError('two-DOF articulation requires one explicit root view')
            for root in roots:
                view=self.sim.create_articulation_view(root)
                if is_v2:
                    from .mechanism_v2 import TwoDofTensorState
                    adapter=TwoDofTensorState(view,binding,simulation_view=self.sim,root_link_type=root_link_type)
                    paths=list(adapter.link_paths);dofs=list(adapter.dof_paths)
                    self.two_dof_articulations.append(adapter)
                else:
                    if view.count!=1 or view.max_dofs!=1:
                        raise RuntimeError('prepared native articulation must expose exactly one actual tensor DOF')
                    paths=list(view.link_paths[0]);dofs=list(view.dof_paths[0])
                    if set(paths)!=set(binding['motion_bodies']) or set(dofs)!={j['joint_path'] for j in binding['joints'].values()}:
                        raise RuntimeError('native articulation tensor graph differs from frozen body/joint binding')
                    self.articulations.append((view,paths,dofs,binding))
                if (len(paths)!=len(set(paths)) or len(dofs)!=len(set(dofs))
                        or art_paths.intersection(paths) or joint_paths.intersection(dofs)):
                    raise RuntimeError('duplicate native tensor body or DOF path across articulations')
                art_paths.update(paths);joint_paths.update(dofs)
        expected=set(authored_state['bodies'])
        remaining=sorted(expected-art_paths)
        self.rigid=self.sim.create_rigid_body_view(remaining) if remaining else None
        self.rigid_paths=list(self.rigid.prim_paths) if self.rigid else []
        self.paths=(self.rigid_paths+[p for _,paths,_,_ in self.articulations for p in paths]
                    +[p for adapter in self.two_dof_articulations for p in adapter.link_paths])
        if len(set(self.paths))!=len(self.paths) or set(self.paths)!=expected:
            raise RuntimeError('strict articulated tensor body set differs from authored bodies')

    def refresh(self):
        raise RuntimeError('scheduled body spawning with native articulation strict reset is unsupported')

    def read(self):
        np=self.np;transforms=[];velocities=[];paths=[];positions={};speeds={}
        if self.rigid:
            rt=np.asarray(self.rigid.get_transforms()).copy();rv=np.asarray(self.rigid.get_velocities()).copy()
            if self.two_dof_articulations and (rt.shape!=(len(self.rigid_paths),7) or rv.shape!=(len(self.rigid_paths),6)):
                raise RuntimeError('rigid tensor shape differs from frozen body paths')
            transforms.extend(rt);velocities.extend(rv);paths.extend(self.rigid_paths)
        for view,links,dofs,_ in self.articulations:
            lt=np.asarray(view.get_link_transforms());lv=np.asarray(view.get_link_velocities())
            qa=np.asarray(view.get_dof_positions());va=np.asarray(view.get_dof_velocities())
            if self.two_dof_articulations and (lt.shape!=(1,len(links),7) or lv.shape!=(1,len(links),6)
                    or qa.shape!=(1,len(dofs)) or va.shape!=(1,len(dofs))):
                raise RuntimeError('single-DOF tensor shape differs from frozen body or DOF paths')
            transforms.extend(lt[0,:len(links)].copy())
            velocities.extend(lv[0,:len(links)].copy());paths.extend(links)
            q=qa[0];v=va[0]
            positions.update({p:float(q[i]) for i,p in enumerate(dofs)});speeds.update({p:float(v[i]) for i,p in enumerate(dofs)})
        transforms=np.asarray(transforms);velocities=np.asarray(velocities)
        if not np.isfinite(transforms).all() or not np.isfinite(velocities).all() or not all(math.isfinite(x) for x in list(positions.values())+list(speeds.values())):
            raise RuntimeError('nonfinite native articulation tensor state')
        result={'positions':{p:[float(v) for v in transforms[i,:3]] for i,p in enumerate(paths)},
                'orientations_wxyz':{p:[float(transforms[i,6]),*[float(v) for v in transforms[i,3:6]]] for i,p in enumerate(paths)},
                'linear_velocities_m_s':{p:[float(v) for v in velocities[i,:3]] for i,p in enumerate(paths)},
                'angular_velocities_rad_s':{p:[float(v) for v in velocities[i,3:]] for i,p in enumerate(paths)},
                'native_joint_positions':positions,'native_joint_velocities':speeds,
                'native_joint_measurement_source':'PhysX_articulation_tensor_DOF_readback_SI'}
        for adapter in self.two_dof_articulations:
            observed=adapter.read()
            for key in ('positions','orientations_wxyz','linear_velocities_m_s','angular_velocities_rad_s',
                        'native_joint_positions','native_joint_velocities'):
                if set(result[key]).intersection(observed[key]):
                    raise RuntimeError('duplicate native tensor path during readback')
                result[key].update(observed[key])
            root_velocities=result.setdefault('native_root_velocities',{})
            if set(root_velocities).intersection(observed['native_root_velocities']):
                raise RuntimeError('duplicate native root tensor path during readback')
            root_velocities.update(observed['native_root_velocities'])
        return result

    def mass_properties(self,physics_step):
        np=self.np;result={}
        assumptions={}
        for binding in self.bindings.values():
            for entry in binding.get('bodies',{}).values():
                if entry.get('mass_provenance'):
                    assumptions[entry['motion_body']]={'mass_provenance':entry['mass_provenance'],
                        'native_repairs_ref':copy.deepcopy(binding.get('native_repairs_ref'))}
        groups=[]
        if self.rigid:groups.append((self.rigid_paths,np.asarray(self.rigid.get_masses()),np.asarray(self.rigid.get_coms()),np.asarray(self.rigid.get_inertias())))
        for view,paths,_,_ in self.articulations:
            groups.append((paths,np.asarray(view.get_masses())[0,:len(paths)],np.asarray(view.get_coms())[0,:len(paths)],np.asarray(view.get_inertias())[0,:len(paths)]))
        for adapter in self.two_dof_articulations:
            view=adapter.view;paths=adapter.link_paths
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
                    'observed_at_physics_step':physics_step,'source':'PhysX native articulation/rigid tensor cooked mass properties; see prepared manifest for authored or experimental assumptions'}
                if path in assumptions:result[path].update(assumptions[path])
        return result

    def reset_before_task(self):
        if self.reset_count:raise RuntimeError('strict articulated initialization reset may run only once')
        if self.two_dof_articulations:
            if self._reset_attempted or self._task_started:raise RuntimeError('two-DOF initialization is allowed only once before task start')
            if self._is_paused() is not True:raise RuntimeError('two-DOF initialization requires a paused timeline')
            self._reset_attempted=True
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
        for adapter in self.two_dof_articulations:
            adapter.reset_before_task(self.authored,is_paused=self._is_paused)
        self.sim.update_articulations_kinematic()
        if self.two_dof_articulations and self._is_paused() is not True:
            raise RuntimeError('timeline resumed during two-DOF initialization')
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
        self._reset_verified=True
        return {'applied':True,'phase':'before_task_start','reset_count':1,'body_paths':self.paths,
                'authored_pose_capture_phase':self.authored['phase'],'authored_pose_readback_max_error_m':position_error,
                'max_quaternion_error':rotation_error,'max_speed':speed,'local_xform_ops_restored':True,
                'setters_during_task':False,'native_articulation_joint_reset':True,
                'scope':'one paused pre-task native articulation root/DOF reset; runtime readback only'}

    def mark_task_started(self):
        if self.two_dof_articulations and not self._reset_verified:
            raise RuntimeError('two-DOF task requires a successfully verified initialization')
        for adapter in self.two_dof_articulations:adapter.mark_task_started()
        self._task_started=True
