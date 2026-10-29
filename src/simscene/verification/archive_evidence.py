"""Validate a terminal observation before an archived primitive was removed."""
import math

def matches_observation(run,part_id,obj,event,tolerance=.003):
    if not isinstance(event,dict) or event.get('terminal_state')!='correct' or event.get('part_id')!=part_id or event.get('class_label')!=obj.get('class_label'):return False
    step=event.get('physics_step');time=event.get('simulation_time_s');position=event.get('position');bounds=event.get('bounds')
    if type(step) is not int or step<0 or not isinstance(time,(int,float)) or not math.isfinite(time):return False
    frames=[s for s in run.get('samples',[]) if s.get('physics_steps')==step and abs(s.get('simulation_time_s',-1)-time)<1e-6]
    if len(frames)!=1:return False
    frame=frames[0];path='/World/'+part_id.replace('-','_')
    actual=frame.get('positions',{}).get(path);q=frame.get('orientations_wxyz',{}).get(path);size=obj.get('size')
    def vector(value,n):return isinstance(value,list) and len(value)==n and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in value)
    if not all((vector(position,3),vector(actual,3),vector(q,4),vector(size,3))):return False
    if math.dist(position,actual)>1e-5 or abs(sum(x*x for x in q)-1)>.02:return False
    if not isinstance(bounds,dict) or not vector(bounds.get('min'),3) or not vector(bounds.get('max'),3):return False
    kind=obj.get('kind');w,x,y,z=q
    if kind=='box':
        matrix=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
        extents=[sum(abs(matrix[i][j])*size[j]/2 for j in range(3)) for i in range(3)]
    elif kind=='sphere' and size[0]==size[1]==size[2]:extents=[size[0]/2]*3
    else:return False
    return all(abs(bounds['min'][i]-(actual[i]-extents[i]))<=tolerance and abs(bounds['max'][i]-(actual[i]+extents[i]))<=tolerance for i in range(3))
