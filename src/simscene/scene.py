"""Persistent, revisioned scene specifications and atomic edits."""
import copy
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

class SceneError(ValueError):
    pass

def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value):
        raise SceneError('ID must start with a letter and contain only letters, numbers, - or _')
    return value

def validate(scene):
    issues = []
    normalized={}
    if 'presentation' in scene:
        from .capture import validate_presentation
        try: validate_presentation(scene['presentation'])
        except (ValueError, TypeError) as error: issues.append({'object':None,'message':str(error)})
    for name in scene['objects']:
        try:_id(name)
        except SceneError:
            issues.append({'object':str(name),'message':'invalid object ID'})
            continue
        usd_name=name.replace('-','_')
        if usd_name in ('Looks','PhysicsScene'):
            issues.append({'object':name,'message':'object name is reserved for scene infrastructure'})
        if usd_name in normalized:
            issues.append({'object':name,'message':f'USD path collides with object {normalized[usd_name]}'})
        normalized[usd_name]=name
    for name, obj in scene['objects'].items():
        if not isinstance(obj, dict):
            issues.append({'object': name, 'message': 'object must be a mapping'})
            continue
        allowed = {'kind', 'position', 'size', 'asset_path', 'asset_physics', 'asset_lights', 'asset_metrics', 'color', 'material', 'material_overrides', 'collision', 'dynamic', 'intensity', 'light', 'orientation_wxyz', 'conveyor', 'pose_follower', 'variants', 'spawn_step', 'mass_kg', 'class_label', 'record_fps', 'preview_fps', 'camera_orbit','camera_path','camera','support_surfaces','counter','indicator'}
        unknown = set(obj) - allowed
        if unknown:
            issues.append({'object':name, 'message':f'unsupported fields: {sorted(unknown)}'})
        orientation = obj.get('orientation_wxyz', [1, 0, 0, 0])
        if not isinstance(orientation, list) or len(orientation) != 4 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in orientation) or abs(sum(x*x for x in orientation) - 1) > 1e-4:
            issues.append({'object':name, 'message':'orientation_wxyz must be a normalized quaternion'})
        color = obj.get('color', [1, 1, 1])
        if not isinstance(color, list) or len(color) != 3 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 <= x <= 1 for x in color):
            issues.append({'object':name, 'message':'color must contain three numbers between 0 and 1'})
        if 'material' in obj:
            material=obj['material']
            if obj.get('kind') not in ('box','sphere','asset') or not isinstance(material,dict) or set(material)-{'color','roughness','metallic','opacity','emissive'}:
                issues.append({'object':name,'message':'material requires a supported geometry and material fields'})
            else:
                for field in ('color','emissive'):
                    value=material.get(field,[0,0,0])
                    if not isinstance(value,list) or len(value)!=3 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<=1 for x in value):
                        issues.append({'object':name,'message':f'material {field} must contain three numbers between 0 and 1'})
                for field in ('roughness','metallic','opacity'):
                    value=material.get(field,0)
                    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not 0<=value<=1:
                        issues.append({'object':name,'message':f'material {field} must be between 0 and 1'})
        if 'asset_lights' in obj and (obj.get('kind')!='asset' or obj['asset_lights'] not in ('preserve','disabled')):
            issues.append({'object':name,'message':'asset_lights requires preserve or disabled on an asset'})
        if 'asset_metrics' in obj:
            metrics=obj['asset_metrics']
            if obj.get('kind')!='asset' or not isinstance(metrics,dict) or set(metrics)-{'meters_per_unit','up_axis','reason'} or not isinstance(metrics.get('reason'),str) or len(metrics['reason'].strip())<8 or not isinstance(metrics.get('meters_per_unit',1),(int,float)) or isinstance(metrics.get('meters_per_unit',1),bool) or not math.isfinite(metrics.get('meters_per_unit',1)) or not 1e-9<=metrics.get('meters_per_unit',1)<=1e9 or metrics.get('up_axis','Z') not in ('Y','Z'):
                issues.append({'object':name,'message':'asset_metrics requires explicit finite units/axis and an inspection reason'})
        if 'asset_physics' in obj and (obj.get('kind')!='asset' or obj['asset_physics'] not in ('preserve','visual_only') or obj.get('pose_follower')):
            issues.append({'object':name,'message':'asset_physics requires a controller-free asset with preserve or visual_only policy'})
        if 'material_overrides' in obj:
            overrides=obj['material_overrides']
            if obj.get('kind')!='asset' or not isinstance(overrides,dict) or not overrides:
                issues.append({'object':name,'message':'material_overrides require an imported asset and relative prim paths'})
            else:
                for relative,config in overrides.items():
                    if not isinstance(relative,str) or not relative or relative.startswith('/') or any(part in ('','.','..') for part in relative.split('/')):
                        issues.append({'object':name,'message':'material override paths must be relative to Asset'})
                    else:
                        issues.extend({'object':name,'message':'material override '+relative+': '+issue['message']} for issue in validate({'objects':{'selection':{'kind':'box','material':config}}}))
        for field in ('collision', 'dynamic'):
            if field in obj and not isinstance(obj[field], bool):
                issues.append({'object':name, 'message':f'{field} must be boolean'})
            elif field in obj and obj.get('kind') not in ('box','sphere'):
                issues.append({'object':name,'message':f'{field} is only authored for primitive geometry; inspect asset physics separately'})
        if 'intensity' in obj:
            intensity=obj['intensity']
            if obj.get('kind')!='light' or not isinstance(intensity,(int,float)) or isinstance(intensity,bool) or not math.isfinite(intensity) or intensity<0:
                issues.append({'object':name,'message':'light intensity must be a nonnegative finite number'})
        if 'light' in obj:
            light=obj['light']
            supported={'distant':set(), 'dome':set(), 'sphere':{'radius_m'}, 'rect':{'width_m','height_m'}}
            style=light.get('type','distant') if isinstance(light,dict) else None
            if obj.get('kind')!='light' or not isinstance(light,dict) or not isinstance(style,str) or style not in supported or set(light)-({'type','color','exposure'}|supported.get(style,set())):
                issues.append({'object':name,'message':'light requires distant, dome, sphere or rect type and matching fields'})
            else:
                light_color=light.get('color',[1,1,1]); exposure=light.get('exposure',0)
                if not isinstance(light_color,list) or len(light_color)!=3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=1 for v in light_color):
                    issues.append({'object':name,'message':'light color must contain three values between 0 and 1'})
                if not isinstance(exposure,(int,float)) or isinstance(exposure,bool) or not math.isfinite(exposure) or not -20<=exposure<=20:
                    issues.append({'object':name,'message':'light exposure must be finite and between -20 and 20'})
                for field in supported[style]:
                    value=light.get(field,1)
                    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not 0<value<=1000:
                        issues.append({'object':name,'message':f'light {field} must be positive and at most 1000 meters'})
        if 'counter' in obj or obj.get('kind')=='counter':
            counter=obj.get('counter')
            if obj.get('kind')!='counter' or not isinstance(counter,dict) or set(counter)-{'source','class_label','digits','color','scale'} or counter.get('source') not in ('spawned','verified_archives'):
                issues.append({'object':name,'message':'counter requires a supported measured source'})
            else:
                digits=counter.get('digits',3);label=counter.get('class_label');color=counter.get('color',[.05,1,.1]);scale=counter.get('scale',1)
                if type(digits) is not int or not 1<=digits<=6 or (label is not None and (not isinstance(label,str) or not label)) or not isinstance(color,list) or len(color)!=3 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<=1 for x in color) or not isinstance(scale,(int,float)) or isinstance(scale,bool) or not math.isfinite(scale) or not 0<scale<=100:
                    issues.append({'object':name,'message':'counter has invalid digits, class label, color or scale'})
        if 'indicator' in obj:
            indicator=obj['indicator'];robot=indicator.get('robot_id') if isinstance(indicator,dict) else None
            target=scene['objects'].get(robot,{}) if isinstance(robot,str) else {}
            if obj.get('kind')!='box' or obj.get('dynamic') or obj.get('collision') or not isinstance(indicator,dict) or set(indicator)!={'robot_id'} or not isinstance(target,dict) or not isinstance(target.get('pose_follower'),dict):
                issues.append({'object':name,'message':'indicator requires a non-colliding static box and a robot follower'})
        if 'camera' in obj or obj.get('kind')=='camera':
            from .capture import camera_config
            try:
                if obj.get('kind')!='camera': raise ValueError('camera settings require a camera')
                camera_config(scene,obj)
            except (ValueError,TypeError) as error: issues.append({'object':name,'message':str(error)})
        if 'support_surfaces' in obj:
            from .placement import validate_surfaces
            try: validate_surfaces(obj['support_surfaces'])
            except (ValueError,TypeError) as error: issues.append({'object':name,'message':str(error)})
        if 'record_fps' in obj and (obj.get('kind')!='camera' or type(obj['record_fps']) is not int or obj['record_fps'] not in (1,2,3,4,5,6,10,12,15,20,30)):
            issues.append({'object':name,'message':'record_fps must be a camera frame rate that divides 60, up to 30'})
        if 'preview_fps' in obj and (obj.get('kind')!='camera' or type(obj['preview_fps']) is not int or obj['preview_fps'] not in (1,2,3,4,5,6,10)):
            issues.append({'object':name,'message':'preview_fps must be a camera frame rate that divides 60, up to 10'})
        if 'camera_path' in obj:
            nodes=obj['camera_path']
            previous=-1
            if obj.get('kind')!='camera' or 'camera_orbit' in obj or not isinstance(nodes,list) or not 2<=len(nodes)<=200:
                issues.append({'object':name,'message':'camera_path requires 2..200 camera poses and excludes camera_orbit'})
            else:
                from .capture import finite
                for node in nodes:
                    if not isinstance(node,dict) or set(node)!={'time_s','position','target'} or not finite(node.get('time_s')) or not 0<=node.get('time_s',-1)<=1200 or not previous<node.get('time_s',-1) or not all(isinstance(node.get(k),list) and len(node[k])==3 and all(finite(v) for v in node[k]) for k in ('position','target')) or node.get('position')==node.get('target'):
                        issues.append({'object':name,'message':'camera_path nodes need increasing time_s and distinct finite position/target'})
                        break
                    previous=node['time_s']
        if 'camera_orbit' in obj:
            orbit=obj['camera_orbit']
            if obj.get('kind')!='camera' or not isinstance(orbit,dict) or set(orbit)-{'center','radius_m','height_m','duration_s','turns','start_angle_rad'}:
                issues.append({'object':name,'message':'camera_orbit requires a camera and supported orbit fields'})
            else:
                center=orbit.get('center');values=[orbit.get('radius_m'),orbit.get('height_m'),orbit.get('duration_s'),orbit.get('turns',1),orbit.get('start_angle_rad',0)]
                if not isinstance(center,list) or len(center)!=3 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in center) or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in values) or not 0<values[0]<=1000 or not 0<values[2]<=1200 or not 0<values[3]<=10:
                    issues.append({'object':name,'message':'camera_orbit requires finite center, positive radius, duration and turns'})
        if 'conveyor' in obj:
            c = obj['conveyor']
            d = c.get('direction') if isinstance(c, dict) else None
            speed = c.get('speed_m_s') if isinstance(c, dict) else None
            if obj.get('kind') != 'box' or obj.get('dynamic') or not obj.get('collision') or not isinstance(speed, (float, int)) or isinstance(speed, bool) or not math.isfinite(speed) or not isinstance(d, list) or len(d) != 3 or not all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in d) or abs(sum(x*x for x in d) - 1) > 1e-4:
                issues.append({'object':name, 'message':'invalid conveyor configuration'})
        if 'variants' in obj and (obj.get('kind') != 'asset' or not isinstance(obj['variants'],dict) or not all(isinstance(k,str) and isinstance(v,str) and k and v for k,v in obj['variants'].items())):
            issues.append({'object':name,'message':'variants must map USD variant set names to selections on an asset'})
        if 'pose_follower' in obj:
            c=obj['pose_follower']
            if not isinstance(c,dict) or obj.get('kind') != 'asset' or c.get('experimental') is not True:
                issues.append({'object':name,'message':'pose follower requires an asset and explicit experimental flag'})
            else:
                allowed_config={'experimental','model_directory','tool_frame','tcp_prim','initial_joints','target_position','tcp_offset','tcp_orientation_wxyz','max_joint_speed','monitor_collisions','self_collision_enabled','self_collision_exclusions','diagnose_overlaps','avoid_obstacles','obstacle_margin_m','arm_drives_enabled','suction_enabled','gripper_urdf','gripper_joint','gripper_mapping','gripper_physics','suction','sequence'}
                if set(c)-allowed_config:issues.append({'object':name,'message':f'unsupported pose follower fields: {sorted(set(c)-allowed_config)}'})
                target=c.get('target_position')
                if not isinstance(target,list) or len(target)!=3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in target):
                    issues.append({'object':name,'message':'pose follower target_position must contain three finite numbers'})
                for field in ('model_directory','tool_frame','tcp_prim'):
                    if not isinstance(c.get(field),str) or not c[field]: issues.append({'object':name,'message':f'pose follower {field} required'})
                if 'monitor_collisions' in c and not isinstance(c['monitor_collisions'],bool): issues.append({'object':name,'message':'monitor_collisions must be boolean'})
                if 'self_collision_enabled' in c and not isinstance(c['self_collision_enabled'],bool): issues.append({'object':name,'message':'self_collision_enabled must be boolean'})
                if 'self_collision_exclusions' in c:
                    from pathlib import PurePosixPath
                    pairs=c['self_collision_exclusions']
                    def valid_link(value):
                        if not isinstance(value,str) or not value or value.startswith('/') or '|' in value:return False
                        path=PurePosixPath(value)
                        return all(part not in ('','.','..') for part in value.split('/')) and bool(path.parts)
                    if c.get('self_collision_enabled') is not True or not isinstance(pairs,list) or len(pairs)>128 or any(not isinstance(pair,list) or len(pair)!=2 or not all(valid_link(v) for v in pair) or pair[0]==pair[1] for pair in pairs):
                        issues.append({'object':name,'message':'self_collision_exclusions require enabled self collisions and relative rigid-body pairs'})
                if 'diagnose_overlaps' in c and not isinstance(c['diagnose_overlaps'],bool): issues.append({'object':name,'message':'diagnose_overlaps must be boolean'})
                if 'avoid_obstacles' in c:
                    obstacles=c['avoid_obstacles']
                    valid=isinstance(obstacles,list) and len(obstacles)<=64 and all(isinstance(x,str) for x in obstacles)
                    if valid:
                        valid=len(obstacles)==len(set(obstacles)) and all(
                            x!=name and isinstance(scene['objects'].get(x),dict)
                            and scene['objects'][x].get('kind') in ('box','sphere')
                            and scene['objects'][x].get('collision') is True
                            and not scene['objects'][x].get('dynamic')
                            and not scene['objects'][x].get('spawn_step',0) for x in obstacles)
                    if not valid:issues.append({'object':name,'message':'avoid_obstacles must list distinct static collision-enabled box or sphere IDs'})
                if 'obstacle_margin_m' in c:
                    margin=c['obstacle_margin_m']
                    if not c.get('avoid_obstacles') or not isinstance(margin,(int,float)) or isinstance(margin,bool) or not math.isfinite(margin) or not 0<=margin<=.1:
                        issues.append({'object':name,'message':'obstacle_margin_m requires obstacles and a finite value between 0 and 0.1 m'})
                if 'arm_drives_enabled' in c and not isinstance(c['arm_drives_enabled'],bool): issues.append({'object':name,'message':'arm_drives_enabled must be boolean'})
                offset=c.get('tcp_offset',[0,0,0])
                if not isinstance(offset,list) or len(offset)!=3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in offset):
                    issues.append({'object':name,'message':'tcp_offset must contain three finite numbers'})
                if 'max_joint_speed' in c and (not isinstance(c['max_joint_speed'],(int,float)) or isinstance(c['max_joint_speed'],bool) or not math.isfinite(c['max_joint_speed']) or not 0<c['max_joint_speed']<=5): issues.append({'object':name,'message':'invalid max_joint_speed'})
                suction=c.get('suction')
                if 'suction_enabled' in c and (not isinstance(c['suction_enabled'],bool) or suction is None):
                    issues.append({'object':name,'message':'suction_enabled requires a suction configuration and a boolean'})
                if suction is not None:
                    if not isinstance(suction,dict) or not isinstance(suction.get('prim'),str) or not suction['prim'] or suction['prim'].startswith('/') or '..' in suction['prim'].split('/'):
                        issues.append({'object':name,'message':'suction prim must be a relative path'})
                    else:
                        if set(suction)-{'prim','max_grip_distance','force_limit'}:issues.append({'object':name,'message':'unsupported suction fields'})
                        for field,default in [('max_grip_distance',.02),('force_limit',100.)]:
                            value=suction.get(field,default)
                            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<=0: issues.append({'object':name,'message':f'invalid suction {field}'})
                mapping=c.get('gripper_mapping',{})
                if not isinstance(mapping,dict) or not all(isinstance(k,str) and isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for k,v in mapping.items()):
                    issues.append({'object':name,'message':'gripper_mapping must map joint names to finite multipliers'})
                if 'gripper_physics' in c:
                    from .gripper_physics import validate as validate_gripper_physics
                    issues.extend({'object':name,'message':message} for message in validate_gripper_physics(c['gripper_physics']))
                rotation=c.get('tcp_orientation_wxyz',[1,0,0,0])
                if not isinstance(rotation,list) or len(rotation)!=4 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in rotation) or abs(sum(v*v for v in rotation)-1)>1e-4:
                    issues.append({'object':name,'message':'tcp_orientation_wxyz must be a normalized quaternion'})
                sequence=c.get('sequence',[])
                if not isinstance(sequence,list):
                    issues.append({'object':name,'message':'sequence must be a list'})
                else:
                    for phase in sequence:
                        if not isinstance(phase,dict) or phase.get('type') not in ('move','gripper','track','wait_object'):
                            issues.append({'object':name,'message':'unsupported sequence phase'})
                            continue
                        allowed_phase={
                            'move':{'type','object','offset','position','min_steps','max_steps','tolerance_m','max_joint_speed','settle_steps','rmp_max_joint_speed','workspace_min','workspace_max'},
                            'track':{'type','object','offset','steps','gripper_value','required_object','max_tracking_error_m','workspace_min','workspace_max'},
                            'gripper':{'type','value','steps','required_object'},
                            'wait_object':{'type','object','axis','minimum','maximum','max_steps','workspace_min','workspace_max'}}[phase['type']]
                        if set(phase)-allowed_phase:issues.append({'object':name,'message':f'unsupported phase fields: {sorted(set(phase)-allowed_phase)}'})
                        if 'workspace_min' in phase or 'workspace_max' in phase:
                            lo,hi=phase.get('workspace_min'),phase.get('workspace_max')
                            valid=all(isinstance(v,list) and len(v)==3 and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in v) for v in (lo,hi))
                            if not valid or any(a>=b for a,b in zip(lo,hi)):
                                issues.append({'object':name,'message':'workspace bounds require finite ordered three-vectors'})
                            if phase['type']=='move' and 'object' not in phase:
                                issues.append({'object':name,'message':'workspace bounds on move require an object target'})
                        if 'rmp_max_joint_speed' in phase:
                            speed=phase['rmp_max_joint_speed']
                            if 'max_joint_speed' not in c or not isinstance(speed,(int,float)) or isinstance(speed,bool) or not math.isfinite(speed) or not 0<speed<=5:
                                issues.append({'object':name,'message':'phase rmp_max_joint_speed requires a global max_joint_speed and a finite value in (0, 5]'})
                        if phase['type']=='move':
                            p=phase.get('position') if 'object' not in phase else phase.get('offset')
                            if not isinstance(p,list) or len(p)!=3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in p):
                                issues.append({'object':name,'message':'move position or object offset must contain three finite numbers'})
                            if 'object' in phase and (not isinstance(phase['object'],str) or phase['object'] not in scene['objects'] or not isinstance(scene['objects'][phase['object']],dict) or not scene['objects'][phase['object']].get('dynamic')):
                                issues.append({'object':name,'message':'move object must be an existing dynamic object'})
                            for field in ('min_steps','max_steps','settle_steps'):
                                if field in phase and (not isinstance(phase[field],int) or isinstance(phase[field],bool) or not 1<=phase[field]<=36000): issues.append({'object':name,'message':f'invalid {field}'})
                            speed=phase.get('max_joint_speed',1.0)
                            if not isinstance(speed,(int,float)) or isinstance(speed,bool) or not math.isfinite(speed) or not 0<speed<=5: issues.append({'object':name,'message':'invalid phase max_joint_speed'})
                            tolerance=phase.get('tolerance_m',.02)
                            if not isinstance(tolerance,(int,float)) or isinstance(tolerance,bool) or not math.isfinite(tolerance) or not 0<tolerance<=.1: issues.append({'object':name,'message':'invalid move tolerance'})
                            if phase.get('min_steps',30)>phase.get('max_steps',300): issues.append({'object':name,'message':'min_steps exceeds max_steps'})
                        elif phase['type']=='wait_object':
                            target_id=phase.get('object')
                            if not isinstance(target_id,str) or target_id not in scene['objects'] or not isinstance(scene['objects'][target_id],dict) or not scene['objects'][target_id].get('dynamic'):
                                issues.append({'object':name,'message':'wait_object requires an existing dynamic object'})
                            if phase.get('axis') not in ('x','y','z'): issues.append({'object':name,'message':'wait_object axis must be x, y or z'})
                            lo,hi=phase.get('minimum'),phase.get('maximum')
                            if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (lo,hi)) or lo>hi:
                                issues.append({'object':name,'message':'wait_object requires a finite ordered interval'})
                            max_steps=phase.get('max_steps')
                            if not isinstance(max_steps,int) or isinstance(max_steps,bool) or not 1<=max_steps<=360000: issues.append({'object':name,'message':'invalid wait timeout'})
                        elif phase['type']=='track':
                            target_id=phase.get('object'); offset=phase.get('offset'); steps=phase.get('steps')
                            if not isinstance(target_id,str) or target_id not in scene['objects'] or not isinstance(scene['objects'][target_id],dict) or not scene['objects'][target_id].get('dynamic'):
                                issues.append({'object':name,'message':'track requires an existing dynamic object'})
                            if not isinstance(offset,list) or len(offset)!=3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in offset):
                                issues.append({'object':name,'message':'track offset must contain three finite numbers'})
                            if not isinstance(steps,int) or isinstance(steps,bool) or not 1<=steps<=36000: issues.append({'object':name,'message':'invalid track steps'})
                            error=phase.get('max_tracking_error_m',.03)
                            if not isinstance(error,(int,float)) or isinstance(error,bool) or not math.isfinite(error) or not 0<error<=.1: issues.append({'object':name,'message':'invalid tracking error limit'})
                            if 'required_object' in phase and phase['required_object'] != target_id:
                                issues.append({'object':name,'message':'track required_object must match tracked object'})
                            if 'gripper_value' in phase:
                                value=phase['gripper_value']
                                if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or (not c.get('suction') and (not c.get('gripper_urdf') or not c.get('gripper_joint'))):
                                    issues.append({'object':name,'message':'invalid track gripper configuration'})
                        else:
                            v=phase.get('value');steps=phase.get('steps')
                            if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or not isinstance(steps,int) or isinstance(steps,bool) or not 1<=steps<=36000:
                                issues.append({'object':name,'message':'invalid gripper phase'})
                            if not c.get('suction') and (not c.get('gripper_urdf') or not c.get('gripper_joint')):
                                issues.append({'object':name,'message':'gripper_urdf and gripper_joint required'})
                            if 'required_object' in phase:
                                target_id=phase['required_object']
                                if not isinstance(target_id,str) or target_id not in scene['objects'] or not isinstance(scene['objects'][target_id],dict) or not scene['objects'][target_id].get('dynamic'):
                                    issues.append({'object':name,'message':'required_object must identify a dynamic object'})
                joints=c.get('initial_joints',{})
                if not isinstance(joints,dict) or not all(isinstance(k,str) and isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for k,v in joints.items()):
                    issues.append({'object':name,'message':'initial_joints must map names to finite numbers'})
        if 'spawn_step' in obj and (not isinstance(obj['spawn_step'],int) or isinstance(obj['spawn_step'],bool) or not 0<=obj['spawn_step']<=360000 or obj.get('kind') not in ('box','sphere') or not obj.get('dynamic')):
            issues.append({'object':name,'message':'spawn_step requires a dynamic primitive and a nonnegative integer step'})
        if 'mass_kg' in obj and (not obj.get('dynamic') or not isinstance(obj['mass_kg'],(int,float)) or isinstance(obj['mass_kg'],bool) or not math.isfinite(obj['mass_kg']) or obj['mass_kg']<=0):
            issues.append({'object':name,'message':'mass_kg requires a dynamic object and a positive finite mass'})
        if 'class_label' in obj and (not isinstance(obj['class_label'],str) or not obj['class_label']): issues.append({'object':name,'message':'class_label must be nonempty text'})
        position = obj.get('position', [0, 0, 0])
        if not isinstance(position, list) or len(position) != 3 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in position):
            issues.append({'object': name, 'message': 'position must be three finite numbers'})
        kind = obj.get('kind')
        if kind not in ('box', 'sphere', 'asset', 'camera', 'light','counter'):
            issues.append({'object': name, 'message': f'unsupported kind: {kind}'})
        if kind == 'asset' and not obj.get('asset_path'):
            issues.append({'object': name, 'message': 'asset_path required'})
        elif kind == 'asset' and (not isinstance(obj['asset_path'],str) or '://' in obj['asset_path']):
            issues.append({'object':name,'message':'asset_path must be a local simulation-host path; acquire the online asset and use its returned path'})
        if kind in ('box', 'sphere'):
            size = obj.get('size', [1, 1, 1])
            if not isinstance(size, list) or len(size) != 3 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0 for x in size):
                issues.append({'object': name, 'message': 'size must contain three positive finite numbers'})
    return issues

class SceneStore:
    def __init__(self, directory=None):
        from .settings import get
        self.path = Path(directory or get('data_directory','~/.local/share/simscene')).expanduser()
        self.path.mkdir(parents=True, exist_ok=True)

    def _path(self, scene_id):
        return self.path / (_id(scene_id) + '.json')

    def _write(self, path, data):
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=self.path, delete=False) as f:
            name = f.name
            try:
                json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
                os.replace(name, path)
            finally:
                if os.path.exists(name): os.unlink(name)

    def open(self, scene_id):
        import fcntl
        path = self._path(scene_id)
        with (self.path / (scene_id + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists(): return self.get(scene_id)
            scene = {'schema_version':'0.1', 'scene_id':scene_id, 'revision':0, 'world':{'units':'m', 'up_axis':'Z'}, 'objects':{}, 'requests':{}}
            self._write(path, scene)
            return scene

    def get(self, scene_id):
        try:
            return json.loads(self._path(scene_id).read_text())
        except FileNotFoundError as e:
            raise SceneError('scene not found') from e

    def apply(self, scene_id, base_revision, request_id, operations):
        # Lock the whole read/compare/write transaction across local processes.
        import fcntl
        _id(scene_id)
        _id(request_id)
        with (self.path / (scene_id + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            scene = self.get(scene_id)
            payload = hashlib.sha256(json.dumps({'base_revision':base_revision, 'operations':operations}, sort_keys=True, allow_nan=False).encode()).hexdigest()
            prior = scene['requests'].get(request_id)
            if prior:
                if prior['hash'] != payload: raise SceneError('request ID reused with different payload')
                return {'revision':prior['revision'], 'replayed':True}
            if scene['revision'] != base_revision: raise SceneError(f"revision conflict: current {scene['revision']}")
            updated = copy.deepcopy(scene)
            for op in operations:
                action = op.get('op')
                if action == 'set_presentation':
                    from .capture import validate_presentation
                    try: updated['presentation']=copy.deepcopy(validate_presentation(op.get('presentation')))
                    except ValueError as error: raise SceneError(str(error)) from error
                    continue
                if action in ('arrange_grid','align'):
                    from .placement import apply_layout
                    apply_layout(updated,op)
                    continue
                if action == 'arrange_line':
                    if any(updated['objects'].get(i,{}).get('kind')=='asset' or updated['objects'].get(i,{}).get('orientation_wxyz',[1,0,0,0])!=[1,0,0,0] for i in op.get('ids',[])):
                        from .placement import arrange_line
                        arrange_line(updated,op)
                        continue
                    ids, origin, spacing, axis = op.get('ids'), op.get('origin'), op.get('spacing'), op.get('axis', 'x')
                    if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
                        raise SceneError('arrange_line requires distinct object IDs')
                    if not isinstance(origin, list) or len(origin) != 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in origin):
                        raise SceneError('origin must be three finite numbers')
                    if axis not in ('x', 'y', 'z') or not isinstance(spacing, (int,float)) or isinstance(spacing, bool) or not math.isfinite(spacing) or spacing <= 0:
                        raise SceneError('axis and positive spacing required')
                    dim = ('x', 'y', 'z').index(axis)
                    objects = []
                    for item_id in ids:
                        _id(item_id)
                        obj = updated['objects'].get(item_id)
                        if not obj or obj.get('kind') not in ('box','sphere') or obj.get('orientation_wxyz', [1,0,0,0]) != [1,0,0,0]:
                            raise SceneError('arrange_line requires unrotated primitive objects')
                        objects.append(obj)
                    for left, right in zip(objects, objects[1:]):
                        if spacing < (left.get('size',[1,1,1])[dim] + right.get('size',[1,1,1])[dim]) / 2:
                            raise SceneError('line spacing would overlap objects')
                    for i, obj in enumerate(objects):
                        position = list(origin)
                        position[dim] += i * spacing
                        obj['position'] = position
                    continue
                name = _id(op.get('id'))
                if action == 'add':
                    if name in updated['objects']: raise SceneError(f'object already exists: {name}')
                    if not isinstance(op.get('object'), dict): raise SceneError('object must be a mapping')
                    updated['objects'][name] = op['object']
                elif action == 'update':
                    if name not in updated['objects']: raise SceneError(f'object not found: {name}')
                    if not isinstance(op.get('changes'), dict): raise SceneError('changes must be a mapping')
                    updated['objects'][name].update(op['changes'])
                elif action == 'look_at':
                    from .geometry import camera_orientation
                    camera = updated['objects'].get(name)
                    if not camera or camera.get('kind') != 'camera': raise SceneError('look_at requires a camera')
                    if 'target_id' in op:
                        target = updated['objects'].get(_id(op['target_id']))
                        if target is None: raise SceneError('look_at target not found')
                        point = target.get('position', [0, 0, 0])
                    else:
                        point = op.get('target')
                    if not isinstance(point, list) or len(point) != 3 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in point):
                        raise SceneError('look_at target must be three finite numbers')
                    camera['orientation_wxyz'] = camera_orientation(camera.get('position', [0,0,0]), point)
                elif action == 'bind_conveyor':
                    if name not in updated['objects']: raise SceneError(f'object not found: {name}')
                    obj = updated['objects'][name]
                    speed, direction = op.get('speed_m_s'), op.get('direction', [1, 0, 0])
                    if obj.get('kind') != 'box' or obj.get('dynamic'):
                        raise SceneError('conveyor requires a static box collision surface')
                    if not isinstance(speed, (float, int)) or isinstance(speed, bool) or not math.isfinite(speed):
                        raise SceneError('bind_conveyor requires finite speed_m_s, e.g. {"op":"bind_conveyor","id":"belt","speed_m_s":0.1,"direction":[1,0,0]}')
                    if not isinstance(direction, list) or len(direction) != 3 or not all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in direction) or sum(x*x for x in direction) < 1e-12:
                        raise SceneError('conveyor direction must be a nonzero finite vector')
                    obj['collision'] = True
                    length = math.sqrt(sum(x*x for x in direction))
                    obj['conveyor'] = {'speed_m_s':speed, 'direction':[x / length for x in direction]}
                elif action == 'remove':
                    if name not in updated['objects']: raise SceneError(f'object not found: {name}')
                    del updated['objects'][name]
                elif action == 'place_on':
                    from .placement import place_on
                    place_on(updated,op)
                else: raise SceneError(f'unsupported operation: {action}')
            issues = validate(updated)
            if issues: raise SceneError(json.dumps(issues))
            updated['revision'] += 1
            updated['requests'][request_id] = {'hash':payload, 'revision':updated['revision']}
            self._write(self._path(scene_id), updated)
            return {'revision':updated['revision'], 'replayed':False}
