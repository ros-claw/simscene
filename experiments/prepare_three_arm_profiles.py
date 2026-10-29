"""Prepare experimental profiles for three individually selected local USDs."""
import argparse
import json
from simscene.robotics.profiles import prepare

p=argparse.ArgumentParser()
p.add_argument('--kawasaki-usd',required=True)
p.add_argument('--franka-usd',required=True)
p.add_argument('--ur10-usd',required=True)
a=p.parse_args()
profiles={}
for model,path in [('kawasaki_rs007l_rg2',a.kawasaki_usd),('franka_panda',a.franka_usd),('ur10_short_suction',a.ur10_usd)]:
    profiles[model]=prepare(model,path)
print(json.dumps({'profiles':profiles,'environment':{
    'SIMSCENE_KAWASAKI_USD':a.kawasaki_usd,'SIMSCENE_KAWASAKI_PROFILE':profiles['kawasaki_rs007l_rg2']['model_directory'],
    'SIMSCENE_FRANKA_USD':a.franka_usd,'SIMSCENE_FRANKA_PROFILE':profiles['franka_panda']['model_directory'],
    'SIMSCENE_UR10_USD':a.ur10_usd,'SIMSCENE_UR10_PROFILE':profiles['ur10_short_suction']['model_directory']}},indent=2))
