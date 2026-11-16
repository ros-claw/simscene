"""Fixed-route probe with explicit scene-local source caster material repair.

The stock example writes instantaneous wheel velocities. This adapter sends
PhysX drive velocity targets instead and never calls replay or task-time reset.
"""
import argparse
import hashlib
import json
import math
import os
import random
from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
CASE = json.loads((HERE / 'fixed_case.json').read_text())
parser = argparse.ArgumentParser()
parser.add_argument('--mode', required=True, choices=['positive', 'zero'])
parser.add_argument('--steps', type=int, default=CASE['task_step_budget'])
parser.add_argument('--output', required=True)
parser.add_argument('--asset', required=True)
args = parser.parse_args()
run_dir = Path(args.output).resolve()
if not run_dir.is_dir() or (run_dir / 'metadata.json').exists() or (run_dir / 'telemetry.jsonl').exists():
    raise SystemExit('output must be an empty, existing run directory')
if args.steps != CASE['task_step_budget']:
    raise SystemExit('the frozen fixed horizon requires exactly 600 task steps')
asset = Path(args.asset).expanduser().absolute()
from asset_lock import verify_asset_files
verify_asset_files(asset, json.loads((HERE / 'asset-lock.json').read_text()))
isaac_root = Path(os.environ['ISAAC_PATH']).resolve()
version = (isaac_root / 'VERSION').read_text().strip()
if version != '6.2.0-rc.14+release.52805.02189a84.gl':
    raise SystemExit(f'untested Isaac version: {version}')

metadata = {'mode': args.mode, 'case': CASE, 'requested_steps': args.steps,
            'script_name': Path(__file__).name,
            'case_sha256': hashlib.sha256((HERE / 'fixed_case.json').read_bytes()).hexdigest(),
            'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'isaac_version': version,
            'asset_sha256': hashlib.sha256(asset.read_bytes()).hexdigest(),
            'drive_adapter': 'set_dof_velocity_targets; no task-time joint-state setter',
            'trajectory_adapter': 'fixed BFS endpoints; MobilityGen path-following controller',
            'collision_adapter': 'meters converted to pixels through buffered_meters; no automatic reset'}
(run_dir / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
app = None
try:
    if type(CASE.get('seed')) is not int or not 0 <= CASE['seed'] < 2**32:
        raise ValueError('frozen seed must be a 32-bit integer')
    random.seed(CASE['seed'])
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'multi_gpu': False,
                         'active_gpu': int(os.environ.get('SIMSCENE_GPU', '0'))})

    import numpy as np
    np.random.seed(CASE['seed'])
    metadata.update(seed=CASE['seed'], seeded_rngs=['python.random', 'numpy.random'])
    import omni.usd
    import omni.physx
    from pxr import Gf, PhysxSchema, PhysicsSchemaTools, Usd, UsdGeom, UsdPhysics, UsdShade
    import isaacsim.core.experimental.utils.app as app_utils
    from isaacsim.core.experimental.prims import Articulation, RigidPrim
    from isaacsim.core.simulation_manager import SimulationManager, SimulationEvent
    app_utils.enable_extension('isaacsim.replicator.mobility_gen.examples')
    app.update()
    from isaacsim.replicator.experimental.mobility_gen import MobilityGenScenario, OccupancyMap, Buffer
    from isaacsim.replicator.experimental.mobility_gen.impl.path_planner import generate_paths, compress_path
    from isaacsim.replicator.experimental.mobility_gen.impl.utils.path_utils import PathHelper
    from isaacsim.replicator.mobility_gen.examples import JetbotRobot, RandomPathFollowingScenario
    from isaacsim.robot.experimental.wheeled_robots import DifferentialController

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, '/World')
    stage.SetDefaultPrim(world.GetPrim())
    physics = UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
    physics.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
    physics.CreateGravityMagnitudeAttr(9.81)
    pscene = PhysxSchema.PhysxSceneAPI.Apply(physics.GetPrim())
    pscene.CreateEnableGPUDynamicsAttr().Set(False)
    pscene.CreateBroadphaseTypeAttr().Set('MBP')
    pscene.CreateSolverTypeAttr().Set(CASE['solver_type'])
    pscene.CreateEnableExternalForcesEveryIterationAttr().Set(CASE['enable_external_forces_every_iteration'])

    def static_cube(path, center, size):
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.0)
        xf = UsdGeom.XformCommonAPI(cube)
        xf.SetTranslate(Gf.Vec3d(*center))
        xf.SetScale(Gf.Vec3f(*size))
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())

    static_cube('/World/Ground', (0, 0, -0.05), (4, 4, 0.1))
    static_cube('/World/WallEast', (1.95, 0, 0.25), (0.1, 4, 0.5))
    static_cube('/World/WallWest', (-1.95, 0, 0.25), (0.1, 4, 0.5))
    static_cube('/World/WallNorth', (0, 1.95, 0.25), (4, 0.1, 0.5))
    static_cube('/World/WallSouth', (0, -1.95, 0.25), (4, 0.1, 0.5))
    root = UsdGeom.Xform.Define(stage, '/World/Jetbot').GetPrim()
    root.GetReferences().AddReference(str(asset))
    UsdGeom.XformCommonAPI(root).SetTranslate(Gf.Vec3d(*CASE['spawn_position_m']))
    # The source instances bind an absolute /jetbot/caster_material outside
    # their reference scope, so USD drops that relationship. Repair only the
    # composed scene, keeping the source USD unchanged and restoring the
    # existing source-authored material and its original parameters.
    material_path = '/World/Jetbot/caster_material'
    material_prim = stage.GetPrimAtPath(material_path)
    material = UsdShade.Material(material_prim)
    material_api = UsdPhysics.MaterialAPI(material_prim)
    coefficients = {'static_friction': material_api.GetStaticFrictionAttr().Get(),
                    'dynamic_friction': material_api.GetDynamicFrictionAttr().Get(),
                    'restitution': material_api.GetRestitutionAttr().Get()}
    if not material or not material_prim.HasAPI(UsdPhysics.MaterialAPI) or any(
            abs(coefficients[k] - v) > 1e-6 for k, v in
            [('static_friction', .01), ('dynamic_friction', .01), ('restitution', .1)]):
        raise RuntimeError('source caster material missing or parameters changed')
    repairs = []
    for end in ('front', 'back'):
        parent = stage.GetPrimAtPath('/World/Jetbot/chassis/geometry/caster_ball_' + end)
        if not parent or not parent.IsInstance() or not parent.SetInstanceable(False):
            raise RuntimeError(f'cannot expand expected caster instance: {end}')
        collider = stage.GetPrimAtPath(str(parent.GetPath()) + '/caster_ball_front')
        if not collider or not collider.HasAPI(UsdPhysics.CollisionAPI):
            raise RuntimeError(f'expected caster collider missing: {end}')
        old = [str(x) for x in collider.GetRelationship('material:binding:physics').GetTargets()]
        if old:
            raise RuntimeError(f'expected broken source binding, found {old}')
        if not UsdShade.MaterialBindingAPI.Apply(collider).Bind(material, materialPurpose='physics'):
            raise RuntimeError(f'cannot author caster physics material: {end}')
        actual, _ = UsdShade.MaterialBindingAPI(collider).ComputeBoundMaterial(materialPurpose='physics')
        if not actual or str(actual.GetPath()) != material_path:
            raise RuntimeError(f'caster physics material did not resolve: {end}')
        repairs.append({'collider': str(collider.GetPath()), 'original_resolved_targets': old,
                        'new_material': material_path, 'source_coefficients': coefficients,
                        'action': 'deinstance and restore source-authored physics material in scene only'})
    metadata['stage_physics_repairs'] = repairs
    drive_repairs = []
    for name in CASE['wheel_names']:
        joint_path = '/World/Jetbot/chassis/' + name
        joint = stage.GetPrimAtPath(joint_path)
        drive = UsdPhysics.DriveAPI.Get(joint, 'angular')
        if not joint or not drive or drive.GetTypeAttr().Get() != 'force':
            raise RuntimeError(f'expected angular force drive missing: {joint_path}')
        original = drive.GetMaxForceAttr().Get()
        if not math.isinf(original):
            raise RuntimeError(f'expected original unbounded effort, got {original}')
        if not drive.GetMaxForceAttr().Set(CASE['wheel_max_effort_nm']):
            raise RuntimeError(f'cannot set finite effort on {joint_path}')
        authored = drive.GetMaxForceAttr().Get()
        if abs(authored - CASE['wheel_max_effort_nm']) > 1e-6:
            raise RuntimeError(f'finite drive effort was not authored on {joint_path}')
        drive_repairs.append({'joint_path': joint_path, 'type': drive.GetTypeAttr().Get(),
                              'original_max_effort_nm': 'infinity', 'scene_max_effort_nm': authored,
                              'stiffness_usd': drive.GetStiffnessAttr().Get(),
                              'damping_usd': drive.GetDampingAttr().Get()})
    metadata['stage_drive_effort_overrides'] = drive_repairs
    robot_bodies = []
    for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr().Set(0)
            robot_bodies.append(str(prim.GetPath()))
    if len(robot_bodies) != 3:
        raise RuntimeError(f'expected 3 robot rigid bodies: {robot_bodies}')

    pending_contacts = []
    def contact_callback(headers, data):
        for header in headers:
            if getattr(header, 'num_contact_data', 0) <= 0:
                continue
            actors = [str(PhysicsSchemaTools.intToSdfPath(header.actor0)),
                      str(PhysicsSchemaTools.intToSdfPath(header.actor1))]
            if any(a == '/World/Jetbot' or a.startswith('/World/Jetbot/') for a in actors):
                pending_contacts.append(actors)
    subscription = omni.physx.get_physx_simulation_interface().subscribe_contact_report_events(contact_callback)

    app.update()  # load stage while timeline remains stopped
    SimulationManager.setup_simulation(dt=CASE['physics_dt_s'], device='cpu')
    scenes = SimulationManager.get_physics_scenes()
    if len(scenes) != 1:
        raise RuntimeError(f'expected one physics scene, got {len(scenes)}')
    scenes[0].set_enabled_gpu_dynamics(False)
    if str(SimulationManager.get_physics_sim_device()) != 'cpu':
        raise RuntimeError('physics device is not CPU')
    app_utils.play()
    app.update()  # SDK warmup occurs before task time
    app_utils.pause()
    if not app_utils.is_paused():
        raise RuntimeError('timeline failed to pause for controlled stepping')
    settings = {'solver_type': pscene.GetSolverTypeAttr().Get(),
                'enable_external_forces_every_iteration': pscene.GetEnableExternalForcesEveryIterationAttr().Get()}
    if settings != {'solver_type': CASE['solver_type'],
                    'enable_external_forces_every_iteration': CASE['enable_external_forces_every_iteration']}:
        raise RuntimeError('PhysX scene settings differ from the frozen USD attributes')
    metadata['observed_solver_settings_usd'] = settings

    art = Articulation('/World/Jetbot')
    chassis = RigidPrim('/World/Jetbot/chassis')
    if not art.is_physics_tensor_entity_valid() or not chassis.is_physics_tensor_entity_valid():
        raise RuntimeError('robot articulation or chassis tensor is invalid')
    if set(art.dof_names) != set(CASE['wheel_names']) or len(art.dof_names) != 2:
        raise RuntimeError(f'unexpected physical DOFs: {art.dof_names}')
    dof_indices = art.get_dof_indices(CASE['wheel_names'])
    dof_index_list = dof_indices.numpy().tolist()
    native_view = art._physics_articulation_view
    if native_view is None:
        raise RuntimeError('native PhysX articulation view is missing')
    native_dof_paths = list(native_view.dof_paths[0])
    native_link_paths = list(native_view.link_paths[0])
    expected_dofs = ['/World/Jetbot/chassis/' + name for name in CASE['wheel_names']]
    if (len(native_dof_paths) != 2 or len(set(native_dof_paths)) != 2 or
            [native_dof_paths[i] for i in dof_index_list] != expected_dofs or
            len(native_link_paths) != 3 or set(native_link_paths) != set(robot_bodies)):
        raise RuntimeError(f'native body or DOF paths differ from frozen paths: {native_dof_paths}, {native_link_paths}')
    native_chassis = chassis._physics_rigid_body_view
    if native_chassis is None:
        raise RuntimeError('native chassis rigid-body view is missing')
    def native_wheels(getter):
        values = np.asarray(getter().numpy())
        if values.shape != (1, 2):
            raise RuntimeError(f'unexpected native drive tensor shape: {values.shape}')
        return values[0, dof_index_list].tolist()
    def native_drive_snapshot():
        return {'drive_type_codes': [int(v) for v in native_wheels(native_view.get_drive_types)],
                'max_effort_nm': native_wheels(native_view.get_dof_max_forces),
                'stiffness': native_wheels(native_view.get_dof_stiffnesses),
                'damping': native_wheels(native_view.get_dof_dampings)}
    from evaluate import validate_drive_snapshot
    native_drive_before = native_drive_snapshot()
    errors = validate_drive_snapshot(native_drive_before)
    if errors:
        raise RuntimeError('native drive readback failed: ' + ', '.join(errors))
    controller = DifferentialController(wheel_radius=CASE['wheel_radius_m'], wheel_base=CASE['wheel_base_m'],
        max_linear_speed=CASE['target_speed_m_s'], max_angular_speed=CASE['maximum_yaw_rate_rad_s'],
        max_wheel_speed=CASE['maximum_wheel_speed_rad_s'])
    step_count = [0]
    def post_step(dt, context):
        if abs(dt - CASE['physics_dt_s']) > 1e-8:
            raise RuntimeError(f'unexpected physics callback dt {dt}')
        step_count[0] += 1
    callback_id = SimulationManager.register_callback(post_step, event=SimulationEvent.PHYSICS_POST_STEP)
    def step_once():
        previous = step_count[0]
        SimulationManager.step(steps=1)
        if step_count[0] != previous + 1:
            raise RuntimeError(f'expected one physics callback, got {step_count[0] - previous}')

    class DriveTargetJetbot(JetbotRobot):
        path_following_speed = CASE['target_speed_m_s']
        path_following_stop_distance_threshold = CASE['arrival_distance_m']
        path_following_target_point_offset_meters = CASE['lookahead_m']

        def write_action(self, step_size):
            requested = np.asarray(self.action.get_value(), dtype=np.float64)
            applied = np.zeros(2) if args.mode == 'zero' else requested
            wheel = np.asarray(self.controller.forward(command=applied), dtype=np.float32)
            self.articulation.set_dof_velocity_targets(wheel[np.newaxis], dof_indices=dof_indices)
            self.last_twist = applied.tolist()
            self.last_wheel_targets = wheel.tolist()

    robot = DriveTargetJetbot('/World/Jetbot', art, controller, front_camera=None)
    robot.action.set_value(np.zeros(2))
    robot.write_action(CASE['physics_dt_s'])
    for _ in range(CASE['settling_steps']):
        step_once()
    settled_contacts = list(pending_contacts)
    pending_contacts.clear()

    # Reproduce the stock controller while fixing its pixel-vs-meter buffer call.
    # Random reset is deliberately never invoked.
    shape = tuple(CASE['map_shape'])
    free = np.ones(shape, dtype=bool)
    border = CASE['map_border_cells']
    free[:border, :] = free[-border:, :] = False
    free[:, :border] = free[:, -border:] = False
    occupancy = OccupancyMap.from_masks(free, ~free, CASE['map_resolution_m'], tuple(CASE['map_origin_xyyaw']))

    class FixedScenario(RandomPathFollowingScenario):
        def __init__(self, robot, occupancy_map):
            MobilityGenScenario.__init__(self, robot, occupancy_map)
            self.is_alive = True
            self.target_path = Buffer()
            self.collision_occupancy_map = occupancy_map.buffered_meters(robot.occupancy_map_collision_radius)

    scenario = FixedScenario(robot, occupancy)
    start_px = np.rint(occupancy.world_to_pixel_numpy(np.array([[0.0, 0.0]])))[0].astype(int)
    end_px = np.rint(occupancy.world_to_pixel_numpy(np.array([CASE['goal_xy_m']])))[0].astype(int)
    graph = generate_paths((int(start_px[1]), int(start_px[0])), scenario.buffered_occupancy_map.freespace_mask())
    end = (int(end_px[1]), int(end_px[0]))
    if not graph.visited[end]:
        raise RuntimeError('fixed goal is not reachable on occupancy map')
    points, _ = compress_path(graph.unroll_path(end))
    path = occupancy.pixel_to_world_numpy(points[:, ::-1])
    if len(path) < 2 or np.linalg.norm(path[-1] - np.array(CASE['goal_xy_m'])) > 1e-6:
        raise RuntimeError(f'bad reconstructed fixed path: {path.tolist()}')
    scenario.target_path.set_value(path)
    scenario.target_path_helper = PathHelper(path)
    metadata.update({'robot_bodies': robot_bodies, 'dof_names': art.dof_names,
                     'wheel_dof_indices': dof_index_list, 'path_xy_m': path.tolist(),
                     'native_dof_paths': native_dof_paths, 'native_link_paths': native_link_paths,
                     'native_drive_before': native_drive_before,
                     'observed_physics_device': str(SimulationManager.get_physics_sim_device()),
                     'observed_physics_dt_s': SimulationManager.get_physics_dt(),
                     'ground_contacts_during_settling': sum(any('/World/Ground' in a for a in p) for p in settled_contacts)})
    (run_dir / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')

    goal = CASE['goal_xy_m']
    def sample(step, contacts):
        transforms = np.asarray(native_chassis.get_transforms().numpy())
        velocities = np.asarray(native_chassis.get_velocities().numpy())
        if transforms.shape != (1, 7) or velocities.shape != (1, 6):
            raise RuntimeError('native chassis transform or velocity has an invalid shape')
        pos = transforms[0, :3].tolist()
        quat = transforms[0, [6, 3, 4, 5]].tolist()
        base_linear = velocities[0, :3].tolist()
        base_angular = velocities[0, 3:].tolist()
        positions = art.get_dof_positions(dof_indices=dof_indices).numpy().reshape(-1).tolist()
        velocities = art.get_dof_velocities(dof_indices=dof_indices).numpy().reshape(-1).tolist()
        robot.update_state()
        pose = robot.get_pose_2d()
        ground = any(any(a == '/World/Ground' or a.startswith('/World/Ground/') for a in pair) for pair in contacts)
        obstacle = any(any(a.startswith('/World/Wall') for a in pair) for pair in contacts)
        distance = math.hypot(goal[0] - pos[0], goal[1] - pos[1])
        return {'step': step, 'physics_callback_count': step_count[0], 'time_s': step * CASE['physics_dt_s'],
                'base_position_m': pos, 'base_orientation_wxyz': quat,
                'base_com_linear_velocity_m_s': base_linear, 'base_angular_velocity_rad_s': base_angular,
                'wheel_positions_rad': positions, 'wheel_velocities_rad_s': velocities,
                'wheel_targets_rad_s': list(robot.last_wheel_targets), 'twist_command': list(robot.last_twist),
                'native_wheel_targets_rad_s': native_wheels(native_view.get_dof_velocity_targets),
                'goal_distance_m': distance, 'arrived': distance <= CASE['arrival_distance_m'],
                'obstacle_collision': obstacle,
                'map_out_of_bounds': not scenario.collision_occupancy_map.check_world_point_in_bounds(pose),
                'map_collision': not scenario.collision_occupancy_map.check_world_point_in_freespace(pose),
                'ground_contact': ground, 'contact_actor_pairs': contacts}

    terminal_status = None
    with (run_dir / 'telemetry.jsonl').open('x', encoding='utf8') as stream:
        initial = sample(0, settled_contacts)
        stream.write(json.dumps(initial, allow_nan=False) + '\n'); stream.flush()
        for step in range(1, args.steps + 1):
            pending_contacts.clear()
            if terminal_status is None:
                alive = scenario.step(CASE['physics_dt_s'])
                if not alive:
                    robot.action.set_value(np.zeros(2)); robot.write_action(CASE['physics_dt_s'])
                    pose = robot.get_pose_2d()
                    if not scenario.collision_occupancy_map.check_world_point_in_bounds(pose):
                        terminal_status = 'map_out_of_bounds'
                    elif not scenario.collision_occupancy_map.check_world_point_in_freespace(pose):
                        terminal_status = 'map_collision'
                    elif math.hypot(goal[0] - pose.x, goal[1] - pose.y) < CASE['arrival_distance_m']:
                        terminal_status = 'arrived'
                    else:
                        terminal_status = 'unknown_controller_stop'
            else:
                robot.action.set_value(np.zeros(2)); robot.write_action(CASE['physics_dt_s'])
            step_once()
            row = sample(step, list(pending_contacts))
            if row['obstacle_collision']:
                terminal_status = 'obstacle_collision'
            elif row['map_out_of_bounds']:
                terminal_status = 'map_out_of_bounds'
            elif row['map_collision']:
                terminal_status = 'map_collision'
            row['terminal_status'] = terminal_status
            stream.write(json.dumps(row, allow_nan=False) + '\n'); stream.flush()
    if terminal_status is None:
        terminal_status = 'zero_target_duration_complete' if args.mode == 'zero' else 'timeout'
    native_drive_after = native_drive_snapshot()
    errors = validate_drive_snapshot(native_drive_after)
    if errors:
        raise RuntimeError('native final drive readback failed: ' + ', '.join(errors))
    metadata.update(native_drive_after=native_drive_after, terminal_status=terminal_status,
                    actual_task_steps=step_count[0] - CASE['settling_steps'])
    (run_dir / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    from evaluate import evaluate_horizon
    rows = [json.loads(line) for line in (run_dir / 'telemetry.jsonl').read_text().splitlines()]
    result = evaluate_horizon(rows, args.mode)
    expected_terminal = 'arrived' if args.mode == 'positive' else 'zero_target_duration_complete'
    if terminal_status != expected_terminal:
        result['passed'] = False
        result['errors'].append(f'unexpected terminal status {terminal_status}')
    result['terminal_status'] = terminal_status
    (run_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('RESULT', json.dumps(result), flush=True)
    if not result['passed']:
        raise RuntimeError('independent experiment checks did not pass')
except BaseException:
    (run_dir / 'failure.txt').write_text(traceback.format_exc())
    raise
finally:
    if app is not None:
        app.close()
