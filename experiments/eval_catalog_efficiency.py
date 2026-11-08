#!/usr/bin/env python3
"""Frozen paired Codex benchmark. Import, freeze and aggregate never launch a model.

The host-provided binding bundle is trusted evaluator configuration, never agent
output. Actual execution requires explicit run-trial and the frozen plan hash.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

try:
    from experiments import eval_catalog_agent as agent
    from experiments.pilot_usage import normalize
except ModuleNotFoundError:
    import eval_catalog_agent as agent
    from pilot_usage import normalize

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = ROOT / 'examples/catalog_benchmark/protocol.json'
DEFAULT_TASKS = ROOT / 'examples/catalog_benchmark/tasks.json'


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write('\n')


def inventory(root):
    root = Path(root).resolve()
    if not root.is_dir(): raise ValueError('missing input directory')
    if any(p.is_symlink() for p in root.rglob('*')): raise ValueError('symlinked frozen input')
    return {str(p.relative_to(root)): agent.digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def usage(path, *, live=False):
    """Deduplicate completed-turn delivery by turn/event ID, else exact payload.

    Anonymous identical events are ambiguous: return unknown rather than silently
    undercount two genuine turns. Session cumulative snapshots are never added.
    """
    rows = []; seen = {}; anonymous = set(); errors = []
    lines=Path(path).read_text().splitlines(keepends=True)
    for number, line in enumerate(lines, 1):
        if live and number==len(lines) and not line.endswith('\n'): continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict): raise ValueError('event must be object')
            if event.get('type') not in ('turn.completed','turn.failed'): continue
            if event.get('usage') is None:
                errors.append({'line':number,'error':'turn usage absent'}); continue
            value = normalize(event['usage']); identity = event.get('turn_id') or event.get('id')
            fingerprint = sha(event)
            if identity is None:
                if fingerprint in anonymous: raise ValueError('ambiguous repeated anonymous usage')
                anonymous.add(fingerprint)
            elif identity in seen:
                if seen[identity] != value: raise ValueError('conflicting duplicate turn usage')
                continue
            else: seen[identity] = value
            rows.append(value)
        except (ValueError, TypeError, KeyError) as error:
            errors.append({'line': number, 'error': str(error)})
    subtotal = None
    if rows:
        subtotal = {key: sum(row[key] for row in rows) if all(row[key] is not None for row in rows) else None for key in rows[0]}
    return {'aggregate': subtotal if not errors else None, 'known_reported_subtotal':subtotal, 'reported_turns': len(rows), 'errors': errors,
            'billing_amount': None, 'availability': 'reported' if subtotal and not errors else 'partial' if subtotal else 'unknown'}


def phase_seconds(intervals):
    """Union actual monotonic intervals independently for each phase."""
    result = {}
    for phase in ('setup','index','download','authoring','simulation','render','warm_edit','strict_replay'):
        spans = []
        for row in intervals:
            if row.get('phase') != phase: continue
            a, b = row['start_s'], row['end_s']
            if type(a) not in (int,float) or type(b) not in (int,float) or not 0 <= a <= b < float('inf'):
                raise ValueError('invalid monotonic phase interval')
            spans.append((a,b))
        merged = []
        for a,b in sorted(spans):
            if merged and a <= merged[-1][1]: merged[-1][1] = max(b,merged[-1][1])
            else: merged.append([a,b])
        result[phase] = sum(b-a for a,b in merged) if spans else None
    return result


def schedule(tasks, protocol, pilot=False):
    selected = [t for t in tasks if not pilot or t['id'] in protocol['pilot_task_ids']]
    result = []; pair = 0
    for task in selected:
        for repetition in range(protocol['pilot_repetitions'] if pilot else protocol['repetitions']):
            order = ('baseline','candidate') if pair % 2 == 0 else ('candidate','baseline')
            pair_id = f"{task['id']}-{repetition+1}"
            for version in order:
                result.append({'trial_id': pair_id+'-'+version, 'pair_id': pair_id, 'task_id': task['id'],
                               'group': task['group'], 'phase': task['phase'], 'cache': task['cache'],
                               'repetition': repetition+1, 'version': version})
            pair += 1
    return result


def freeze(protocol_path, tasks_path, bindings_path, baseline_package, candidate_package, candidate_commit, *, model=None, pilot=True):
    protocol, tasks, bindings = read(protocol_path), read(tasks_path)['tasks'], read(bindings_path)
    if len(tasks) != 6 or len({t['id'] for t in tasks}) != len(tasks): raise ValueError('six distinct tasks required')
    if not __import__('re').fullmatch('[0-9a-f]{40}', candidate_commit): raise ValueError('full candidate commit required')
    if model is not None: protocol['model'] = model
    protocol['candidate_commit'] = candidate_commit
    if not protocol['model'] or protocol['reasoning_effort'] != 'medium': raise ValueError('fixed explicit model and medium effort required')
    if any(not protocol['hardware'].get(k) for k in ('host','gpu','isaac','usd','renderer')):
        raise ValueError('freeze observed hardware/runtime settings before trials')
    packages = {}
    for version, path in [('baseline',baseline_package),('candidate',candidate_package)]:
        path = Path(path).resolve()
        if path.is_relative_to(ROOT): raise ValueError('package must be isolated outside checkout')
        if not (path/'server/launch.py').is_file(): raise ValueError('installed isolated package required')
        packages[version] = {'path':str(path),'files':inventory(path)}
    if packages['baseline']['path']==packages['candidate']['path']: raise ValueError('distinct version packages required')
    verifier = Path(bindings['verifier']).resolve()
    if not verifier.is_file() or verifier.is_symlink(): raise ValueError('frozen host verifier required')
    task_inputs = {}
    for task in tasks:
        binding = bindings['tasks'][task['id']]
        path = Path(binding['inputs']).resolve()
        # Assets, predicate files and seeds are identical across versions.
        files = inventory(path)
        if not files: raise ValueError('task source/quality predicates must be frozen')
        if task['cache'] == 'paired_warm' and not any(p.startswith('cache/') for p in files):
            raise ValueError('warm pair requires identical frozen cache seed')
        if not binding.get('acceptance_file') or binding['acceptance_file'] not in files:
            raise ValueError('host acceptance predicates required for every task')
        task_inputs[task['id']] = dict(binding, inputs=str(path), files=files)
    plan = {'schema':'simscene.catalog_efficiency_plan.v1','protocol':protocol,'tasks':tasks,
            'packages':packages,'inputs':task_inputs,'verifier':str(verifier),'verifier_sha256':agent.digest(verifier),
            'harness_sha256':agent.digest(Path(__file__)),'agent_harness_sha256':agent.digest(Path(agent.__file__)),
            'schedule':schedule(tasks,protocol,pilot),'pilot':pilot,
            'server_environment':bindings.get('server_environment',{}),'v2_config':bindings.get('v2_config',{}),
            'tool_allowlist':bindings.get('tool_allowlist',list(agent.ALLOWED_TOOLS)),
            'scope':'same-machine bounded trials; no savings result before actual verified pairs'}
    if len(plan['schedule'])>protocol['max_trials']: raise ValueError('trial budget exceeded')
    plan['comparison_fingerprint'] = sha({k:v for k,v in plan.items() if k not in ('schedule','pilot')})
    plan['plan_sha256'] = sha(plan)
    return plan


def verify_plan(plan):
    identity = dict(plan); expected = identity.pop('plan_sha256')
    if sha(identity) != expected: raise ValueError('frozen plan hash changed')
    for value in plan['packages'].values():
        if inventory(value['path']) != value['files']: raise ValueError('package drift')
    for value in plan['inputs'].values():
        if inventory(value['inputs']) != value['files']: raise ValueError('task/cache input drift')
    for key,path in [('verifier_sha256',plan['verifier']),('harness_sha256',__file__),('agent_harness_sha256',agent.__file__)]:
        if agent.digest(Path(path)) != plan[key]: raise ValueError('evaluator drift')


def remap_seed_metadata(source, output, work):
    """Relocate documented JSON locator fields; never modify frozen inputs.

    Source geometry, URLs and file/hash inventories are byte-for-byte retained.
    The receipt records original and relocated metadata hashes separately.
    """
    import shutil
    source,output,work=map(Path,(source,output,work))
    replacements={'${CACHE_ROOT}':str((output/'cache').resolve()),'${TASK_ROOT}':str((work/'task').resolve())}
    allowed={'root','asset_path','manifest_path'}
    def relocate(value):
        if isinstance(value,dict):
            result={}
            for key,item in value.items():
                if key in allowed and isinstance(item,str):
                    for token,replacement in replacements.items():
                        if item==token or item.startswith(token+'/'):item=replacement+item[len(token):]
                    result[key]=item
                else:result[key]=relocate(item)
            return result
        if isinstance(value,list):return [relocate(item) for item in value]
        return value
    receipts=[]
    candidates=[]
    if (source/'cache').is_dir():
        candidates.extend((p,output/'cache'/p.relative_to(source/'cache')) for p in (source/'cache').rglob('simscene-lock.json'))
    if (source/'seed-scene.json').is_file():candidates.append((source/'seed-scene.json',work/'seed-scene-resolved.json'))
    for original,target in candidates:
        if original.is_symlink() or original.stat().st_size>5*1024**2:raise ValueError('invalid frozen seed metadata')
        before=read(original);after=relocate(before)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(after,indent=2)+'\n')
        receipts.append({'original':str(original.relative_to(source)),'relocated':str(target.relative_to(output)),
                         'original_sha256':agent.digest(original),'relocated_sha256':agent.digest(target),
                         'scope':'documented root/asset_path/manifest_path locator fields only'})
    write_new(output/'seed-remapping.json',{'schema_version':1,'path_tokens':replacements,'files':receipts,
        'source_inventory_unchanged':inventory(source)==inventory(work/'task')})
    return receipts


def isolated_client_environment(output, environment):
    """Use fresh client state; copy only private auth and model-capability metadata.

    Credential contents/hashes never enter receipts. Parent configuration,
    instructions, skills, plugin registrations and conversation history do not
    migrate into the evaluation client. Work-local installed skills remain.
    """
    import shutil
    source=Path(environment.get('CODEX_HOME',str(Path.home()/'.codex'))).expanduser()
    client_state_root=Path(output)/'client-state'
    client_state_root.mkdir(mode=0o700)
    copied=[]
    for name in ('auth.json','models_cache.json'):
        path=source/name
        if not path.exists():continue
        info=path.stat()
        if path.is_symlink() or not path.is_file() or info.st_uid!=os.getuid() or info.st_size>16*1024**2:
            raise ValueError('client state must be bounded owned regular files')
        target=client_state_root/name
        shutil.copyfile(path,target);target.chmod(0o600);copied.append(name)
    result=dict(environment,CODEX_HOME=str(client_state_root.resolve()))
    write_new(Path(output)/'client-isolation.json',{
        'schema':'simscene.eval_client_isolation.v1','client_state':str(client_state_root.resolve()),
        'copied_filenames':copied,'global_configuration_copied':False,
        'global_instructions_copied':False,'global_skills_or_plugins_copied':False,
        'credential_values_recorded':False,'scope':'client-state isolation; not an operating-system read jail'})
    return result


def run_trial(plan, trial_id, output):
    """Actual Codex CLI, isolated MCP package and host verifier; no implicit retry."""
    import shutil
    setup_started=time.monotonic()
    verify_plan(plan)
    trial = next(row for row in plan['schedule'] if row['trial_id'] == trial_id)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(ROOT): raise ValueError('new output outside checkout required')
    output.mkdir(parents=True); work=output/'work'; work.mkdir(); state=output/'state'; state.mkdir()
    binding=plan['inputs'][trial['task_id']]; source=Path(binding['inputs'])
    shutil.copytree(source,work/'task')
    for folder in ('cache','prepared','index'):
        if (source/folder).is_dir(): shutil.copytree(source/folder,output/folder)
    remap_seed_metadata(source,output,work)
    package=Path(plan['packages'][trial['version']]['path'])
    shutil.copytree(package/'skills',work/'.agents/skills')
    for skill in (work/'.agents/skills').iterdir():
        if skill.is_dir(): (skill/'.simscene-plugin-root').write_text(str(package)+'\n')
    config=dict(plan['v2_config'],index_directory=str(output/'index'),prepared_directory=str(output/'prepared'))
    write_new(output/'v2.json',config)
    env=dict(plan['server_environment'],SIMSCENE_HOME=str(state),SIMSCENE_CACHE=str(output/'cache'),
             XDG_CONFIG_HOME=str(output/'config'),SIMSCENE_V2_CONFIG=str(output/'v2.json'),SIMSCENE_PHYSICS_DEVICE='cpu')
    task=next(t for t in plan['tasks'] if t['id']==trial['task_id'])
    prompt=('Use only this work directory, copied installed skills and configured SimScene MCP. Do not read global skills or global configuration. Do not list global MCP resources or templates; only the configured SimScene tools and its explicit simscene://catalog/sources resource are allowed. No child agents, source checkout reads, direct SDK/shell SimScene calls or network shell commands. Preserve every failed attempt. Submit submission.json with scene_id, run_ids (every attempted run ID), selected_run_id, and evidence paths. For an unsupported new capability, optionally include capability_gap:{capability:NAME}; only the host can verify a capability gap. Agent assertions are not verification. Read all fixed task inputs and acceptance predicates in task/. Do not modify them. If seed-scene-resolved.json exists, it is the same frozen seed with documented local asset locators resolved; use it as the warm task starting scene. The worker already saves the complete trajectory. Inspect only a few representative observations rather than streaming every physics step through MCP. The trusted host verifier reads the full saved trajectory directly; its acceptance file need not be a stock run_verify case. Write submission.json promptly after completing the chosen run and saving its evidence paths; do not reproduce the host audit frame by frame.\n'+task['prompt'])
    (output/'prompt.txt').write_text(prompt)
    (work/'AGENTS.md').write_text('Use only own work and configured MCP. Do not modify task inputs.\n')
    cmd=agent.command(package,work,output,plan['protocol']['model'],plan['protocol']['reasoning_effort'],env)
    cmd[2:2]=['-c','skills.bundled.enabled=false']
    key='mcp_servers.simscene.enabled_tools='
    cmd=[key+json.dumps(plan['tool_allowlist']) if x.startswith(key) else x for x in cmd]
    write_new(output/'trial-config.json',dict(trial,plan_sha256=plan['plan_sha256'],command=cmd,mcp_environment=env))
    environment=dict(os.environ,**env); environment.pop('PYTHONPATH',None)
    environment=isolated_client_environment(output,environment)
    setup_wall_s=time.monotonic()-setup_started
    p=plan['protocol']; wall=p['pilot_wall_limit_s'] if plan['pilot'] else p['wall_limit_s']; cap=p['pilot_token_limit'] if plan['pilot'] else p['token_limit']
    started=time.monotonic(); completion={'exit_code':None,'timed_out':False,'token_limit_reached':False}; process=None
    with (output/'events.jsonl').open('x') as stdout,(output/'stderr.log').open('x') as stderr:
        try:
            completion['client_version']=subprocess.run(['codex','--version'],capture_output=True,text=True,timeout=10,check=True).stdout.strip()
            process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,cwd=work,env=environment,text=True,start_new_session=True)
            process.stdin.write(prompt); process.stdin.close()
            while process.poll() is None:
                completion['timed_out']=time.monotonic()-started>=wall
                observed=usage(output/'events.jsonl',live=True)
                output_cap=p['pilot_output_token_limit'] if plan['pilot'] else p['output_token_limit']
                completion['token_limit_reached']=bool(observed['aggregate'] and (observed['aggregate']['total_tokens']>=cap or observed['aggregate']['output_tokens']>=output_cap))
                completion['trace_budget_exceeded']=(output/'events.jsonl').stat().st_size>=p['max_trace_bytes']
                completion['usage_invalid']=bool(observed['errors'])
                if completion['timed_out'] or completion['token_limit_reached'] or completion['trace_budget_exceeded'] or completion['usage_invalid']: break
                time.sleep(.2)
        except (OSError,subprocess.SubprocessError) as error: completion['launch_error']=str(error)
        finally:
            if process is not None:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL); process.wait()
                completion['exit_code']=process.returncode
    completion['wall_s']=time.monotonic()-started
    final_usage=usage(output/'events.jsonl')
    output_cap=p['pilot_output_token_limit'] if plan['pilot'] else p['output_token_limit']
    if final_usage['aggregate'] and (final_usage['aggregate']['total_tokens']>=cap or final_usage['aggregate']['output_tokens']>=output_cap):
        completion['token_limit_reached']=True
    if final_usage['errors']: completion['usage_invalid']=True
    write_new(output/'completion.json',completion)
    # Verifier runs in host process, after model exits, with exact frozen predicates.
    verifier_started=time.monotonic()
    try:
        verified=subprocess.run([sys.executable,plan['verifier'],'--task',trial['task_id'],'--work',str(work),
                                 '--state',str(state),'--package',str(package),'--acceptance',str(source/binding['acceptance_file'])],
                                capture_output=True,text=True,timeout=p['verifier_timeout_s'],env=environment)
        (output/'verifier.stdout').write_text(verified.stdout); (output/'verifier.stderr').write_text(verified.stderr)
        evidence=json.loads(verified.stdout) if verified.returncode==0 else {'passed':False,'error':'host verifier exit nonzero'}
    except (OSError,ValueError,subprocess.SubprocessError) as error: evidence={'passed':False,'error':str(error)}
    if not isinstance(evidence,dict): evidence={'passed':False,'error':'host verifier returned non-object'}
    try:
        verify_plan(plan)
        if inventory(work/'task')!=binding['files']: raise ValueError('task inputs changed')
    except ValueError as error:
        evidence={'passed':False,'error':str(error)}
    result=trial_result(plan,trial,output,completion,evidence)
    result['host_verifier_wall_s']=time.monotonic()-verifier_started
    result['setup_wall_s']=setup_wall_s
    write_new(output/'trial-result.json',result)
    return result


def approved_mcp_call(call, allowlist):
    if call.get('server')!='simscene':return False
    if call.get('tool') in allowlist:return True
    args=call.get('arguments',{})
    return (call.get('tool')=='read_mcp_resource' and isinstance(args,dict)
            and args.get('server')=='simscene' and args.get('uri')=='simscene://catalog/sources')


def trial_result(plan, trial, output, completion, evidence):
    output=Path(output); trace=agent.analyze_trace(output/'events.jsonl',output/'work')
    # Reuse audit-v2 command rules; extend only the explicit frozen tool allowlist.
    violations=[v for v in trace['scope_violations'] if v['reason']!='unapproved MCP tool']
    violations += [{'reason':'unapproved MCP tool'} for c in trace['calls'] if not approved_mcp_call(c,plan['tool_allowlist'])]
    measured=usage(output/'events.jsonl')
    try: phases=phase_seconds(evidence.get('phase_intervals',[]))
    except (ValueError,KeyError,TypeError) as error:
        phases=phase_seconds([]); evidence=dict(evidence,passed=False,phase_error=str(error))
    verified=evidence.get('passed') is True and evidence.get('provenance_verified') is True and evidence.get('quality_verified') is True
    stopped=any(completion.get(k) for k in ('timed_out','token_limit_reached','trace_budget_exceeded','launch_error','usage_invalid'))
    status='passed' if verified and completion.get('exit_code')==0 and not stopped and not violations and not trace['invalid_lines'] else 'failed'
    if completion.get('timed_out'): status='timeout'
    if trial['group']=='B' and evidence.get('capability_gap') is True and evidence.get('capability_gap_verified') is True and not verified and not stopped and not violations and not trace['invalid_lines']: status='capability_gap'
    return dict(trial,plan_sha256=plan['plan_sha256'],status=status,completion=completion,usage=measured,
                trace_sha256=agent.digest(output/'events.jsonl'),verifier=evidence,
                tool_calls=len(trace['calls']),failed_tool_calls=sum(not c['successful'] for c in trace['calls']),
                tool_return_bytes=sum(len(json.dumps(c.get('result'),ensure_ascii=False).encode()) for c in trace['calls']),
                tool_return_bytes_method='UTF-8 serialized final result per unique tool call in actual trace, not transport bytes',
                phases=phases,actual_download_bytes=evidence.get('actual_download_bytes'),
                video_passed=evidence.get('video_passed'),scope_violations=violations,
                manual_interventions=evidence.get('manual_interventions',[]),billing_amount=None)


def aggregate(plan, results):
    expected={r['trial_id']:r for r in plan['schedule']}; by_id={}
    for row in results:
        if row['trial_id'] in by_id: raise ValueError('duplicate trial result; do not double-count retries')
        if row.get('plan_sha256')!=plan['plan_sha256'] or row['trial_id'] not in expected: raise ValueError('foreign trial')
        for key in ('pair_id','task_id','group','phase','cache','version','repetition'):
            if row.get(key)!=expected[row['trial_id']][key]: raise ValueError('trial pairing changed')
        by_id[row['trial_id']]=row
    groups={}
    for group in ('A','B'):
        rows=[r for r in by_id.values() if r['group']==group]
        versions={}
        for version in ('baseline','candidate'):
            subset=[r for r in rows if r['version']==version]
            amounts=[r['usage']['aggregate']['total_tokens'] if r['usage']['aggregate'] else None for r in subset]
            known=[(r['usage'].get('known_reported_subtotal') or r['usage']['aggregate'] or {}).get('total_tokens') for r in subset]
            versions[version]={'trials':len(subset),'passed':sum(r['status']=='passed' for r in subset),
                'capability_gaps':sum(r['status']=='capability_gap' for r in subset),
                'all_trial_reported_tokens':sum(x for x in known if x is not None),'missing_usage_trials':sum(x is None for x in amounts),
                'all_trial_wall_s':sum(r['completion']['wall_s'] for r in subset),
                'known_download_bytes':sum(r.get('actual_download_bytes') or 0 for r in subset),
                'missing_download_byte_trials':sum(r.get('actual_download_bytes') is None for r in subset),
                'video_passed':sum(r.get('video_passed') is True for r in subset),
                'video_measured_trials':sum(type(r.get('video_passed')) is bool for r in subset)}
        paired=[]
        for pair_id in sorted({r['pair_id'] for r in rows}):
            pair={r['version']:r for r in rows if r['pair_id']==pair_id}
            if set(pair)!= {'baseline','candidate'}: continue
            a,b=pair['baseline'],pair['candidate']
            clean=all(r['status']=='passed' and not r['manual_interventions'] for r in (a,b))
            tokens=[r['usage']['aggregate'] for r in (a,b)]
            client_match=bool(a['completion'].get('client_version') and a['completion'].get('client_version')==b['completion'].get('client_version'))
            comparable=group=='A' and clean and client_match
            paired.append({'pair_id':pair_id,'baseline_trial':a['trial_id'],'candidate_trial':b['trial_id'],
                'statuses':[a['status'],b['status']], 'client_versions_match':client_match, 'comparable_pass_pair':comparable,
                'token_ratio':tokens[1]['total_tokens']/tokens[0]['total_tokens'] if comparable and all(tokens) and tokens[0]['total_tokens']>0 else None,
                'wall_ratio':b['completion']['wall_s']/a['completion']['wall_s'] if comparable and a['completion']['wall_s']>0 else None})
        ratios=[x['token_ratio'] for x in paired if x['token_ratio'] is not None]
        groups[group]={'versions':versions,'pairs':paired,'median_paired_token_ratio':statistics.median(ratios) if ratios else None}
    return {'schema':'simscene.catalog_efficiency_report.v1','plan_sha256':plan['plan_sha256'],'comparison_fingerprint':plan.get('comparison_fingerprint'),
            'status':'complete' if len(by_id)==len(expected) else 'incomplete','missing_trials':sorted(set(expected)-set(by_id)),
            'groups':groups,'trial_results':list(by_id.values()),'savings_claim':None,
            'limitations':'Small same-machine sample; missing counters and unsuccessful pairs cannot establish token savings.'}


def preflight(plan):
    verify_plan(plan)
    return {'status':'frozen_not_executed','plan_sha256':plan['plan_sha256'],
            'model':plan['protocol']['model'],'reasoning_effort':plan['protocol']['reasoning_effort'],
            'trials':len(plan['schedule']),'pilot':plan['pilot'],
            'shared_input_hashes':{key:sha(value['files']) for key,value in plan['inputs'].items()},
            'capability_checks':[{ 'task_id':task['id'], 'group':task['group'],
                'required':task.get('capability','common legacy capability'),
                'status':'host verifier must establish actual support or capability gap'} for task in plan['tasks']],
            'runtime_probe':'not executed; caller-frozen observed runtime settings required',
            'read_isolation':'workspace instructions and trace audit; not an operating-system read jail'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='action',required=True)
    f=sub.add_parser('freeze')
    f.add_argument('--protocol',default=str(DEFAULT_PROTOCOL)); f.add_argument('--tasks',default=str(DEFAULT_TASKS))
    for key in ('bindings','baseline-package','candidate-package','candidate-commit','output'): f.add_argument('--'+key,required=True)
    f.add_argument('--model'); f.add_argument('--full',action='store_true')
    f.add_argument('--pilot-report'); f.add_argument('--reviewed-pilot-sha256')
    r=sub.add_parser('run-trial')
    for key in ('plan','plan-sha256','trial-id','output'): r.add_argument('--'+key,required=True)
    q=sub.add_parser('preflight');q.add_argument('--plan',required=True)
    a=sub.add_parser('aggregate'); a.add_argument('--plan',required=True); a.add_argument('--results',nargs='*',default=[]); a.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    if args.action=='preflight':
        print(json.dumps(preflight(read(args.plan)),indent=2));return 0
    if args.action=='freeze':
        if args.full and (not args.pilot_report or not args.reviewed_pilot_sha256):
            raise ValueError('full schedule needs explicit reviewed two-pair pilot report hash')
        if args.full:
            report=read(args.pilot_report)
            if agent.digest(Path(args.pilot_report))!=args.reviewed_pilot_sha256:
                raise ValueError('pilot report hash changed')
            if report.get('status')!='complete' or len(report.get('trial_results',[]))!=4:
                raise ValueError('complete two-pair pilot required')
            if any(r['status']!='passed' for r in report['trial_results'] if r['group']=='A'):
                raise ValueError('common-task pilot did not pass; fix and refreeze before expansion')
            if any(not r.get('usage',{}).get('aggregate') or not r.get('trace_sha256') or not r.get('verifier') for r in report['trial_results']):
                raise ValueError('pilot collection is incomplete')
        result=freeze(args.protocol,args.tasks,args.bindings,args.baseline_package,args.candidate_package,args.candidate_commit,model=args.model,pilot=not args.full)
        if args.full:
            if report.get('comparison_fingerprint')!=result['comparison_fingerprint']:
                raise ValueError('pilot and full comparison inputs differ')
            result['reviewed_pilot_sha256']=args.reviewed_pilot_sha256
            result.pop('plan_sha256'); result['plan_sha256']=sha(result)
    elif args.action=='run-trial':
        plan=read(args.plan)
        if args.plan_sha256!=plan['plan_sha256']: raise ValueError('explicit frozen plan hash required')
        result=run_trial(plan,args.trial_id,args.output)
        print(json.dumps({'trial_id':result['trial_id'],'status':result['status']})); return 0
    else: result=aggregate(read(args.plan),[read(path) for path in args.results])
    write_new(args.output,result); print(json.dumps({'output':args.output,'plan_sha256':result['plan_sha256']})); return 0


if __name__=='__main__': raise SystemExit(main())
