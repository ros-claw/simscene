#!/usr/bin/env python3
"""Print an unrelated drop/rest environment probe as ordinary v43 ops.

Preparation only. This source never creates a scene or starts Isaac.
A single externally scheduled native run can test import, GPU, strict observation,
contact callback and image readiness. It is excluded from all task outcomes.
"""
import json

ops=[
 {'op':'set_observation','observation':{'sample_interval_steps':1,'strict_start':True,'record_contact_pairs':True}},
 {'op':'add','id':'smoke_support','object':{'kind':'box','position':[0,0,-0.05],'size':[0.6,0.6,0.10],'collision':True,'dynamic':False,'color':[0.4,0.4,0.4]}},
 {'op':'add','id':'smoke_probe','object':{'kind':'sphere','position':[0,0,0.25],'size':[0.08]*3,'collision':True,'dynamic':True,'mass_kg':0.1,'physics':{'restitution':0.05},'color':[0.5,0.3,0.8]}},
 {'op':'add','id':'smoke_camera','object':{'kind':'camera','position':[0.8,-0.8,0.7],'camera':{'resolution':[320,240]}}},
 {'op':'look_at','id':'smoke_camera','target':[0,0,0.10]},
 {'op':'add','id':'smoke_light','object':{'kind':'light','position':[0,0,2],'intensity':1500}},
]
if __name__=='__main__':
 print(json.dumps({'ops':ops,'simulation_request':{'steps':120,'seed':19},'scope':'generic environment smoke only; do not count as a task trial'},indent=2))
