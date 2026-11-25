"""Independent, read-only checks of the positive/zero physical evidence."""
import math
from evaluate import evaluate_horizon, validate_drive_snapshot


def check_pair(positive, control):
    errors = []
    a, b = positive['metadata'], control['metadata']
    checks = {'positive': evaluate_horizon(positive['rows'], 'positive'),
              'zero': evaluate_horizon(control['rows'], 'zero')}
    if not all(item['passed'] for item in checks.values()):
        return {'passed': False, 'errors': ['one or both physical checks failed'], 'checks': checks,
                'native_velocity_consistency': 'not_verified'}
    keys = ('case_sha256', 'script_sha256', 'asset_sha256', 'isaac_version', 'case',
            'observed_physics_device', 'observed_physics_dt_s', 'wheel_dof_indices', 'dof_names', 'path_xy_m',
            'native_dof_paths', 'native_link_paths',
            'stage_physics_repairs', 'stage_drive_effort_overrides', 'observed_solver_settings_usd')
    for key in keys:
        if a.get(key) is None or a.get(key) != b.get(key):
            errors.append('paired metadata mismatch: ' + key)
    if a.get('mode') != 'positive' or b.get('mode') != 'zero':
        errors.append('incorrect run modes')
    case = a.get('case')
    if (not isinstance(case, dict) or case.get('settling_steps') != 30 or
            any(item['rows'][0].get('physics_callback_count') != 30 for item in (positive, control))):
        errors.append('first task sample must follow exactly 30 physics callbacks')
    expected_solver = {'solver_type': 'TGS', 'enable_external_forces_every_iteration': True}
    if (not isinstance(case, dict) or any(case.get(k) != v for k, v in expected_solver.items()) or
            any(m.get('observed_solver_settings_usd') != expected_solver for m in (a, b))):
        errors.append('frozen solver settings were not read back from the USD scene')
    if (not isinstance(case, dict) or case.get('native_wheel_damping') != [1., 1.] or
            case.get('native_wheel_damping_tolerance') != 1e-5):
        errors.append('fixed native wheel damping and tolerance are missing')
    path = a.get('path_xy_m')
    route = [[0., 0.], [.8, 0.]]
    if (not isinstance(path, list) or len(path) != 2 or any(
            not isinstance(point, list) or len(point) != 2 or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in point)
            for point in path) or any(math.dist(actual, expected) > 1e-6
                                      for actual, expected in zip(path, route))):
        errors.append('recorded path is not the frozen straight route')
    if (not isinstance(case, dict) or type(case.get('seed')) is not int or
            any(m.get('seed') != case['seed'] or m.get('seeded_rngs') != ['python.random', 'numpy.random']
                for m in (a, b))):
        errors.append('fixed seed or seeded RNG declarations are missing or inconsistent')
    names, indices = a.get('dof_names'), a.get('wheel_dof_indices')
    wanted = case.get('wheel_names') if isinstance(case, dict) else None
    if (not isinstance(names, list) or len(names) != 2 or len(set(names)) != 2 or
            not isinstance(indices, list) or len(indices) != 2 or any(type(i) is not int or i not in (0, 1) for i in indices)
            or len(set(indices)) != 2 or not isinstance(wanted, list) or len(wanted) != 2 or
            [names[i] for i in indices] != wanted):
        errors.append('wheel DOF indices do not map frozen wheel names to native names')
    else:
        paths, links = a.get('native_dof_paths'), a.get('native_link_paths')
        if (not isinstance(paths, list) or len(paths) != 2 or len(set(paths)) != 2 or
                [paths[i] for i in indices] != ['/World/Jetbot/chassis/' + name for name in wanted] or
                not isinstance(links, list) or len(links) != 3 or set(links) != {
                    '/World/Jetbot/chassis', '/World/Jetbot/left_wheel', '/World/Jetbot/right_wheel'}):
            errors.append('native wheel or link paths differ from frozen robot topology')
    if (a.get('observed_physics_device') != 'cpu' or
            abs(a.get('observed_physics_dt_s', 0) - 1 / 60) > 1e-9):
        errors.append('unexpected physics device or timestep')
    if any(m.get('requested_steps') != 600 or m.get('actual_task_steps') != 600 for m in (a, b)):
        errors.append('fixed horizon was not completed')
    if a.get('terminal_status') != 'arrived' or b.get('terminal_status') != 'zero_target_duration_complete':
        errors.append('unexpected terminal status')
    repairs = a.get('stage_physics_repairs')
    expected_casters = {'/World/Jetbot/chassis/geometry/caster_ball_' + end + '/caster_ball_front'
                        for end in ('front', 'back')}
    if (not isinstance(repairs, list) or len(repairs) != 2 or
            {x.get('collider') for x in repairs} != expected_casters or any(
                x.get('original_resolved_targets') != [] or
                x.get('new_material') != '/World/Jetbot/caster_material' or
                abs(x.get('source_coefficients', {}).get('dynamic_friction', -1) - .01) > 1e-6 for x in repairs)):
        errors.append('caster repair evidence missing or inconsistent')
    overrides = a.get('stage_drive_effort_overrides')
    expected_joints = {'/World/Jetbot/chassis/' + side + '_wheel_joint' for side in ('left', 'right')}
    if (not isinstance(overrides, list) or len(overrides) != 2 or
            {x.get('joint_path') for x in overrides} != expected_joints or any(
                x.get('original_max_effort_nm') != 'infinity' or x.get('scene_max_effort_nm') != 1.0 or
                x.get('type') != 'force' for x in overrides)):
        errors.append('wheel effort overrides missing or inconsistent')
    for item in (positive, control):
        for key in ('native_drive_before', 'native_drive_after'):
            errors.extend(validate_drive_snapshot(item['metadata'].get(key)))
        if item['process'].get('exit_code') != 0:
            errors.append('nonzero queued simulator exit')
        if not all(text in item['log'] for text in ('Simulation App Startup Complete',
                    'isaacsim.replicator.experimental.mobility_gen-0.5.0',
                    'isaacsim.replicator.mobility_gen.examples-0.4.1')):
            errors.append('expected extension startup missing')
    snapshots = [m.get(key) for m in (a, b) for key in ('native_drive_before', 'native_drive_after')]
    if all(not validate_drive_snapshot(s) for s in snapshots):
        reference = snapshots[0]
        if any(s['drive_type_codes'] != reference['drive_type_codes'] or any(
                abs(x - y) > 1e-6 for key in ('max_effort_nm', 'stiffness', 'damping')
                for x, y in zip(s[key], reference[key])) for s in snapshots[1:]):
            errors.append('native wheel drive configuration differs across runs or task boundaries')
    if positive['rows'] and control['rows']:
        first, second = positive['rows'][0], control['rows'][0]
        start_distance = math.dist(first['base_position_m'], second['base_position_m'])
        quat_dot = abs(sum(x * y for x, y in zip(first['base_orientation_wxyz'], second['base_orientation_wxyz'])))
        if start_distance > .001 or abs(quat_dot - 1.0) > .0001:
            errors.append('initial chassis poses differ')
        if any(abs(v) > .05 for row in (first, second) for v in row['wheel_velocities_rad_s']):
            errors.append('initial raw wheel velocity readback exceeds fixed bound')
        def quaternion_angle(left, right):
            dot = abs(sum(x * y for x, y in zip(left, right)))
            norm = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
            return 2 * math.acos(min(1., max(0., dot / norm)))
        target = case.get('spawn_orientation_wxyz') if isinstance(case, dict) else None
        if (not isinstance(target, list) or len(target) != 4 or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in target)
                or abs(math.sqrt(sum(x*x for x in target)) - 1.) > 1e-6):
            errors.append('frozen initial orientation is invalid')
        elif any(quaternion_angle(row['base_orientation_wxyz'], target) > case.get('initial_orientation_tolerance_rad', .02)
                 for row in (first, second)):
            errors.append('initial chassis orientation differs from frozen spawn orientation')
        if quaternion_angle(first['base_orientation_wxyz'], second['base_orientation_wxyz']) > .01:
            errors.append('paired initial chassis orientations differ')
        spawn = case.get('spawn_position_m') if isinstance(case, dict) else None
        z_range = case.get('initial_z_range_m') if isinstance(case, dict) else None
        if (not isinstance(spawn, list) or len(spawn) != 3 or not isinstance(z_range, list) or len(z_range) != 2 or
                any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                    for x in spawn + z_range) or z_range[0] >= z_range[1]):
            errors.append('frozen initial position bounds are invalid')
        elif any(math.hypot(row['base_position_m'][0] - spawn[0], row['base_position_m'][1] - spawn[1]) >
                 case.get('initial_xy_tolerance_m', .02) or
                 not z_range[0] <= row['base_position_m'][2] <= z_range[1] for row in (first, second)):
            errors.append('initial chassis position differs from frozen spawn bounds')
        paired_fields = [('wheel_positions_rad', 'initial_pair_wheel_position_tolerance_rad', .001),
                         ('wheel_velocities_rad_s', 'initial_pair_wheel_velocity_tolerance_rad_s', .001),
                         ('base_com_linear_velocity_m_s', 'initial_pair_linear_velocity_tolerance_m_s', .005),
                         ('base_angular_velocity_rad_s', 'initial_pair_angular_velocity_tolerance_rad_s', .02)]
        for field, limit, default in paired_fields:
            if math.dist(first[field], second[field]) > case.get(limit, default):
                errors.append('paired initial state differs: ' + field)
        for field, limit, default in [('base_com_linear_velocity_m_s', 'initial_linear_speed_tolerance_m_s', .05),
                                      ('base_angular_velocity_rad_s', 'initial_angular_speed_tolerance_rad_s', .1)]:
            if any(math.sqrt(sum(x*x for x in row[field])) > case.get(limit, default) for row in (first, second)):
                errors.append('initial raw chassis velocity readback exceeds bound: ' + field)
        if any(abs(value) > 1e-9 for row in (first, second)
               for field in ('wheel_targets_rad_s', 'native_wheel_targets_rad_s') for value in row[field]):
            errors.append('initial drive target is not zero')
    else:
        start_distance = None
        errors.append('missing initial states')
    return {'passed': not errors, 'errors': errors, 'checks': checks, 'initial_chassis_difference_m': start_distance,
            'native_velocity_consistency': 'not_verified',
            'final_wheel_velocities_rad_s': {
                name: item['rows'][-1]['wheel_velocities_rad_s'] if item['rows'] else None
                for name, item in [('positive', positive), ('zero', control)]}}
