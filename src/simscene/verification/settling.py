"""Estimate object speed from recorded positions and orientations."""
import math

def stable(samples,part,simulation_time,duration_s,max_linear_m_s,max_angular_rad_s):
    frames=[s for s in samples if simulation_time-duration_s<=s.get('simulation_time_s',-1)<=simulation_time+1e-9]
    if len(frames)<2 or frames[-1]['simulation_time_s']-frames[0]['simulation_time_s']<duration_s-.1:return False
    if any(part not in s.get('positions',{}) or part not in s.get('orientations_wxyz',{}) for s in frames):return False
    def numbers(v,n):return isinstance(v,list) and len(v)==n and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in v)
    for a,b in zip(frames,frames[1:]):
        dt=b['simulation_time_s']-a['simulation_time_s']
        p0,p1=a['positions'][part],b['positions'][part];q0,q1=a['orientations_wxyz'][part],b['orientations_wxyz'][part]
        if not 0<dt<=.2 or not all([numbers(p0,3),numbers(p1,3),numbers(q0,4),numbers(q1,4)]):return False
        n0=math.sqrt(sum(x*x for x in q0));n1=math.sqrt(sum(x*x for x in q1))
        if abs(n0-1)>.01 or abs(n1-1)>.01:return False
        linear=math.dist(p0,p1)/dt
        cosine=min(1.,max(0.,abs(sum(x*y for x,y in zip(q0,q1))/(n0*n1))))
        angular=2*math.acos(cosine)/dt
        if linear>max_linear_m_s or angular>max_angular_rad_s:return False
    return True
