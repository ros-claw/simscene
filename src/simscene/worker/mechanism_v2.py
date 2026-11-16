"""Isolated two-single-axis articulation tensor adapter.

The caller supplies an already-created NumPy PhysX view and its simulation view.
No Isaac integration or runtime physics validation is implied by this module.
"""
import copy
import math

from .mechanism import _path, _quaternion, _vector, measure_joint

RESET_LOCKED_ROTATION_TOLERANCE_RAD = 1e-4


class TwoDofTensorState:
    """Read a frozen two-DOF tree and reset it once while paused before a task.

    ``binding`` contains ``root_body``, three ``motion_bodies``, and two
    single-axis ``joints`` with explicit absolute paths, frames and SI limits.
    ``root_link_type`` must be the target engine's ArticulationRootLink enum;
    the caller must call ``mark_task_started`` before starting task physics.
    The view and authored poses must use the same world/subspace reference frame.
    """

    def __init__(self, view, binding, *, simulation_view, root_link_type):
        import numpy as np

        self.np = np
        self.view = view
        self.simulation_view = simulation_view
        self.root_link_type = root_link_type
        if root_link_type is None or not callable(getattr(simulation_view, 'get_object_type', None)):
            raise ValueError('an engine root-link type and object-type query are required')
        self.binding = copy.deepcopy(binding)
        self.root_body, expected_links, self.by_path = self._validate_binding(self.binding)
        self.link_paths, self.dof_paths = self._current_graph()
        if (len(set(self.link_paths)) != 3 or set(self.link_paths) != set(expected_links)
                or len(set(self.dof_paths)) != 2 or set(self.dof_paths) != set(self.by_path)):
            raise RuntimeError('tensor paths are not a bijection with the frozen articulation graph')
        self._check_actual_root()
        self._reset_attempted = False
        self._reset_completed = False
        self._task_started = False

    @staticmethod
    def _validate_binding(binding):
        if not isinstance(binding, dict):
            raise ValueError('two-DOF binding must be a dictionary')
        links = binding.get('motion_bodies')
        root = binding.get('root_body')
        joints = binding.get('joints')
        if (not isinstance(links, (list, tuple)) or len(links) != 3
                or any(not _path(path) for path in links) or len(set(links)) != 3 or root not in links):
            raise ValueError('two-DOF binding requires three distinct links and an explicit root')
        if not isinstance(joints, dict) or len(joints) != 2:
            raise ValueError('two-DOF binding requires exactly two named joints')
        by_path = {}
        incoming = {path: 0 for path in links}
        edges = {}
        for name, joint in joints.items():
            if not isinstance(name, str) or not name or not isinstance(joint, dict):
                raise ValueError('invalid frozen joint identity')
            path = joint.get('joint_path')
            parent, child = joint.get('parent_body'), joint.get('child_body')
            if not _path(path) or path in by_path:
                raise ValueError('frozen joint paths must be distinct and absolute')
            if parent not in incoming or child not in incoming or parent == child:
                raise ValueError('frozen joint endpoints must be distinct links in this articulation')
            unit = {'revolute': 'rad', 'prismatic': 'm'}.get(joint.get('type'))
            if unit is None or joint.get('position_unit') != unit or joint.get('axis') not in ('X', 'Y', 'Z'):
                raise ValueError('only single-axis SI revolute or prismatic joints are supported')
            limits = _vector(joint.get('limits'), 2, 'joint limits')
            if limits[0] >= limits[1] or unit == 'rad' and limits[1] - limits[0] >= 2 * math.pi:
                raise ValueError('joint limits must be ordered and angular initialization unambiguous')
            for suffix in ('0', '1'):
                _vector(joint.get('local_pos' + suffix + '_m'), 3, 'joint local position')
                _quaternion(joint.get('local_rot' + suffix + '_wxyz'))
            by_path[path] = joint
            incoming[child] += 1
            edges.setdefault(parent, []).append(child)
        if [path for path, count in incoming.items() if count == 0] != [root] or any(v > 1 for v in incoming.values()):
            raise ValueError('frozen articulation must have one explicit root and unique child links')
        visited, pending = set(), [root]
        while pending:
            current = pending.pop()
            if current in visited:
                raise ValueError('frozen articulation contains a cycle')
            visited.add(current)
            pending.extend(edges.get(current, []))
        if visited != set(links):
            raise ValueError('frozen articulation graph is disconnected')
        return root, tuple(links), by_path

    def _current_graph(self):
        try:
            if self.view.count != 1 or self.view.max_dofs != 2:
                raise RuntimeError('tensor view must contain one articulation with two DOFs')
            metadata = self.view.get_metatype(0)
            if metadata.dof_count != 2 or metadata.link_count != 3:
                raise RuntimeError('actual tensor metatype must expose two DOFs and three links')
            links, dofs = self.view.link_paths, self.view.dof_paths
            if len(links) != 1 or len(dofs) != 1:
                raise RuntimeError('tensor path arrays must contain exactly one articulation')
            links, dofs = tuple(links[0]), tuple(dofs[0])
            if (len(links) != 3 or len(dofs) != 2
                    or any(not _path(path) for path in links + dofs)):
                raise RuntimeError('tensor link or DOF path array has an invalid shape')
            return links, dofs
        except (AttributeError, TypeError, IndexError) as error:
            raise RuntimeError('tensor view does not expose a verifiable articulation graph') from error

    def _check_actual_root(self):
        try:
            roots = [path for path in self.link_paths
                     if self.simulation_view.get_object_type(path) == self.root_link_type]
        except Exception as error:
            raise RuntimeError('engine root-link identity could not be checked') from error
        if roots != [self.root_body]:
            raise RuntimeError('engine root link differs from the frozen explicit root body')

    def _check_current_graph(self):
        if self._current_graph() != (self.link_paths, self.dof_paths):
            raise RuntimeError('tensor path order or graph changed after binding')
        self._check_actual_root()

    def _array(self, value, shape, name):
        np = self.np
        try:
            array = np.asarray(value)
            if (array.shape != shape or not np.issubdtype(array.dtype, np.number)
                    or np.issubdtype(array.dtype, np.complexfloating)):
                raise RuntimeError(name + ' tensor has an invalid shape or type')
            array = array.astype(np.float64, copy=True)
            if not np.isfinite(array).all():
                raise RuntimeError(name + ' tensor contains a nonfinite value')
            return array
        except (TypeError, ValueError, OverflowError) as error:
            raise RuntimeError(name + ' tensor is invalid') from error

    def read(self):
        """Return per-path actual link poses and PhysX DOF q/v in SI units."""
        self._check_current_graph()
        q = self._array(self.view.get_dof_positions(), (1, 2), 'DOF position')[0]
        v = self._array(self.view.get_dof_velocities(), (1, 2), 'DOF velocity')[0]
        transforms = self._array(self.view.get_link_transforms(), (1, 3, 7), 'link transform')[0]
        velocities = self._array(self.view.get_link_velocities(), (1, 3, 6), 'link velocity')[0]
        root = self._array(self.view.get_root_transforms(), (1, 7), 'root transform')[0]
        root_velocity = self._array(self.view.get_root_velocities(), (1, 6), 'root velocity')[0]
        for quat in [root[3:7], *(row[3:7] for row in transforms)]:
            if abs(float(quat @ quat) - 1.) > 1e-4:
                raise RuntimeError('tensor link/root quaternion is not normalized')
        root_index = self.link_paths.index(self.root_body)
        root_link = transforms[root_index]
        rotation_error = min(self.np.linalg.norm(root[3:] - root_link[3:]),
                             self.np.linalg.norm(root[3:] + root_link[3:]))
        if self.np.linalg.norm(root[:3] - root_link[:3]) > 1e-5 or rotation_error > 1e-5:
            raise RuntimeError('root tensor transform differs from the verified root link')
        return {'positions': {path: transforms[i, :3].tolist() for i, path in enumerate(self.link_paths)},
                'orientations_wxyz': {path: [float(transforms[i, 6]), *transforms[i, 3:6].tolist()]
                                      for i, path in enumerate(self.link_paths)},
                'linear_velocities_m_s': {path: velocities[i, :3].tolist() for i, path in enumerate(self.link_paths)},
                'angular_velocities_rad_s': {path: velocities[i, 3:].tolist() for i, path in enumerate(self.link_paths)},
                'root_linear_velocity_m_s': root_velocity[:3].tolist(),
                'root_angular_velocity_rad_s': root_velocity[3:].tolist(),
                'native_root_velocities': {self.root_body: {
                    'linear_velocity_m_s': root_velocity[:3].tolist(),
                    'angular_velocity_rad_s': root_velocity[3:].tolist(),
                    'source': 'PhysX_articulation_tensor_root_velocity_raw',
                    'scope': 'raw root getter may be stale while sleeping; not an independent motion measurement'}},
                'native_joint_positions': {path: float(q[i]) for i, path in enumerate(self.dof_paths)},
                'native_joint_velocities': {path: float(v[i]) for i, path in enumerate(self.dof_paths)},
                'native_joint_measurement_source': 'PhysX_articulation_tensor_DOF_readback_SI'}

    def mark_task_started(self):
        """Prevent future reset as soon as the caller begins task physics."""
        if self._reset_attempted and not self._reset_completed:
            raise RuntimeError('cannot start a task after an incomplete articulation reset')
        self._task_started = True

    def reset_before_task(self, authored_state, *, is_paused):
        """Reset once, in tensor order, then verify actual DOF and link readback."""
        if self._task_started or self._reset_attempted:
            raise RuntimeError('articulation reset is allowed only once before the task')
        if not callable(is_paused) or is_paused() is not True:
            raise RuntimeError('articulation reset requires a paused simulation')
        self._check_current_graph()
        if not isinstance(authored_state, dict) or not isinstance(authored_state.get('bodies'), dict):
            raise ValueError('reset requires frozen authored body poses')
        bodies = authored_state['bodies']
        positions, orientations = {}, {}
        for path in self.link_paths:
            body = bodies.get(path)
            if not isinstance(body, dict):
                raise ValueError('missing frozen authored link pose')
            positions[path] = _vector(body.get('position'), 3, 'authored link position')
            orientations[path] = _quaternion(body.get('orientation_wxyz'))
        authored = {'positions': positions, 'orientations_wxyz': orientations}
        values = []
        for path in self.dof_paths:
            joint = self.by_path[path]
            measured = measure_joint(joint, authored, physics_step=0, physics_dt_s=1 / 60,
                                     require_unique_initial=True)
            position = measured['position']
            if (not math.isfinite(position) or measured['anchor_error_m'] > 1e-4
                    or measured['locked_rotation_error_rad'] > RESET_LOCKED_ROTATION_TOLERANCE_RAD
                    or position < joint['limits'][0] - 1e-4 or position > joint['limits'][1] + 1e-4):
                raise ValueError('authored joint frame or position is inconsistent with the frozen binding')
            values.append(position)
        np = self.np
        root_q = orientations[self.root_body]
        root_transform = np.asarray([[*positions[self.root_body], *root_q[1:], root_q[0]]], dtype=np.float32)
        dof_positions = np.asarray([values], dtype=np.float32)
        if not np.isfinite(root_transform).all() or not np.isfinite(dof_positions).all():
            raise ValueError('authored reset pose exceeds the tensor numeric range')
        if is_paused() is not True:
            raise RuntimeError('simulation resumed before the articulation reset')
        self._reset_attempted = True  # A partial write must never be retried.
        indices = np.asarray([0], dtype=np.uint32)
        self.view.set_root_transforms(root_transform, indices)
        self.view.set_root_velocities(np.zeros((1, 6), dtype=np.float32), indices)
        self.view.set_dof_positions(dof_positions, indices)
        self.view.set_dof_velocities(np.zeros((1, 2), dtype=np.float32), indices)
        self.simulation_view.update_articulations_kinematic()
        if is_paused() is not True:
            raise RuntimeError('simulation resumed during the articulation reset')
        observed = self.read()
        if (np.linalg.norm(observed['root_linear_velocity_m_s']) > 1e-7
                or np.linalg.norm(observed['root_angular_velocity_rad_s']) > 1e-7):
            raise RuntimeError('native root reset velocity is not zero')
        for index, path in enumerate(self.dof_paths):
            if (abs(observed['native_joint_positions'][path] - values[index]) > 1e-6
                    or abs(observed['native_joint_velocities'][path]) > 1e-7):
                raise RuntimeError('native DOF reset readback differs from the authored coordinate')
        for path in self.link_paths:
            actual_q = np.asarray(observed['orientations_wxyz'][path])
            expected_q = np.asarray(orientations[path])
            if (np.linalg.norm(np.asarray(observed['positions'][path]) - positions[path]) > 1e-6
                    or min(np.linalg.norm(actual_q - expected_q), np.linalg.norm(actual_q + expected_q)) > 1e-6
                    or np.linalg.norm(observed['linear_velocities_m_s'][path]) > 1e-7
                    or np.linalg.norm(observed['angular_velocities_rad_s'][path]) > 1e-7):
                raise RuntimeError('native link reset readback differs from the authored pose or zero velocity')
        self._reset_completed = True
        return observed
