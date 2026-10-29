"""Translate URDF mimic relationships into explicit drive commands."""
import math
import xml.etree.ElementTree as ET

def mimic_commands(urdf_path, source_joint, value):
    value=float(value)
    if not math.isfinite(value): raise ValueError('joint value must be finite')
    joints={j.get('name'):j for j in ET.parse(urdf_path).getroot().findall('joint')}
    if source_joint not in joints: raise ValueError('source joint not found')
    if joints[source_joint].find('mimic') is not None: raise ValueError('source joint is itself a mimic')
    values={source_joint:value}
    pending={name:j.find('mimic') for name,j in joints.items() if j.find('mimic') is not None}
    for _ in range(len(pending)+1):
        progressed=False
        for name,mimic in list(pending.items()):
            if mimic.get('joint') in values:
                mult=float(mimic.get('multiplier','1')); offset=float(mimic.get('offset','0'))
                if not math.isfinite(mult) or not math.isfinite(offset): raise ValueError('nonfinite mimic rule')
                values[name]=values[mimic.get('joint')]*mult+offset
                del pending[name]; progressed=True
        if not progressed: break
    for name,command in values.items():
        limit=joints[name].find('limit')
        if limit is not None:
            lower=float(limit.get('lower','-inf'));upper=float(limit.get('upper','inf'))
            if command < lower-1e-8 or command > upper+1e-8:
                raise ValueError(f'joint command outside limits: {name}')
    return values

def coupled_commands(urdf_path, source_joint, value, mapping=None):
    """Expand mimics plus explicit independent drive multipliers, validating limits."""
    values=mimic_commands(urdf_path,source_joint,value)
    if not mapping:return values
    if not isinstance(mapping,dict):raise ValueError('gripper mapping must be a mapping')
    joints={j.get('name'):j for j in ET.parse(urdf_path).getroot().findall('joint')}
    for name,multiplier in mapping.items():
        if name not in joints: raise ValueError(f'gripper joint not found: {name}')
        if not isinstance(multiplier,(int,float)) or isinstance(multiplier,bool) or not math.isfinite(multiplier):raise ValueError('invalid gripper multiplier')
        command=float(value)*multiplier
        if name in values and abs(values[name]-command)>1e-8:raise ValueError('explicit mapping conflicts with mimic rule')
        limit=joints[name].find('limit')
        if limit is not None and (command<float(limit.get('lower','-inf'))-1e-8 or command>float(limit.get('upper','inf'))+1e-8):raise ValueError(f'joint command outside limits: {name}')
        values[name]=command
    return values
