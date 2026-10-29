"""Numerical URDF IK candidate search. Collision checking is separate."""
import math
import xml.etree.ElementTree as ET
from .urdf import link_transform

def solve_ik(urdf_path, base_link, tool_link, joint_names, target_position, target_orientation_wxyz=None, seed=None, position_tolerance=.005, orientation_tolerance=.05):
    try:
        import numpy as np
        from scipy.optimize import least_squares
        from scipy.spatial.transform import Rotation
    except ImportError as error: raise RuntimeError('IK requires numpy and scipy') from error
    if not joint_names or len(set(joint_names))!=len(joint_names): raise ValueError('unique joint names required')
    target=np.asarray(target_position,dtype=float)
    if target.shape!=(3,) or not np.all(np.isfinite(target)): raise ValueError('invalid target position')
    wanted=None
    if target_orientation_wxyz is not None:
        q=np.asarray(target_orientation_wxyz,dtype=float)
        if q.shape!=(4,) or not np.all(np.isfinite(q)) or abs(np.linalg.norm(q)-1)>1e-4: raise ValueError('invalid target quaternion')
        wanted=Rotation.from_quat([q[1],q[2],q[3],q[0]])
    root=ET.parse(urdf_path).getroot(); joints={j.get('name'):j for j in root.findall('joint')}
    by_child={j.find('child').get('link'):j for j in joints.values() if j.find('child') is not None}
    chain=[];link=tool_link;seen=set()
    while link!=base_link:
        if link in seen or link not in by_child: raise ValueError('tool is not a descendant of base')
        seen.add(link);joint=by_child[link];chain.append(joint);link=joint.find('parent').get('link')
    movable={j.get('name') for j in chain if j.get('type')!='fixed'}
    if movable != set(joint_names): raise ValueError('joint_names must exactly cover movable joints on the base-to-tool chain')
    if any(j.find('mimic') is not None for j in chain): raise ValueError('IK through mimic joints is not yet supported')
    lower=[];upper=[]
    for name in joint_names:
        joint=joints.get(name)
        if joint is None or joint.get('type') not in ('revolute','continuous','prismatic'): raise ValueError('joint not controllable: '+name)
        limit=joint.find('limit')
        if joint.get('type')=='continuous': lo,hi=-math.pi,math.pi
        elif limit is None or limit.get('lower') is None or limit.get('upper') is None: raise ValueError('joint limits missing: '+name)
        else: lo,hi=float(limit.get('lower')),float(limit.get('upper'))
        if not math.isfinite(lo) or not math.isfinite(hi) or lo>=hi: raise ValueError('invalid joint limits: '+name)
        lower.append(lo);upper.append(hi)
    initial=np.asarray(seed if seed is not None else [(x+y)/2 for x,y in zip(lower,upper)],dtype=float)
    if initial.shape!=(len(joint_names),) or not np.all(np.isfinite(initial)): raise ValueError('invalid seed')
    initial=np.clip(initial,lower,upper)
    def residual(q):
        matrix=np.asarray(link_transform(urdf_path,base_link,tool_link,dict(zip(joint_names,q))))
        pos=matrix[:3,3]-target
        return np.r_[pos,(wanted.inv()*Rotation.from_matrix(matrix[:3,:3])).as_rotvec()] if wanted is not None else pos
    solution=least_squares(residual,initial,bounds=(lower,upper),max_nfev=500)
    error=residual(solution.x)
    position_error=float(np.linalg.norm(error[:3]));orientation_error=float(np.linalg.norm(error[3:])) if wanted is not None else None
    success=position_error<=position_tolerance and (orientation_error is None or orientation_error<=orientation_tolerance)
    return {'success':success,'joint_positions':dict(zip(joint_names,solution.x.tolist())), 'position_error_m':position_error,
            'orientation_error_rad':orientation_error,'collision_check':'not performed','note':'Numerical candidate only; verify against simulator and collision constraints.'}
