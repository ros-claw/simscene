"""Resume paired negative controls against a frozen seed-17 baseline."""
import json,os,subprocess,sys,time
from pathlib import Path
from simscene.jobs import status
from simscene.verification.case_runner import evaluate
if len(sys.argv)!=3:raise SystemExit('usage: resume_negative_suite.py SCENE_ID CASE_JSON')
scene_id,case=sys.argv[1:];home=Path(os.environ['SIMSCENE_HOME']).resolve()
progress=json.loads((home/'formal-suite-progress.json').read_text());baseline=Path(next(x['directory'] for x in progress if x['seed']==17)).resolve()
results=[]
for mode in ('disable_drive','disable_suction','stop_belt'):
    matches=[]
    for p in (home/'runs').glob('*/run-lock.json'):
        lock=json.loads(p.read_text())
        if lock.get('scene_id')=='control_'+mode:
            info=json.loads((p.parent/'job.json').read_text());matches.append((p.parent,info['job_id']))
    if len(matches)>1:raise RuntimeError('ambiguous control '+mode)
    if matches:
        directory,job_id=matches[0]
        while True:
            state=status(job_id)
            if state['state'] not in ('queued','running','paused'):break
            time.sleep(3)
        (directory/'job-status.json').write_text(json.dumps(state,indent=2)+'\n')
        if state['state']=='completed':
            try:(directory/'verification.json').write_text(json.dumps(evaluate(directory),indent=2)+'\n')
            except Exception as error:(directory/'verification-error.txt').write_text(str(error)+'\n')
        run_exit=0 if state['state']=='completed' and state.get('exit_code')==0 else 1
    else:
        out=home/('negative-'+mode+'-resume.stdout');err=home/('negative-'+mode+'-resume.stderr')
        with out.open('w') as stdout,err.open('w') as stderr:
            process=subprocess.run([sys.executable,'experiments/run_three_arm_negative_control.py',scene_id,mode,case],stdout=stdout,stderr=stderr,check=False)
        run_exit=process.returncode
        try:directory=Path(json.loads(out.read_text().splitlines()[-1])['directory']).resolve()
        except (OSError,ValueError,IndexError,KeyError) as error:
            results.append({'mode':mode,'run_exit_code':run_exit,'passed':False,'error':str(error)});continue
    verified=subprocess.run([sys.executable,'experiments/verify_three_arm_negative_control.py',str(baseline),str(directory),mode],capture_output=True,text=True,check=False)
    (directory/'negative-control-verification.json').write_text(verified.stdout)
    (directory/'negative-control-verification.stderr').write_text(verified.stderr)
    try:passed=run_exit==0 and verified.returncode==0 and bool(json.loads(verified.stdout)['passed'])
    except (ValueError,KeyError,TypeError):passed=False
    results.append({'mode':mode,'run_exit_code':run_exit,'passed':passed,'directory':str(directory)})
    tmp=home/'negative-suite-result.tmp';tmp.write_text(json.dumps({'passed':False,'baseline':str(baseline),'controls':results},indent=2)+'\n');tmp.replace(home/'negative-suite-result.json')
summary={'passed':len(results)==3 and all(x['passed'] for x in results),'baseline':str(baseline),'controls':results}
(home/'negative-suite-result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
raise SystemExit(0 if summary['passed'] else 1)
