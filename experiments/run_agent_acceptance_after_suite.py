"""Run fresh agent acceptance sessions sequentially after unattended GPU tests.

Each evaluator freezes its own case, checker, package and skill before the
model session. This supervisor does not change scenes or issue model actions.
Failed checks remain failures and require investigation; it never retries by
weakening the cases. It runs only after the full physical suite and its paired
negative controls pass.
"""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

if len(sys.argv) != 5:
    raise SystemExit('usage: run_agent_acceptance_after_suite.py PACKAGE SUITE_HOME PRESENTATION_LOG FEEDER_PROBE_LOG')
package, suite, showcase_log, feeder_log = map(lambda x: Path(x).resolve(), sys.argv[1:])
if not (package/'server/launch.py').is_file():
    raise SystemExit('package is missing')
root = suite/'agent-acceptance'; root.mkdir(parents=True, exist_ok=False)
result_file = root/'progress.json'
def write(result):
    tmp = result_file.with_suffix('.tmp'); tmp.write_text(json.dumps(result,indent=2)+'\n'); tmp.replace(result_file)
write({'state':'waiting_for_physical_suite','sessions':[]})
while True:
    combined_file=suite/'combined-result.json'
    if combined_file.exists():
        try:combined=json.loads(combined_file.read_text())
        except (OSError,ValueError):combined={}
        if combined and combined.get('passed') is not True:
            write({'state':'blocked_by_failed_suite_process','details':combined,'sessions':[]});raise SystemExit(1)
    for gate_file in (suite/'probe-gate.json',showcase_log.parent/'presentation-gate.json'):
        if gate_file.exists():
            try:gate=json.loads(gate_file.read_text())
            except (OSError,ValueError):continue
            if gate.get('passed') is not True:
                write({'state':'blocked_by_failed_probe','gate':str(gate_file),'details':gate,'sessions':[]});raise SystemExit(1)
    presentation_exit=showcase_log.parent/'presentation-exit.json'
    if presentation_exit.exists():
        try:presentation_result=json.loads(presentation_exit.read_text())
        except (OSError,ValueError):presentation_result={}
        if presentation_result and presentation_result.get('exit_code')!=0:
            write({'state':'blocked_by_failed_presentation','sessions':[]});raise SystemExit(1)
    if (suite/'formal-suite-error.txt').exists():
        write({'state':'blocked_by_failed_formal_suite','error':(suite/'formal-suite-error.txt').read_text(),'sessions':[]}); raise SystemExit(1)
    try:
        formal = json.loads((suite/'formal-suite-verification.json').read_text())
        negative = json.loads((suite/'negative-suite-result.json').read_text())
        showcase = json.loads(showcase_log.read_text().splitlines()[-1])
        feeder = json.loads(feeder_log.read_text().splitlines()[-1])
        if not formal.get('passed'):
            write({'state':'blocked_by_failed_formal_suite','sessions':[]}); raise SystemExit(1)
        if negative.get('reason') or len(negative.get('controls',[])) == 3:
            if not negative.get('passed'):
                write({'state':'blocked_by_failed_negative_controls','sessions':[]}); raise SystemExit(1)
            if showcase.get('state') != 'completed' or showcase.get('passed') is not True:
                write({'state':'blocked_by_failed_showcase','showcase':showcase,'sessions':[]}); raise SystemExit(1)
            if feeder.get('state') != 'completed':
                write({'state':'blocked_by_failed_feeder_probe','feeder':feeder,'sessions':[]}); raise SystemExit(1)
            break
    except (OSError, ValueError, IndexError, KeyError, TypeError):
        pass
    time.sleep(10)
base = Path.cwd()
tasks = [('workbench','experiments/agent_workbench_eval.py',[]),
         ('online','experiments/agent_online_eval.py',[]),
         ('three_arm','experiments/agent_three_arm_eval.py',[]),
         ('retime','experiments/agent_edit_eval.py',['__AGENT_SCENE__','retime']),
         ('swap','experiments/agent_edit_eval.py',['__AGENT_SCENE__','swap']),
         ('relocate','experiments/agent_edit_eval.py',['__AGENT_SCENE__','relocate'])]
results = []
previous = os.environ.get('SIMSCENE_REUSE_EVIDENCE')
if previous:
    # A model-capacity failure does not invalidate earlier independent cases.
    # Carry them forward only when they passed and their entire frozen package
    # is byte-for-byte identical to the package about to be evaluated.
    previous = Path(previous).resolve()
    current = {str(f.relative_to(package)):hashlib.sha256(f.read_bytes()).hexdigest()
               for part in ('server/vendor/simscene','skills') for f in (package/part).rglob('*')
               if f.is_file() and '__pycache__' not in f.parts}
    for name in ('workbench','online'):
        prior = previous/name
        verification = json.loads((prior/'verification.json').read_text())
        if (verification.get('passed') is not True or
                json.loads((prior/'package-hashes.json').read_text()) != current or
                hashlib.sha256((prior/'frozen-checker.py').read_bytes()).hexdigest() != (prior/'frozen-checker.sha256').read_text().strip()):
            raise SystemExit(f'cannot carry forward unverified or changed {name} case')
        results.append({'name':name, 'passed':True, 'reused_identical_frozen_evidence':True, 'directory':str(prior)})
    tasks = tasks[2:]
agent_scene = None
for name, program, extra in tasks:
    directory = root/name
    if '__AGENT_SCENE__' in extra:
        if agent_scene is None:
            results.append({'name':name,'passed':False,'error':'fresh three-arm agent scene did not pass verification'})
            write({'state':'running','sessions':results})
            continue
        extra=[str(agent_scene) if value=='__AGENT_SCENE__' else value for value in extra]
    command = [sys.executable,program,str(package),*extra,str(directory)]
    write({'state':'running','current':name,'sessions':results})
    with (root/(name+'.stdout')).open('w') as out, (root/(name+'.stderr')).open('w') as err:
        run = subprocess.run(command, stdout=out, stderr=err, check=False, cwd=base)
    item = {'name':name,'agent_exit_code':run.returncode,'passed':False,'directory':str(directory)}
    try:
        checker = directory/'frozen-checker.py'
        env = dict(os.environ,PYTHONPATH=str(package/'server/vendor'))
        if name == 'workbench':
            candidates = [d for d in (directory/'state/runs').glob('*') if (d/'result.json').is_file()]
            if not candidates:raise ValueError('no completed workbench run')
            selected = max(candidates,key=lambda p:p.stat().st_mtime)
            args = [str(checker),str(selected),str(directory/'pre_registered_case.json')]
        else:
            args = [str(checker),str(directory)]
        checked = subprocess.run([sys.executable,*args],capture_output=True,text=True,env=env,check=False,cwd=base)
        (directory/'verification.json').write_text(checked.stdout)
        (directory/'verification.stderr').write_text(checked.stderr)
        item['passed'] = run.returncode == 0 and checked.returncode == 0 and bool(json.loads(checked.stdout)['passed'])
        if name == 'three_arm' and item['passed']:
            candidates=[]
            for d in (directory/'state/runs').glob('*'):
                try:
                    result=json.loads((d/'result.json').read_text())
                    if result.get('actual_physics_steps')==result.get('requested_physics_steps') and result.get('actual_physics_steps',0)>0:
                        candidates.append(d)
                except (OSError,ValueError,TypeError):
                    continue
            selected=max(candidates,key=lambda p:p.stat().st_mtime)
            lock=json.loads((selected/'run-lock.json').read_text())
            candidate=directory/'state'/(lock['scene_id']+'.json')
            scene=json.loads(candidate.read_text())
            digest=hashlib.sha256(json.dumps(scene,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
            if digest!=lock['source_scene_sha256']:
                raise ValueError('saved agent scene differs from the independently checked run')
            agent_scene=candidate
            item['saved_scene']=str(candidate)
    except (OSError,ValueError,KeyError,IndexError,TypeError) as error:
        item['error'] = str(error)
        item['passed'] = False
    # Once the model session and frozen verification have finished, reclaim
    # any jobs it left active.  Do not let an unobserved queued run consume
    # the next evaluation's GPU slot or later be mistaken for agent evidence.
    cleanup_code = '''import json,sys
from pathlib import Path
from simscene.jobs import status,cancel
root=Path(sys.argv[1]);records=[]
for path in (root/'state'/'runs').glob('*/job.json'):
    try:
        job=json.loads(path.read_text())['job_id']; current=status(job)
        if current['state'] in ('queued','running','paused','stalled'):
            records.append(cancel(job))
    except Exception as error: records.append({'path':str(path),'error':str(error)})
(root/'post-session-cleanup.json').write_text(json.dumps({'when':'after agent exit and frozen verification','jobs':records},indent=2)+'\\n')
'''
    cleanup_env = dict(os.environ,PYTHONPATH=str(package/'server/vendor'),SIMSCENE_HOME=str(directory/'state'))
    cleanup = subprocess.run([sys.executable,'-c',cleanup_code,str(directory)],capture_output=True,text=True,env=cleanup_env,check=False)
    if cleanup.returncode:
        item['cleanup_error'] = cleanup.stderr[-2000:]
        item['passed'] = False
    results.append(item)
    write({'state':'running','sessions':results})
write({'state':'complete' if all(x['passed'] for x in results) else 'requires_investigation','sessions':results})
raise SystemExit(0 if all(x['passed'] for x in results) else 1)
