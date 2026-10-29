"""Check a frozen case against discrete PhysX shape and contact evidence.

This is an audit of sampled simulation steps, not a continuous swept-volume
or physical-robot safety certification. Any missing coverage fails closed.
"""
import math
def evaluate(run, spec, case, stage_path):
    from pxr import Usd,UsdPhysics
    stage=Usd.Stage.Open(str(stage_path))
    if not stage:raise ValueError('cannot open frozen run stage')
    items={item['part_path']:item for item in case['objects']}
    robots={item['robot_id'] for item in case['objects']}
    prefixes={robot:'/World/'+robot.replace('-','_')+'/Asset' for robot in robots}
    policy=case.get('collision_policy') or {}
    if not isinstance(policy,dict):raise ValueError('collision policy must be a mapping')
    permitted=policy.get('mechanical_pairs') or {}
    contact_exceptions=policy.get('allowed_mechanical_contacts') or {}
    grasp=policy.get('grasp_bodies') or {}
    if not all(isinstance(value,dict) for value in (permitted,contact_exceptions,grasp)):
        raise ValueError('collision policy entries must be mappings')
    valid_policy=set(permitted)==robots and set(grasp)==robots and set(contact_exceptions)==robots
    allowed=set()
    for robot in robots:
        pairs=permitted.get(robot);bodies=grasp.get(robot)
        if not isinstance(pairs,list) or not isinstance(bodies,list) or not bodies:
            valid_policy=False;continue
        extra=contact_exceptions.get(robot)
        if not isinstance(extra,list):valid_policy=False;continue
        for pair in pairs+extra:
            if not isinstance(pair,list) or len(pair)!=2 or not all(isinstance(x,str) and x and '/' not in x for x in pair) or pair[0]==pair[1]:
                valid_policy=False;continue
            allowed.add(frozenset(prefixes[robot]+'/'+x for x in pair))
        if not all(isinstance(body,str) and body and '/' not in body for body in bodies):valid_policy=False
        configured=spec['objects'][robot]['pose_follower'].get('self_collision_exclusions',[])
        if {tuple(sorted(x)) for x in configured}!={tuple(sorted(x)) for x in pairs}:valid_policy=False
    # Directly joint-linked bodies are designed as one mechanism; a joint that
    # explicitly enables collision is not automatically permitted.
    for prim in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdPhysics.Joint):continue
        joint=UsdPhysics.Joint(prim);a=joint.GetBody0Rel().GetTargets();b=joint.GetBody1Rel().GetTargets()
        if len(a)!=1 or len(b)!=1 or joint.GetCollisionEnabledAttr().Get() is True:continue
        a,b=str(a[0]),str(b[0])
        if any(a.startswith(prefix+'/') and b.startswith(prefix+'/') for prefix in prefixes.values()):allowed.add(frozenset((a,b)))
    expected_bodies={}
    for prim in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
        path=str(prim.GetPath())
        if not path.startswith('/World/') or not prim.HasAPI(UsdPhysics.CollisionAPI):continue
        body=prim
        while body and not body.HasAPI(UsdPhysics.RigidBodyAPI):body=body.GetParent()
        expected_bodies[path]=str(body.GetPath()) if body else path
    events={e['id']:e for e in run.get('spawn_events',[]) if isinstance(e,dict) and 'id' in e}
    for name,obj in spec['objects'].items():
        if obj.get('dynamic') and obj.get('spawn_step',0)>0:
            path='/World/'+name.replace('-','_');expected_bodies[path]=path
    expected_shapes=set(expected_bodies)
    diagnostic=run.get('overlap_diagnostics') or {};shapes=diagnostic.get('shapes') or []
    shape_body={s.get('path'):s.get('body') for s in shapes if isinstance(s,dict)}
    samples=diagnostic.get('shape_samples') or {};steps=run.get('actual_physics_steps',-1)
    coverage=shape_body==expected_bodies and len(shape_body)==len(shapes) and set(samples)==expected_shapes
    for path in expected_shapes:
        name=path.removeprefix('/World/')
        if name in events and path=='/World/'+name:
            archive=run.get('archived_objects',{}).get(name)
            end=archive.get('physics_step') if isinstance(archive,dict) else steps
            count=end-events[name].get('physics_step',end) if isinstance(end,int) else -1
        else:count=steps+1
        if samples.get(path)!=count:coverage=False
    settings=run.get('self_collision_settings') or {}
    enabled=all(settings.get(robot,{}).get('authored') is True and settings.get(robot,{}).get('runtime') is True and
                spec['objects'][robot]['pose_follower'].get('diagnose_overlaps') is True for robot in robots)
    excluded={frozenset(pair) for robot in robots for pair in settings.get(robot,{}).get('excluded_body_pairs',[]) if isinstance(pair,list) and len(pair)==2}
    expected_excluded={frozenset(prefixes[robot]+'/'+x for x in pair) for robot in robots for pair in permitted.get(robot,[]) if isinstance(pair,list) and len(pair)==2}
    enabled=enabled and excluded==expected_excluded
    def owner(path):
        if not isinstance(path,str):return None
        return next((robot for robot,prefix in prefixes.items() if path==prefix or path.startswith(prefix+'/')),None)
    def permitted_pair(a,b,first,last):
        ra,rb=owner(a),owner(b)
        if not ra and not rb:return True
        if ra and rb:return ra==rb and (a==b or frozenset((a,b)) in allowed)
        robot,body,other=(ra,a,b) if ra else (rb,b,a)
        item=items.get(other)
        if not item or item['robot_id']!=robot or body not in {prefixes[robot]+'/'+x for x in grasp.get(robot,[])}:return False
        transitions={t['index']:t['physics_step'] for t in run.get('followers',{}).get(robot,{}).get('transitions',[])}
        start=transitions.get(item['tracking_phase']);end=transitions.get(item['release_phase']+2)
        return isinstance(start,int) and isinstance(end,int) and start<=first<=last<=end
    unexpected=[]
    for key,value in (run.get('overlap_counts') or {}).items():
        pair=key.split('|')
        if len(pair)!=2 or not all(p in shape_body for p in pair) or not isinstance(value,dict):
            unexpected.append({'source':'overlap','pair':key,'reason':'invalid shape evidence'});continue
        first,last=value.get('first_physics_step'),value.get('last_physics_step')
        if type(first) is not int or type(last) is not int or not 0<=first<=last<=steps or not permitted_pair(shape_body[pair[0]],shape_body[pair[1]],first,last):
            unexpected.append({'source':'overlap','pair':key,'first':first,'last':last})
    proximity_only=0;missing_separation=0
    for key,value in (run.get('robot_contacts') or {}).items():
        pair=key.split('|')
        if len(pair)<3 or not isinstance(value,dict):unexpected.append({'source':'contact','pair':key,'reason':'invalid contact evidence'});continue
        first,last=value.get('first_physics_step'),value.get('last_physics_step')
        if type(first) is not int or type(last) is not int or not 0<=first<=last<=steps:
            unexpected.append({'source':'contact','pair':key,'reason':'invalid contact timing'});continue
        separation=value.get('minimum_separation_m')
        if not isinstance(separation,(int,float)) or isinstance(separation,bool) or not math.isfinite(separation):
            missing_separation+=1
        elif separation>0:
            proximity_only+=1
            continue
        if not permitted_pair(pair[0],pair[1],first,last):
            unexpected.append({'source':'contact','pair':key,'first':first,'last':last})
    checks={'case_policy_matches_scene':valid_policy,'self_collision_enabled':enabled,
            'collision_shapes_covered':coverage,'each_step_queried':diagnostic.get('sampled_steps')==steps+1 and diagnostic.get('last_physics_step')==steps and diagnostic.get('step_gaps')==0,
            'queries_complete':diagnostic.get('error_count')==0 and diagnostic.get('missing_self_hits')=={} and diagnostic.get('truncated') is False,
            'contact_reporting_complete':run.get('contacts_truncated') is False and run.get('contact_geometry_incomplete') is False and missing_separation==0 and all(robot in run.get('monitored_robot_ids',[]) for robot in robots),
            'no_unexpected_overlaps_or_contacts':not unexpected}
    return {'passed':all(checks.values()),'checks':checks,'unexpected':unexpected,
            'shape_count':len(shape_body),'overlap_pairs':len(run.get('overlap_counts') or {}),'positive_separation_contact_records':proximity_only,
            'scope':'Discrete per-physics-step PhysX queries with convex-hull mesh approximations plus reported zero-or-negative-separation contacts. Positive-separation contact records are counted separately. Approved mechanical pairs and assigned grasp contacts are excluded. No swept-volume, unmodelled-geometry or physical-robot safety claim.'}
