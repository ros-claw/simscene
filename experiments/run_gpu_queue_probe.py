"""Exercise two real Isaac jobs and an idempotent retry on one GPU host."""
import json
import time
from pathlib import Path
from simscene.scene import SceneStore
from simscene.jobs import start,status
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs

store=SceneStore();scene=store.open('queue_probe')
if scene['revision'] or scene['objects']:raise SystemExit('use a fresh SIMSCENE_HOME')
store.apply('queue_probe',0,'scene',[{'op':'add','id':'floor','object':{'kind':'box','position':[0,0,-.05],'size':[2,2,.1],'collision':True}},
                                   {'op':'add','id':'cube','object':{'kind':'box','position':[0,0,.5],'size':[.1,.1,.1],'dynamic':True}}])
first=start('queue_probe',120,17,request_id='queue_probe_first')
again=start('queue_probe',120,17,request_id='queue_probe_first')
second=start('queue_probe',120,29,request_id='queue_probe_second')
history=[];finished={}
while len(finished)<2:
    row={'time_unix':time.time()}
    for label,job in [('first',first),('second',second)]:
        current=status(job['job_id']);row[label]=current['state']
        if current['state'] in ('completed','failed','cancelled','stalled'):finished[label]=current
    history.append(row)
    if any(value['state'] in ('failed','cancelled','stalled') for value in finished.values()):break
    time.sleep(1)
root=store.path
paths={name:root/'runs'/job['run_id'] for name,job in [('first',first),('second',second)]}
for label,data in finished.items():
    (paths[label]/'job-status.json').write_text(json.dumps(data,indent=2)+'\n')
states={name:json.loads((path/'gpu-queue.json').read_text()) for name,path in paths.items()}
checks={'same_id_for_retry':again['job_id']==first['job_id'] and again['run_id']==first['run_id'] and again.get('replayed') is True,
        'second_observed_queued':any(row['second']=='queued' for row in history),
        'both_completed':len(finished)==2 and all(value['state']=='completed' and value.get('exit_code')==0 for value in finished.values()),
        'second_started_after_first_result':(paths['first']/'result.json').is_file() and states['second'].get('started_unix_ns',0)>=(paths['first']/'result.json').stat().st_mtime_ns,
        'inputs_intact':all(verify_inputs(path)['passed'] for path in paths.values()),
        'outputs_intact':all(verify_outputs(path)['passed'] for path in paths.values())}
report={'passed':all(checks.values()),'checks':checks,'runs':{name:str(path) for name,path in paths.items()},'history':history,
        'scope':'real Isaac queue and retry behavior; not a robot or scene acceptance test'}
(root/'queue-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2));raise SystemExit(0 if report['passed'] else 1)
