"""Frozen relational/physical reuse check; no scene construction or repair."""
import hashlib,json,math,sys
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
if len(sys.argv)!=2:raise SystemExit('usage: verify_visual_workbench.py FULL_EVALUATION_DIRECTORY')
root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(repo/'src'))
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs
from simscene.video_tools import inspect
criteria=json.load(open(root/'acceptance-frozen.json'));trace=[json.loads(l) for l in (root/'tool-trace.jsonl').read_text().splitlines()];selected=json.load(open(root/'selected-assets.json'));case_hash=(root/'acceptance-frozen.sha256').read_text().strip()
job=json.load(open(root/'formal-job.json'));run=root/'state/runs'/job['run_id'];result=json.load(open(run/'result.json'));spec=json.load(open(run/'spec.json'));assets=json.load(open(run/'asset-lock.json'))
checks={'criteria_unchanged':hashlib.sha256((root/'acceptance-frozen.json').read_bytes()).hexdigest()==case_hash,'inputs':verify_inputs(run)['passed'],'outputs':verify_outputs(run)['passed']}
frozen=json.load(open(repo/'evidence/visual-upgrade-v31/frozen-implementation.json'))['files'];checks['runtime_and_skills_frozen']=all(hashlib.sha256((repo/p).read_bytes()).hexdigest()==sha for p,sha in frozen.items())
checks['empty_scene_observed']=any(r['tool']=='scene_open' and r['result'].get('revision')==0 and not r['result'].get('objects') for r in trace)
rows={};tray_positions=[]
for name in criteria['required_tray_ids']:
 pos=spec['objects'][name]['position'];rows.setdefault(round(pos[1],4),[]).append(pos[0]);tray_positions.append(pos)
checks['two_rows_three_trays']=len(rows)==criteria['rows'] and all(len(v)==criteria['columns'] for v in rows.values())
checks['cart_and_rear_rack']=criteria['cart_id'] in assets and spec['objects'][criteria['shelf_id']]['position'][1]>spec['objects'][criteria['bench_id']].get('position',[0,0,0])[1]
checks['three_online_part_categories']=len({assets[name]['source'] for name in assets if name.startswith('part_')})>=criteria['part_source_categories_minimum']
checks['all_imports_query_bound']=all(entry.get('source') in {v['source'] for v in selected.values()} for entry in assets.values()) and all(any(r['tool']=='asset_search' and any(h.get('source',{}).get('base_key')==choice['source'] and h.get('id')==choice['hit_id'] for h in r['result'].get('hits',[])) for r in trace) for choice in selected.values())
checks['completion_observed_via_tool']=any(r['tool']=='job_status' and r['args'].get('job_id')==job['job_id'] and r['result'].get('state')=='completed' and r['result'].get('result',{}).get('actual_physics_steps')==result['actual_physics_steps'] for r in trace)
checks['completed_physics_steps']=result['actual_physics_steps']==result['requested_physics_steps']==1800
receiver=spec['objects'][criteria['receiver_id']];p=receiver['position'];size=receiver['size'];item_checks={}
for name in criteria['dynamic_ids']:
 path='/World/'+name;observations=[s['positions'][path] for s in result['samples'] if path in s.get('positions',{})];last=observations[-1] if observations else [];tail=observations[-24:]
 motion=max((math.dist(a,b) for a in tail for b in tail),default=float('inf'))
 has_contact=any(k.startswith(name+'|/World/'+criteria['receiver_id']+'|') and v.get('count',0)>0 for k,v in result.get('contact_counts',{}).items())
 item_checks[name]={'spawned':any(e['id']==name for e in result['spawn_events']),'fell':bool(observations and observations[0][2]-last[2]>=criteria['minimum_fall_m']),'contact':has_contact,'contained':bool(last and all(p[i]-size[i]/2+.02<=last[i]<=p[i]+size[i]/2-.02 for i in (0,1)) and p[2]+size[2]/2<=last[2]<=p[2]+size[2]/2+.05),'settled':motion<=criteria['maximum_terminal_motion_m'],'terminal_motion_m':motion}
checks['all_three_real_drops']=all(all(v for k,v in item.items() if k!='terminal_motion_m') for item in item_checks.values()) and result.get('contacts_truncated') is False
videos={name:inspect(v['path'],record=v) for name,v in result.get('videos',{}).items()}
checks['native_captures']=len(videos)>=criteria['minimum_camera_count'] and all(v['simulation_timeline']['passed'] and result['videos'][name]['native_resolution']==criteria['native_resolution'] and result['videos'][name]['fps']==criteria['fps'] for name,v in videos.items())
checks['generic_camera_planner_used']=any(r['tool']=='scene_plan_presentation' and not r['is_error'] for r in trace)
report={'passed':all(checks.values()),'checks':checks,'dynamic_outcomes':item_checks,'source_run':str(run),'scope':criteria['scope'],'visual_review':'separate representative/action-frame review required'};(root/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));raise SystemExit(0 if report['passed'] else 1)
