"""Reattach to one existing simulation using its frozen package."""
import json,sys,time
from pathlib import Path
from simscene.jobs import status
from simscene.verification.case_runner import evaluate
if len(sys.argv)!=2:raise SystemExit('usage: resume_existing_probe.py RUN_DIRECTORY')
root=Path(sys.argv[1]).resolve();info=json.loads((root/'job.json').read_text())
while True:
 current=status(info['job_id'])
 if current['state'] not in ('queued','running','paused'):break
 time.sleep(3)
(root/'job-status.json').write_text(json.dumps(current,indent=2)+'\n')
if current['state']=='completed':
 try:(root/'verification.json').write_text(json.dumps(evaluate(root),indent=2)+'\n')
 except Exception as error:(root/'verification-error.txt').write_text(str(error)+'\n')
print(json.dumps({'directory':str(root),'state':current['state'],'scope':'resumed frozen diagnostic'}))
raise SystemExit(0 if current['state']=='completed' else 1)
