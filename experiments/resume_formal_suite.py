"""Resume a frozen formal suite without restarting already launched jobs.

Use the same frozen worker package as the original run on PYTHONPATH. Existing
runs must have matching scene, seed, case digest and worker digest. Unknown or
ambiguous existing runs fail closed; no results or failed runs are overwritten.
"""
import hashlib,json,sys,time
from pathlib import Path
from simscene.jobs import start,status
from simscene.scene import SceneStore
from simscene.verification.case_runner import evaluate as evaluate_one
from simscene.verification.acceptance import evaluate as evaluate_suite
import simscene
if len(sys.argv)!=3:raise SystemExit('usage: resume_formal_suite.py SCENE_ID CASE_JSON')
scene_id,case_path=sys.argv[1:];case=Path(case_path).resolve();case_hash=hashlib.sha256(case.read_bytes()).hexdigest()
home=SceneStore().path.resolve();package=Path(simscene.__file__).resolve().parent
code={str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*')
      if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
records=[]
for seed in (17,29,43,53):
    matches=[]
    for lock_path in (home/'runs').glob('*/run-lock.json'):
        try:
            lock=json.loads(lock_path.read_text())
            if lock.get('scene_id')==scene_id and lock.get('seed')==seed:
                if lock.get('acceptance_case_sha256')!=case_hash or lock.get('worker_code_sha256')!=code:
                    raise RuntimeError(f'existing seed {seed} has a different case or worker')
                info=json.loads((lock_path.parent/'job.json').read_text());matches.append((lock_path.parent,info['job_id']))
        except (OSError,ValueError,KeyError) as error:raise RuntimeError(f'unreadable run metadata {lock_path}: {error}') from error
    if len(matches)>1:raise RuntimeError(f'ambiguous existing seed {seed} runs')
    if matches:directory,job_id=matches[0]
    else:
        job=start(scene_id,48000,seed,str(case),archive_verified_objects=True)
        directory=(home/'runs'/job['run_id']).resolve();job_id=job['job_id']
    while True:
        current=status(job_id)
        if current['state'] not in ('queued','running','paused'):break
        time.sleep(3)
    (directory/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
    if current['state']=='completed':
        try:
            report=evaluate_one(directory);(directory/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        except Exception as error:
            (directory/'verification-error.txt').write_text(str(error)+'\n')
    records.append({'seed':seed,'run_id':directory.name,'directory':str(directory),'state':current['state']})
    tmp=home/'formal-suite-progress.tmp';tmp.write_text(json.dumps(records,indent=2)+'\n');tmp.replace(home/'formal-suite-progress.json')
    print(json.dumps(records[-1]),flush=True)
try:
    report=evaluate_suite([r['directory'] for r in records[:3]],records[3]['directory'],str(case))
    (home/'formal-suite-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(0 if report['passed'] else 1)
except (ValueError,OSError,KeyError,TypeError) as error:
    (home/'formal-suite-error.txt').write_text(str(error)+'\n')
raise SystemExit(1)
