"""Record a configured scene with its pinned physical case using existing jobs."""
import argparse,json,time
from pathlib import Path
from simscene.jobs import start,status
from simscene.verification.case_runner import evaluate
from simscene.run_integrity import verify as inputs
from simscene.evidence_integrity import verify as outputs
p=argparse.ArgumentParser();p.add_argument('scene_id');p.add_argument('case');p.add_argument('--steps',type=int,required=True);p.add_argument('--seed',type=int,default=42);p.add_argument('--output',required=True);p.add_argument('--request-id',required=True);p.add_argument('--archive',action='store_true')
a=p.parse_args();root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
job=start(a.scene_id,a.steps,a.seed,case_path=a.case,archive_verified_objects=a.archive,request_id=a.request_id);(root/'job.json').write_text(json.dumps(job,indent=2));print(job,flush=True);last=None
while True:
 state=status(job['job_id']);step=(state.get('progress') or {}).get('physics_steps',0);marker=(state['state'],step//600)
 if marker!=last:print(json.dumps({'state':state['state'],'step':step}),flush=True);last=marker
 # A stalled worker is still alive; retain its original job and await exit.
 if state['state'] not in ('queued','running','paused','stalled'):break
 time.sleep(1)
(root/'status.json').write_text(json.dumps(state,indent=2));report={}
if state['state']=='completed':
 run=Path(state['result_file']).parent;report={'physical':evaluate(run),'inputs':inputs(run),'outputs':outputs(run)};(root/'verification.json').write_text(json.dumps(report,indent=2));(run/'verification.json').write_text(json.dumps(report['physical'],indent=2))
passed=state['state']=='completed' and all(r.get('passed') is True for r in report.values()) and bool(report)
print(json.dumps({'state':state['state'],'passed':passed,'directory':str(Path(state['result_file']).parent) if state.get('result_file') else None}),flush=True)
raise SystemExit(0 if passed else 1)
