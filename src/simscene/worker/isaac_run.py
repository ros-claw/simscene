"""Run a USD stage in an Isaac Sim standalone process (experimental)."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from resources import sample as resource_sample
from contact_geometry import minimum_separation
# Always resolve SimScene imports from this run's frozen package snapshot.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

worker_started=time.monotonic()

parser = argparse.ArgumentParser()
parser.add_argument('scene')
parser.add_argument('output')
parser.add_argument('--steps', type=int, default=120)
parser.add_argument('--spec')
parser.add_argument('--seed',type=int)
parser.add_argument('--physics-device',choices=('default','cpu','gpu'),default='cpu')
parser.add_argument('--continue-on-controller-error',action='store_true')
parser.add_argument('--archive-case')
args = parser.parse_args()
if args.seed is not None:
    import random
    import numpy as np
    random.seed(args.seed);np.random.seed(args.seed)
from isaacsim import SimulationApp
app = SimulationApp({'headless': True, 'multi_gpu': False, 'active_gpu': int(os.getenv('SIMSCENE_GPU', '0'))})
recorders = {}
try:
    import omni.usd
    import omni.physx
    import omni.timeline
    from pxr import Usd, UsdGeom, UsdPhysics, Gf, PhysxSchema, PhysicsSchemaTools
    import isaacsim.core.experimental.utils.app as app_utils
    from isaacsim.core.simulation_manager import SimulationManager
    if not omni.usd.get_context().open_stage(args.scene):
        raise RuntimeError('Could not open stage')
    stage = omni.usd.get_context().get_stage()
    if not stage.GetPrimAtPath('/World/PhysicsScene'):
        physics = UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
        physics.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
        physics.CreateGravityMagnitudeAttr(9.81)
    if args.physics_device != 'default':
        scene_api=PhysxSchema.PhysxSceneAPI.Apply(stage.GetPrimAtPath('/World/PhysicsScene'))
        scene_api.CreateEnableGPUDynamicsAttr().Set(args.physics_device == 'gpu')
        scene_api.CreateBroadphaseTypeAttr().Set('GPU' if args.physics_device == 'gpu' else 'MBP')
    spec = json.load(open(args.spec)) if args.spec else {'objects': {}}
    archive_case=None;archived_objects={}
    if args.archive_case:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from simscene.verification.case_runner import _load as load_case
        from simscene.verification.archive_candidate import validate_case,evaluate_item
        archive_case=load_case(args.archive_case)
        validate_case(spec,archive_case)
    conveyors = [(name, obj['conveyor']) for name, obj in spec['objects'].items() if 'conveyor' in obj]
    if conveyors:
        from isaacsim.core.experimental.utils.app import enable_extension
        enable_extension('isaacsim.asset.gen.conveyor')
        app.update()
        from isaacsim.asset.gen.conveyor import create_conveyor_belt
        for name, config in conveyors:
            prim = stage.GetPrimAtPath('/World/' + name.replace('-', '_'))
            node = create_conveyor_belt(stage, prim)
            body = UsdPhysics.RigidBodyAPI(prim)
            body.CreateKinematicEnabledAttr(True)
            node.GetAttribute('inputs:direction').Set(Gf.Vec3f(*config['direction']))
            node.GetParent().GetAttribute('graph:variable:Velocity').Set(float(config['speed_m_s']))
    cameras = [(name, obj) for name, obj in spec['objects'].items() if obj.get('kind') == 'camera']
    sensors = {}
    preview_rates={name:obj.get('preview_fps',1 if 'record_fps' in obj else 0) for name,obj in cameras}
    if cameras:
        from isaacsim.sensors.experimental.rtx import TiledCameraSensor
        from simscene.worker.camera_frames import MAX_WARMUP_UPDATES, read_rgb
        for name, obj in cameras:
            # This API expects (height, width); keep frames landscape.
            sensors[name] = TiledCameraSensor('/World/' + name.replace('-', '_'), resolution=(480, 640), annotators=['rgb'])
        if any('record_fps' in obj for _,obj in cameras):
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from simscene.worker.video import VideoRecorder
            for name,obj in cameras:
                if 'record_fps' in obj:
                    recorders[name]=VideoRecorder(Path(args.output).parent/('camera_'+name+'.mp4'),obj['record_fps'])
    robot_configs = [(name, obj['pose_follower']) for name, obj in spec['objects'].items() if 'pose_follower' in obj]
    self_collision_settings={}
    for name,config in robot_configs:
        if 'self_collision_enabled' not in config:continue
        prefix='/World/'+name.replace('-', '_')+'/Asset'
        roots=[prim for prim in stage.Traverse() if (str(prim.GetPath())==prefix or str(prim.GetPath()).startswith(prefix+'/')) and prim.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots)!=1:raise RuntimeError(f'expected one articulation root for {name}, found {len(roots)}')
        api=PhysxSchema.PhysxArticulationAPI.Apply(roots[0])
        api.CreateEnabledSelfCollisionsAttr().Set(config['self_collision_enabled'])
        exclusions=[]
        for first,second in config.get('self_collision_exclusions',[]):
            a,b=stage.GetPrimAtPath(prefix+'/'+first),stage.GetPrimAtPath(prefix+'/'+second)
            if not a or not b or not a.HasAPI(UsdPhysics.RigidBodyAPI) or not b.HasAPI(UsdPhysics.RigidBodyAPI):
                raise RuntimeError(f'invalid self-collision exclusion for {name}: {first}, {second}')
            UsdPhysics.FilteredPairsAPI.Apply(a).CreateFilteredPairsRel().AddTarget(b.GetPath())
            exclusions.append([str(a.GetPath()),str(b.GetPath())])
        self_collision_settings[name]={'root':str(roots[0].GetPath()),'authored':bool(api.GetEnabledSelfCollisionsAttr().Get()),'excluded_body_pairs':exclusions}
    followers = {}
    if any('suction' in config for _,config in robot_configs):
        from isaacsim.core.experimental.utils.app import enable_extension
        enable_extension('isaacsim.robot.surface_gripper')
        app.update()
    if robot_configs:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from simscene.worker.follow import PoseFollower
        for name, config in robot_configs:
            followers[name] = PoseFollower('/World/' + name.replace('-', '_') + '/Asset', config)
    monitored={}
    for name,obj in spec['objects'].items():
        if obj.get('dynamic'):
            path='/World/'+name.replace('-', '_')
            prim=stage.GetPrimAtPath(path)
            if prim: PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr().Set(0)
            monitored[path]=name
    robot_paths=[]
    for name,config in robot_configs:
        if not config.get('monitor_collisions'): continue
        prefix='/World/'+name.replace('-', '_')+'/Asset'
        robot_paths.append((name,prefix))
        for prim in stage.Traverse():
            if str(prim.GetPath()).startswith(prefix+'/') and prim.HasAPI(UsdPhysics.RigidBodyAPI):
                PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr().Set(0)
    robot_contacts={}
    contacts={} 
    contacts_truncated=[False]
    contact_geometry_incomplete=[False]
    contact_start_steps=[None]
    def on_contact(headers,data):
        # Initialization updates happen before the frozen run timeline starts.
        # Do not mix those contacts into step zero of the reset task.
        if contact_start_steps[0] is None:return
        for header in headers:
            absolute=SimulationManager.get_num_physics_steps()
            contact_step=max(0,absolute-contact_start_steps[0])
            actors=[str(PhysicsSchemaTools.intToSdfPath(header.actor0)),str(PhysicsSchemaTools.intToSdfPath(header.actor1))]
            involved=[name for name,prefix in robot_paths if any(actor == prefix or actor.startswith(prefix+'/') for actor in actors)]
            separation,incomplete=minimum_separation(header,data) if involved else (None,False)
            if incomplete:contact_geometry_incomplete[0]=True
            def phase(name):
                return f"{name}:{getattr(followers[name], 'sequence_index', -1)}" if name else ''
            for name in involved:
                pair='|'.join(sorted(actors))+'|'+phase(name)
                if pair not in robot_contacts and len(robot_contacts)>=100000:
                    contacts_truncated[0]=True
                else:
                    record=robot_contacts.setdefault(pair,{'count':0,'first_physics_step':contact_step,'last_physics_step':0})
                    record['count']+=1
                    record['last_physics_step']=contact_step
                    if separation is not None:
                        record['minimum_separation_m']=min(record.get('minimum_separation_m',separation),separation)
            for index,actor in enumerate(actors):
                if actor not in monitored: continue
                # Record each relevant robot's phase independently. Combining
                # all arm phases causes a combinatorial explosion in long runs.
                for name in (involved or list(followers) or [None]):
                    key='|'.join([monitored[actor],actors[1-index],phase(name)])
                    if key not in contacts and len(contacts)>=50000:
                        contacts_truncated[0]=True
                        continue
                    record=contacts.setdefault(key,{'count':0,'first_physics_step':contact_step,'last_physics_step':0})
                    record['count']+=1
                    record['last_physics_step']=contact_step
    contact_subscription=omni.physx.get_physx_simulation_interface().subscribe_contact_report_events(on_contact) if monitored or robot_paths else None
    SimulationManager.set_physics_dt(1.0 / 60.0)
    app_utils.play()
    app.update()
    for follower in followers.values(): follower.initialize()
    for name in self_collision_settings:
        observed=followers[name].robot.get_enabled_self_collisions().numpy().reshape(-1)
        if len(observed)!=1:raise RuntimeError(f'cannot read self collision state for {name}')
        self_collision_settings[name]['runtime']=bool(observed[0])
        if self_collision_settings[name]['runtime']!=self_collision_settings[name]['authored']:
            raise RuntimeError(f'self collision setting did not take effect for {name}')
    # App updates drive both the graph and physics; count real physics steps.
    start_steps = SimulationManager.get_num_physics_steps()
    contact_start_steps[0]=start_steps
    start_time = SimulationManager.get_simulation_time()
    overlap_monitor=None
    diagnostic_prefixes=['/World/'+name.replace('-', '_')+'/Asset' for name,config in robot_configs if config.get('diagnose_overlaps')]
    if diagnostic_prefixes:
        from pxr import Sdf
        from simscene.worker.overlap_diagnostics import OverlapDiagnostics
        shapes=[]
        for prim in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
            path=str(prim.GetPath())
            if not path.startswith('/World/') or not prim.HasAPI(UsdPhysics.CollisionAPI):continue
            parent=prim
            while parent and not parent.HasAPI(UsdPhysics.RigidBodyAPI):parent=parent.GetParent()
            shapes.append({'path':path,'body':str(parent.GetPath()) if parent else path,'type':prim.GetTypeName()})
        query=omni.physx.get_physx_scene_query_interface()
        overlap_monitor=OverlapDiagnostics(shapes,query,lambda path:PhysicsSchemaTools.encodeSdfPath(Sdf.Path(path)),robot_prefixes=diagnostic_prefixes)
        overlap_monitor.sample(0)
    samples = []
    displays_present=any(obj.get('kind')=='counter' or 'indicator' in obj for obj in spec['objects'].values())
    display_last={}
    if displays_present:
        from simscene.display_runtime import update as update_displays
    resources=[resource_sample(0,worker_started)]
    pending={name:obj for name,obj in spec['objects'].items() if obj.get('spawn_step',0)>0}
    spawn_events=[]
    if pending:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from simscene.worker.spawn import spawn
    last_sample = 0
    stalled = 0
    while SimulationManager.get_num_physics_steps() - start_steps < args.steps:
        # Control is cooperative: pause the timeline while keeping the worker
        # and its scene alive, then resume from the same physics state.
        control=Path(args.output).parent/'control-request.json'
        if control.is_file():
            request=json.loads(control.read_text())
            if request.get('action')=='pause':
                import time
                app_utils.pause()
                state=Path(args.output).parent/'control-state.json'
                temp=state.with_suffix('.tmp')
                temp.write_text(json.dumps({'state':'paused','request_id':request.get('request_id')}));os.replace(temp,state)
                while True:
                    time.sleep(.1)
                    current=json.loads(control.read_text())
                    if current.get('action')=='resume':
                        app_utils.play()
                        temp.write_text(json.dumps({'state':'running','request_id':current.get('request_id')}));os.replace(temp,state)
                        break
        before = SimulationManager.get_num_physics_steps()
        for name,obj in list(pending.items()):
            if before-start_steps >= obj['spawn_step']:
                path=spawn(stage,name,obj)
                if overlap_monitor:
                    prim=stage.GetPrimAtPath(path)
                    overlap_monitor.add({'path':path,'body':path,'type':prim.GetTypeName()})
                spawn_events.append({'id':name,'path':path,'class_label':obj.get('class_label'),'physics_step':before-start_steps})
                del pending[name]
        for follower in followers.values(): follower.step((before - start_steps) / 60.0)
        if not args.continue_on_controller_error and any(follower.sequence_error for follower in followers.values()): break
        app.update()
        actual = SimulationManager.get_num_physics_steps() - start_steps
        if overlap_monitor and actual>overlap_monitor.last_step:
            overlap_monitor.sample(actual)
        if actual >= resources[-1]['physics_steps'] + 3600:
            resources.append(resource_sample(actual,worker_started))
        for name,sensor in sensors.items():
            recorder=recorders.get(name)
            next_step=(recorder.frames+1)*(60//recorder.fps) if recorder else None
            if recorder and actual>next_step:raise RuntimeError('Physics skipped a scheduled camera frame')
            record_due=bool(recorder and actual==next_step)
            preview_due=bool(preview_rates[name] and actual and actual%(60//preview_rates[name])==0)
            if record_due or preview_due:
                rgb=read_rgb(sensor)
                if rgb is None:
                    # Camera annotators can warm up later than the first
                    # requested frame. Pump rendering while physics is paused;
                    # never duplicate or silently skip a scheduled frame.
                    app_utils.pause()
                    try:
                        rgb=read_rgb(sensor,app.update,MAX_WARMUP_UPDATES)
                        if SimulationManager.get_num_physics_steps()-start_steps != actual:
                            raise RuntimeError('physics advanced while waiting for a camera frame')
                    finally:
                        app_utils.play()
                if rgb is None:raise RuntimeError(f'No RGB frame available for camera {name} at step {actual}')
                frame=rgb.numpy()
                if record_due:recorder.write(frame)
                if preview_due:
                    from PIL import Image
                    path=Path(args.output).parent/('camera_'+name+'_live.png')
                    temporary=path.with_suffix('.tmp')
                    Image.fromarray(frame).save(temporary,format='PNG')
                    os.replace(temporary,path)
        stalled = stalled + 1 if before == SimulationManager.get_num_physics_steps() else 0
        if stalled >= 120:
            raise RuntimeError('Physics did not advance for 120 app updates')
        if actual >= last_sample + 5 or actual >= args.steps:
            last_sample = actual
            cache = UsdGeom.XformCache()
            positions = {str(prim.GetPath()):list(cache.GetLocalToWorldTransform(prim).ExtractTranslation())
                         for prim in stage.Traverse() if prim.HasAPI(UsdPhysics.RigidBodyAPI)}
            orientations={}
            for path in monitored:
                prim=stage.GetPrimAtPath(path)
                if prim:
                    q=cache.GetLocalToWorldTransform(prim).RemoveScaleShear().ExtractRotationQuat()
                    orientations[path]=[q.GetReal(),*q.GetImaginary()]
            camera_poses={}
            if cameras:
                stage_time=omni.timeline.get_timeline_interface().get_current_time()*stage.GetTimeCodesPerSecond()
                camera_cache=UsdGeom.XformCache(Usd.TimeCode(stage_time))
                for name,_ in cameras:
                    prim=stage.GetPrimAtPath('/World/'+name.replace('-', '_'))
                    if not prim:continue
                    transform=camera_cache.GetLocalToWorldTransform(prim).RemoveScaleShear();rotation=transform.ExtractRotationQuat()
                    camera_poses[name]={'position':list(transform.ExtractTranslation()),'orientation_wxyz':[rotation.GetReal(),*rotation.GetImaginary()],'stage_time_code':stage_time}
            observation={'physics_steps':SimulationManager.get_num_physics_steps() - start_steps,
                         'simulation_time_s':SimulationManager.get_simulation_time() - start_time,
                         'positions':positions, 'orientations_wxyz':orientations,'cameras':camera_poses,
                         'followers':{name:follower.sample_state() for name,follower in followers.items()}}
            samples.append(observation)
            if archive_case and actual%30==0:
                for item in archive_case['objects']:
                    part=item['part_id'];robot=item['robot_id'];path=item['part_path']
                    if part in archived_objects or path not in positions:continue
                    follower=followers[robot]
                    transitions={t['index']:t['physics_step'] for t in follower.transitions}
                    retracted=transitions.get(item['release_phase']+2)
                    if retracted is None or actual<retracted+60:continue
                    prim=stage.GetPrimAtPath(path)
                    if not prim:continue
                    box=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render]).ComputeWorldBound(prim).ComputeAlignedRange()
                    if box.IsEmpty():continue
                    bounds={'min':list(box.GetMin()),'max':list(box.GetMax())}
                    event={'part_id':part,'class_label':item['class_label'],'terminal_state':'correct','physics_step':actual,
                           'simulation_time_s':observation['simulation_time_s'],'position':positions[path],'bounds':bounds}
                    view={'positions':positions,'bounds':{part:bounds},'samples':samples,'simulation_time_s':observation['simulation_time_s'],
                          'followers':{name:value.observe() for name,value in followers.items()},'contact_counts':contacts,
                          'robot_contacts':robot_contacts,'monitored_robot_ids':[name for name,config in robot_configs if config.get('monitor_collisions')],
                          'contacts_truncated':contacts_truncated[0],'archived_objects':archived_objects}
                    candidate=evaluate_item(view,spec,archive_case,item,event)
                    if not candidate['passed']:continue
                    # Persist the terminal evidence before removing any body.
                    with (Path(args.output).parent/'archive-ledger.jsonl').open('a') as ledger:
                        ledger.write(json.dumps(event)+'\n');ledger.flush();os.fsync(ledger.fileno())
                    if not stage.RemovePrim(path):raise RuntimeError('failed to remove archived object '+part)
                    if overlap_monitor:overlap_monitor.remove(path)
                    archived_objects[part]=event
            if displays_present:
                observation['displays']=update_displays(stage,spec,followers,spawn_events,archived_objects,archive_case is not None,display_last)
            if archive_case:
                from collections import Counter
                counts=Counter(event['class_label'] for event in archived_objects.values())
                initially_present=sum(1 for obj in spec['objects'].values() if obj.get('dynamic') and not obj.get('spawn_step',0))
                observation['verified_counts']={'total':len(archived_objects),'by_class':dict(counts),
                                                'spawned':initially_present+len(spawn_events),'pending':len(pending),
                                                'scope':'objects checked and archived against the pinned case; the case may be scene-derived and this is not independent acceptance or a final success rate'}
            if actual%30==0 or actual>=args.steps:
                path=Path(args.output).parent/'latest-observation.json'
                temporary=path.with_suffix('.tmp')
                temporary.write_text(json.dumps(observation))
                os.replace(temporary,path)
    actual_steps = SimulationManager.get_num_physics_steps() - start_steps
    if actual_steps != resources[-1]['physics_steps']:
        resources.append(resource_sample(actual_steps,worker_started))
    simulation_time = SimulationManager.get_simulation_time() - start_time
    data = {}
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            transform = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
            data[str(prim.GetPath())] = list(transform.ExtractTranslation())
    object_bounds={}
    bbox_cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render])
    for path,name in monitored.items():
        prim=stage.GetPrimAtPath(path)
        if not prim: continue
        box=bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if not box.IsEmpty(): object_bounds[name]={'min':list(box.GetMin()),'max':list(box.GetMax())}
    images = {}
    videos={name:recorder.close() for name,recorder in recorders.items()}
    recorders={}
    if sensors:
        from PIL import Image
        final_physics_steps=SimulationManager.get_num_physics_steps()
        app_utils.pause()
        for _ in range(5): app.update()
        for name, sensor in sensors.items():
            rgb=read_rgb(sensor,app.update,120)
            if rgb is None:
                raise RuntimeError(f'No RGB image available for camera {name}')
            if SimulationManager.get_num_physics_steps()!=final_physics_steps:
                raise RuntimeError('physics advanced while waiting for the final camera image')
            path = Path(args.output).parent / ('camera_' + name + '.png')
            Image.fromarray(rgb.numpy()).save(path)
            images[name] = str(path)
    with open(args.output, 'w') as f:
        json.dump({'requested_physics_steps':args.steps, 'actual_physics_steps':actual_steps, 'simulation_time_s':simulation_time, 'seed':args.seed, 'positions':data, 'object_classes':{name:obj.get('class_label') for name,obj in spec['objects'].items() if obj.get('dynamic')}, 'spawn_events':spawn_events, 'pending_spawn_ids':list(pending), 'archived_objects':archived_objects, 'bounds':object_bounds, 'samples':samples, 'resources':resources, 'images':images, 'videos':videos, 'followers':{name:follower.observe() for name,follower in followers.items()}, 'task_status':'failed' if any(follower.sequence_error for follower in followers.values()) else 'unverified', 'contact_counts':contacts, 'contacts_truncated':contacts_truncated[0], 'robot_contacts':robot_contacts, 'self_collision_settings':self_collision_settings, 'overlap_counts':overlap_monitor.counts if overlap_monitor else {}, 'overlap_diagnostics':overlap_monitor.summary() if overlap_monitor else None, 'contact_geometry_incomplete':contact_geometry_incomplete[0], 'monitored_robot_ids':[name for name,config in robot_configs if config.get('monitor_collisions')], 'contact_scope':'dynamic objects and explicitly enabled robot rigid bodies; reported separation covers PhysX contact points only and does not exclude unreported penetration'}, f, indent=2)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from simscene.evidence_integrity import seal
    seal(Path(args.output).parent)
    app_utils.stop()
except Exception as error:
    partial_videos={}
    for name,recorder in recorders.items():
        try:partial_videos[name]=recorder.close()
        except Exception:recorder.abort()
    # Preserve already observed evidence without querying a failed GPU context.
    try:
        observed=globals().get('samples',[])
        last=observed[-1] if observed else {}
        controller_records={}
        for name,follower in globals().get('followers',{}).items():
            sampled=last.get('followers',{}).get(name,{})
            controller_records[name]={**sampled,'sequence_index':getattr(follower,'sequence_index',None),
                'sequence_length':len(getattr(follower,'sequence',[])),'sequence_error':getattr(follower,'sequence_error',None),
                'transitions':getattr(follower,'transitions',[]),'suction_events':getattr(follower,'suction_events',[])}
        partial={'task_status':'failed','partial':True,'evidence_incomplete':True,'error':str(error),'requested_physics_steps':args.steps,
                 'actual_physics_steps':last.get('physics_steps',0),'simulation_time_s':last.get('simulation_time_s',0),
                 'positions':last.get('positions',{}),'samples':observed,'resources':globals().get('resources',[]),'bounds':{},'followers':controller_records,
                 'spawn_events':globals().get('spawn_events',[]),'pending_spawn_ids':list(globals().get('pending',{})),'archived_objects':globals().get('archived_objects',{}),
                 'contact_counts':globals().get('contacts',{}),'robot_contacts':globals().get('robot_contacts',{}),
                 'overlap_counts':globals()['overlap_monitor'].counts if globals().get('overlap_monitor') else {},
                 'overlap_diagnostics':globals()['overlap_monitor'].summary() if globals().get('overlap_monitor') else None,
                 'contacts_truncated':True, 'contact_geometry_incomplete':True,'videos':partial_videos}
        (Path(args.output).parent/'partial-result.json').write_text(json.dumps(partial,indent=2))
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from simscene.evidence_integrity import seal
        seal(Path(args.output).parent,'partial-result.json')
    except Exception:
        pass
    import traceback
    traceback.print_exc()
    sys.stderr.flush()
    app.close(exit_code=1)
    raise
else:
    app.close()
