"""Evaluate URDF link transforms for forward-kinematics diagnostics."""
import math
import xml.etree.ElementTree as ET

def _matmul(a,b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def _identity():
    return [[float(i==j) for j in range(4)] for i in range(4)]

def _numbers(text, default):
    values = [float(x) for x in text.split()] if text else default
    if len(values) != 3 or not all(math.isfinite(v) for v in values): raise ValueError('invalid xyz/rpy')
    return values

def _origin(element):
    xyz = _numbers(element.get('xyz') if element is not None else None, [0,0,0])
    r,p,y = _numbers(element.get('rpy') if element is not None else None, [0,0,0])
    cr,sr,cp,sp,cy,sy=math.cos(r),math.sin(r),math.cos(p),math.sin(p),math.cos(y),math.sin(y)
    return [[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr,xyz[0]],
            [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr,xyz[1]],
            [-sp,cp*sr,cp*cr,xyz[2]],[0,0,0,1]]

def _motion(joint, position):
    kind = joint.get('type')
    if kind == 'fixed': return _identity()
    if kind not in ('revolute','continuous','prismatic'): raise ValueError('unsupported joint type: '+str(kind))
    axis_element=joint.find('axis')
    axis=_numbers(axis_element.get('xyz') if axis_element is not None else None, [1,0,0])
    length=math.sqrt(sum(v*v for v in axis))
    if length < 1e-12: raise ValueError('zero joint axis')
    x,y,z=[v/length for v in axis]
    if kind == 'prismatic':
        m=_identity(); m[0][3],m[1][3],m[2][3]=x*position,y*position,z*position; return m
    c,s=math.cos(position),math.sin(position); d=1-c
    return [[c+x*x*d,x*y*d-z*s,x*z*d+y*s,0],
            [y*x*d+z*s,c+y*y*d,y*z*d-x*s,0],
            [z*x*d-y*s,z*y*d+x*s,c+z*z*d,0],[0,0,0,1]]

def link_transform(urdf_path, base_link, target_link, joint_positions=None):
    """Return base-to-target transform; default positions are zero radians/metres."""
    positions=joint_positions or {}
    root=ET.parse(urdf_path).getroot()
    by_child={}
    for joint in root.findall('joint'):
        parent,child=joint.find('parent'),joint.find('child')
        if parent is None or child is None: raise ValueError('joint without parent/child')
        child_name=child.get('link')
        if child_name in by_child: raise ValueError('multiple parent joints')
        by_child[child_name]=joint
    chain=[]; link=target_link; visited=set()
    while link != base_link:
        if link in visited or link not in by_child: raise ValueError('target is not a descendant of base')
        visited.add(link); joint=by_child[link]; chain.append(joint); link=joint.find('parent').get('link')
    result=_identity()
    for joint in reversed(chain):
        position=float(positions.get(joint.get('name'), 0))
        if not math.isfinite(position): raise ValueError('nonfinite joint position')
        result=_matmul(result,_matmul(_origin(joint.find('origin')),_motion(joint,position)))
    return result
