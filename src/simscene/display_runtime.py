"""Update displays from run data; never infer unverified task success."""
from .activity import state,COLORS
from .display import set_value,set_overflow


def update(stage,spec,followers,spawn_events,archived,archive_enabled,last):
    from pxr import Gf,UsdGeom,UsdShade
    observations={}
    initial=[obj.get('class_label') for obj in spec['objects'].values() if obj.get('dynamic') and not obj.get('spawn_step',0)]
    spawned=initial+[event.get('class_label') for event in spawn_events]
    for name,obj in spec['objects'].items():
        path='/World/'+name.replace('-','_')
        if obj.get('kind')=='counter':
            config=obj['counter'];source=config['source'];label=config.get('class_label')
            available=source!='verified_archives' or archive_enabled
            classes=spawned if source=='spawned' else [event.get('class_label') for event in archived.values()]
            value=sum(1 for entry in classes if label is None or entry==label) if available else None
            digits=config.get('digits',3);overflow=value is not None and value>=10**digits
            current=('counter',value,overflow)
            if last.get(name)!=current:
                prim=stage.GetPrimAtPath(path)
                if not prim:raise RuntimeError('counter prim is missing: '+name)
                image=UsdGeom.Imageable(prim)
                if not available:image.MakeInvisible()
                else:
                    image.MakeVisible()
                    if overflow:set_overflow(stage,path,digits)
                    else:set_value(stage,path,digits,value)
                last[name]=current
            observations[name]={'source':source,'class_label':label,'value':value,'overflow':overflow,'available':available}
        elif 'indicator' in obj:
            robot=obj['indicator']['robot_id'];follower=followers[robot]
            status=state(follower.sequence,follower.sequence_index,follower.sequence_error)
            current=('indicator',status)
            if last.get(name)!=current:
                shader=UsdShade.Shader(stage.GetPrimAtPath('/World/Looks/'+name.replace('-','_')+'/PreviewSurface'))
                if not shader:raise RuntimeError('indicator material is missing: '+name)
                color=Gf.Vec3f(*COLORS[status]);shader.GetInput('diffuseColor').Set(color);shader.GetInput('emissiveColor').Set(color)
                last[name]=current
            observations[name]={'robot_id':robot,'controller_phase_state':status}
    return observations
