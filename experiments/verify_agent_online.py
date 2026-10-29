"""Verify a fresh agent really discovered, acquired and loaded an online asset."""
import hashlib
import json
from pathlib import Path
import sys
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs

if len(sys.argv) != 2: raise SystemExit('usage: verify_agent_online.py EVALUATION_DIRECTORY')
root = Path(sys.argv[1]).resolve()
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
checks = {'session_completed': (root/'exit-code.txt').read_text().strip() == '0',
          'no_external_intervention': not (root/'external-intervention.json').exists() and not (root/'external-interventions.jsonl').exists()}
try:
    h = (root/'frozen-checker.sha256').read_text().strip()
    checks['checker_frozen'] = h == digest(root/'frozen-checker.py') == digest(Path(__file__).resolve())
except OSError:
    checks['checker_frozen'] = False
events = []
for line in (root/'trace.jsonl').read_text().splitlines():
    event = json.loads(line); item = event.get('item', {})
    if event.get('type') != 'item.completed' or item.get('type') != 'mcp_tool_call' or item.get('status') != 'completed': continue
    value = item.get('result') or {}
    try: payload = json.loads(value['content'][0]['text'])
    except (KeyError, IndexError, TypeError, ValueError): payload = None
    events.append((item.get('tool'), item.get('arguments') or {}, payload))
searches = [payload for tool, _, payload in events if tool == 'asset_search' and isinstance(payload, dict)]
inspected = {args.get('asset_url') for tool, args, payload in events if tool == 'asset_inspect' and isinstance(payload, dict)}
acquisitions = {payload.get('job_id'): args.get('asset_url') for tool, args, payload in events if tool == 'asset_acquire' and isinstance(payload, dict)}
completed = []
for tool, _, payload in events:
    if tool != 'job_status' or not isinstance(payload, dict) or payload.get('state') != 'completed' or payload.get('job_id') not in acquisitions: continue
    result = payload.get('result') or {}; url = acquisitions[payload['job_id']]
    if result.get('source') == url and result.get('root') and result.get('dependency_status') in ('resolved_locally', 'resolved_with_runtime') and not result.get('unresolved_dependencies'):
        completed.append((url, result['root'], result.get('package_sha256')))
checks['public_search_returned_candidates'] = any(p.get('hits') for p in searches)
checks['selected_result_was_inspected_and_acquired'] = any(url in inspected and any(url in json.dumps(s) for s in searches) for url, path, package_hash in completed)
runs = []
for directory in (root/'state'/'runs').glob('*'):
    try:
        spec = json.loads((directory/'spec.json').read_text()); result = json.loads((directory/'result.json').read_text())
        if result.get('actual_physics_steps') != result.get('requested_physics_steps') or not result.get('actual_physics_steps'): continue
        asset_lock = json.loads((directory/'asset-lock.json').read_text())
        selected = []
        for name,obj in spec['objects'].items():
            if obj.get('kind') != 'asset':continue
            locked=asset_lock.get(name) or {}
            if locked.get('kind')!='snapshot':continue
            relative=locked.get('root_relative_to_run')
            if not isinstance(relative,str) or (directory/relative).resolve()!=Path(obj.get('asset_path','')).resolve():continue
            for url,path,package_hash in completed:
                if (url in inspected and any(url in json.dumps(s) for s in searches) and
                    locked.get('source')==url and package_hash and locked.get('package_sha256')==package_hash):
                    selected.append((name,url,path,package_hash))
        if selected: runs.append((directory,spec,result,selected))
    except (OSError, ValueError, KeyError, TypeError): continue
checks['completed_run_used_selected_asset'] = bool(runs)
directory = None
if runs:
    directory, spec, result, selected = max(runs, key=lambda x: x[0].stat().st_mtime)
    try:
        job_id = json.loads((directory/'job.json').read_text()).get('job_id')
        run_calls = [(tool,args,payload) for tool,args,payload in events if args.get('job_id') == job_id]
        checks['agent_observed_selected_run'] = any(tool in ('run_observe','scene_observe') for tool,_,_ in run_calls)
        checks['agent_saw_completed_run'] = any(tool == 'job_status' and isinstance(payload,dict) and payload.get('state') == 'completed' for tool,_,payload in run_calls)
        checks['input_integrity'] = verify_inputs(directory)['passed']
        output = verify_outputs(directory)
        checks['output_integrity'] = output['passed'] and not output['partial']
        lock = json.loads((directory/'run-lock.json').read_text())
        package = json.loads((root/'package-hashes.json').read_text()); prefix = 'server/vendor/simscene/'
        worker = {n[len(prefix):]:v for n,v in package.items() if n.startswith(prefix)}
        checks['worker_matches_frozen_package'] = bool(worker) and worker == lock.get('worker_code_sha256')
        prefix = 'skills/'
        expected = {n[len(prefix):]:v for n,v in package.items() if n.startswith(prefix)}
        skills = root/'work'/'.agents'/'skills'
        observed = {str(p.relative_to(skills)):digest(p) for p in skills.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        checks['skill_matches_frozen_package'] = bool(expected) and expected == observed
        checks['camera_observation_saved'] = bool(result.get('images'))
        from pxr import Usd
        stage = Usd.Stage.Open(str(directory/'scene.usda'))
        checks['selected_asset_has_composed_prims'] = any(
            bool(prim and prim.IsValid() and list(prim.GetChildren()))
            for name,obj in spec['objects'].items() if name in {item[0] for item in selected}
            for prim in [stage.GetPrimAtPath('/World/'+name.replace('-', '_')+'/Asset')])
    except (OSError, ValueError, KeyError, TypeError, ImportError, AttributeError):
        checks['run_verifiable'] = False
report = {'passed':all(checks.values()), 'checks':checks, 'run_directory':str(directory) if directory else None,
          'scope':'One fresh session and one selected online model; does not establish that every indexed asset or dependency is available.'}
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
