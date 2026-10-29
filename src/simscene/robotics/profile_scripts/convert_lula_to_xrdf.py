"""Create an experimental XRDF from NVIDIA's local legacy Lula descriptor.

Collision spheres are copied from the specified input descriptor. The resulting
model is for diagnostic loading/FK only: self-collision and full gripper
coverage must be validated before planning or physical acceptance.
"""
import argparse
import pathlib
import yaml
import xml.etree.ElementTree as ET
p=argparse.ArgumentParser(); p.add_argument('--descriptor',required=True); p.add_argument('--urdf',required=True); p.add_argument('--output',required=True); p.add_argument('--tool-frame',required=True)
a=p.parse_args()
old=yaml.safe_load(pathlib.Path(a.descriptor).read_text())
names=old['cspace']; default=dict(zip(names,old['default_q']))
for rule in old.get('cspace_to_urdf_rules', []):
    if rule.get('rule') == 'fixed': default[rule['name']]=rule['value']
mimic={j.get('name') for j in ET.parse(a.urdf).getroot().findall('joint') if j.find('mimic') is not None}
for joint in mimic: default.pop(joint, None)
spheres={}
for entry in old.get('collision_spheres',[]):
    spheres.update(entry)
if not spheres: raise ValueError('descriptor contains no collision spheres')
result={'format':'xrdf','format_version':2.0,'default_joint_positions':default,
        'cspace':{'joint_names':names,'acceleration_limits':old['acceleration_limits'],'jerk_limits':old['jerk_limits']},
        'tool_frames':[a.tool_frame], 'world_collision':{'geometry':'legacy_spheres'},
        'geometry':{'legacy_spheres':{'spheres':spheres}}}
pathlib.Path(a.output).write_text('# Derived from NVIDIA Corporation source: SPDX-License-Identifier: Apache-2.0\n# Diagnostic candidate only; self-collision has not been validated.\n' + yaml.safe_dump(result,sort_keys=False))
