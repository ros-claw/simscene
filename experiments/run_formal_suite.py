"""Run four independently recorded jobs from one saved, unedited scene.

The first three use the prescribed seeds; the fourth is a separate long
simulation with a duration selected before the run. The suite verifier remains responsible for all acceptance gates.
Use an idle GPU and a persistent SIMSCENE_HOME containing the prepared scene.
"""
import json
import sys
import time
from pathlib import Path
from simscene.jobs import start,status
from simscene.scene import SceneStore
from simscene.verification.case_runner import evaluate as evaluate_one
from simscene.verification.acceptance import evaluate as evaluate_suite

if len(sys.argv) not in (3,4):raise SystemExit('usage: run_formal_suite.py SCENE_ID CASE_JSON [STEPS]')
scene_id,case=sys.argv[1:3];steps=int(sys.argv[3]) if len(sys.argv)==4 else 48000
if not 36000<=steps<=72000:raise SystemExit('formal duration must be 36,000–72,000 physics steps')
root=SceneStore().path;records=[]
for seed in (17,29,43,53):
    case_passed=False
    try:
        job=start(scene_id,steps,seed,case,archive_verified_objects=True)
        directory=(root/'runs'/job['run_id']).resolve()
        while True:
            current=status(job['job_id'])
            if current['state'] not in ('queued','running','paused'):break
            time.sleep(3)
        (directory/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
        if current['state']=='completed':
            try:
                report=evaluate_one(directory)
                (directory/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
                case_passed=report.get('passed') is True
            except Exception as error:
                (directory/'verification-error.txt').write_text(str(error)+'\n')
        records.append({'seed':seed,'run_id':job['run_id'],'directory':str(directory),'state':current['state']})
    except Exception as error:
        records.append({'seed':seed,'state':'launch_error','error':str(error)})
    (root/'formal-suite-progress.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(records[-1]),flush=True)
    if not case_passed:
        (root/'formal-suite-error.txt').write_text(f'seed {seed} did not complete and pass its frozen physical case; later seeds were not launched\n')
        raise SystemExit(1)
if all('directory' in record for record in records):
    try:
        report=evaluate_suite([x['directory'] for x in records[:3]],records[3]['directory'],case)
        (root/'formal-suite-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        raise SystemExit(0 if report['passed'] else 1)
    except (ValueError,OSError,KeyError,TypeError) as error:
        (root/'formal-suite-error.txt').write_text(str(error)+'\n')
raise SystemExit(1)
