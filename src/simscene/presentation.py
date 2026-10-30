"""Scene-independent camera proposals using measured subjects and action regions."""
import math
from .capture import PROFILES,finite
from .geometry import camera_orientation
from .placement import measure,vector
from .scene import SceneError

def plan(scene,subject_ids,regions=None,profile='technical_showcase_1080p',duration_s=75,max_cameras=2,azimuth_deg=-65):
    if profile not in PROFILES or not finite(duration_s) or not 1<=duration_s<=1200 or type(max_cameras) is not int or not 1<=max_cameras<=2 or not finite(azimuth_deg):raise SceneError('invalid presentation profile, duration or camera budget')
    measured=measure(scene,subject_ids)['objects'];boxes=[v['world_bounds_m'] for v in measured.values()]
    combined={'min':[min(b['min'][i] for b in boxes) for i in range(3)],'max':[max(b['max'][i] for b in boxes) for i in range(3)]}
    regions=regions or []
    if not isinstance(regions,list):raise SceneError('regions must be a list of named bounds')
    for r in regions:
        if not isinstance(r,dict) or set(r)-{'id','min','max','action','subject_ids'} or not isinstance(r.get('id'),str) or not vector(r.get('min')) or not vector(r.get('max')) or any(a>=b for a,b in zip(r['min'],r['max'])):raise SceneError('each region requires id, min and max in world metres')
    selections=[{'id':'overview',**combined}]+regions[:max_cameras-1]
    operations=[{'op':'set_presentation','presentation':{'profile':profile,'budget':{'max_cameras':max_cameras},'diagnostics':{'keyframe_interval_s':10}}}]
    cameras=[]
    for index,region in enumerate(selections):
        center=[(a+b)/2 for a,b in zip(region['min'],region['max'])];radius=math.sqrt(sum((b-a)**2 for a,b in zip(region['min'],region['max'])))/2
        width,height=PROFILES[profile]['resolution'];horizontal=36;focal=35
        vfov=2*math.atan(horizontal*height/width/(2*focal));distance=max(.3,radius/math.sin(vfov/2)*1.12)
        azimuth=math.radians(azimuth_deg);elevation=math.radians(30 if index==0 else 18)
        direction=[math.cos(azimuth)*math.cos(elevation),math.sin(azimuth)*math.cos(elevation),math.sin(elevation)]
        position=[center[i]+distance*direction[i] for i in range(3)]
        name='presentation_'+str(index)
        if name in scene['objects']:raise SceneError('presentation camera ID exists; update it explicitly or remove before replanning')
        camera={'kind':'camera','position':position,'orientation_wxyz':camera_orientation(position,center),
                'record_fps':PROFILES[profile]['fps'],'preview_fps':1,
                'camera':{'resolution':PROFILES[profile]['resolution'],'focal_length_mm':focal,'horizontal_aperture_mm':horizontal,'focus_distance_m':distance,'f_stop':0}}
        operations.append({'op':'add','id':name,'object':camera})
        cameras.append({'id':name,'region_id':region['id'],'target_m':center,'distance_m':distance,'action':region.get('action'),'subject_ids':region.get('subject_ids',subject_ids)})
    existing=[n for n,o in scene['objects'].items() if o.get('kind')=='camera']
    return {'base_revision':scene['revision'],'operations':operations,'cameras':cameras,'measured_subjects':measured,
            'existing_camera_ids':existing,'requested_duration_s':duration_s,
            'lighting_guidance':'preserve imported materials; preview existing lights and locked exposure before changing them',
            'review_required':['camera occlusion and action-region coverage','rendered white/metal highlights','existing recording cameras count against budget','camera and lighting are proposals; inspect native preview before recording']}

def events(directory):
    """Resolve transition meanings from the run's frozen sequence, never names."""
    import json
    from pathlib import Path
    root=Path(directory);result=json.loads((root/'result.json').read_text());spec=json.loads((root/'spec.json').read_text());output=[]
    for owner,record in result.get('followers',{}).items():
        sequence=spec['objects'].get(owner,{}).get('pose_follower',{}).get('sequence',[])
        for transition in record.get('transitions',[]):
            index=transition.get('index');step=transition.get('physics_step')
            if type(index) is not int or not 0<=index<len(sequence) or type(step) is not int:continue
            phase=sequence[index];output.append({'kind':phase.get('type'),'owner_id':owner,'object_id':phase.get('object') or phase.get('required_object'),
                'physics_step':step,'sim_time_s':step/60,'phase_index':index,'gripper_state':phase.get('state'),'gripper_value':phase.get('value'),'parameters':phase})
    for name,event in result.get('archived_objects',{}).items():
        output.append({'kind':'verified_archive','object_id':name,'physics_step':event['physics_step'],'sim_time_s':event['physics_step']/60,'class_label':event.get('class_label'),'scope':'verified against this run pinned case'})
    for event in result.get('spawn_events',[]):output.append({'kind':'spawn','object_id':event['id'],'physics_step':event['physics_step'],'sim_time_s':event['physics_step']/60})
    return sorted(output,key=lambda e:e['physics_step'])
