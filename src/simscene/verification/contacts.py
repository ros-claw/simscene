"""Select recorded robot/environment contacts without conflating arms."""
def forbidden_robot_environment(contacts,robot,paths,phase_range=None):
    found=[];prefix='/World/'+robot+'/Asset'
    for key,value in (contacts or {}).items():
        if value.get('count',0)<=0:continue
        actors=key.split('|')[:2]
        if not any(actor==prefix or actor.startswith(prefix+'/') for actor in actors):continue
        if not any(path in actor for actor in actors for path in paths):continue
        if phase_range is not None:
            phases=key.rsplit('|',1)[-1].split(',');matching=[p[len(robot)+1:] for p in phases if p.startswith(robot+':')]
            if len(matching)==1:
                try:
                    phase=int(matching[0])
                    if not phase_range[0]<=phase<=phase_range[1]:continue
                except ValueError:pass
        found.append(key)
    return found
