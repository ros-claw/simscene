"""Compatibility CLI: export a reviewed shot plan through the generic video tools.

Robot names, phase indices, fixed rates and image sizes belong in no editor.
Pass the same JSON segment plan used by any other SimScene scene.
"""
import argparse,json
from simscene.video_tools import export
p=argparse.ArgumentParser();p.add_argument('plan',help='JSON list of source segments');p.add_argument('destination');p.add_argument('--resolution',nargs=2,type=int,default=[1920,1080]);p.add_argument('--allow-upscale',action='store_true')
a=p.parse_args()
print(json.dumps(export(json.load(open(a.plan)),a.destination,a.resolution,allow_upscale=a.allow_upscale),indent=2))
