"""Wait for a reattached real worker and check its recorded process exit."""
import json,sys,time
from pathlib import Path
from simscene.jobs import status
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs
if len(sys.argv)!=2:raise SystemExit('usage: verify_exit_recovery_probe.py JOB_JSON')
job=json.loads(Path(sys.argv[1]).read_text());root=Path(sys.argv[1]).parent/'runs'/job['run_id']
while True:
 s=status(job['job_id'])
 if s['state'] not in ('queued','running','paused'):break
 time.sleep(3)
checks={'completed':s['state']=='completed','actual_exit_zero':s.get('exit_code')==0 and s.get('exit_code_inferred') is False,
        'input_integrity':verify_inputs(root)['passed'],'output_integrity':verify_outputs(root)['passed'],
        'camera_observed':bool((s.get('result') or {}).get('images'))}
report={'passed':all(checks.values()),'checks':checks,'status':s,'scope':'real reattachment and durable child exit; no robot manipulation claim'}
(root/'recovery-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':report['passed'],'checks':checks,'directory':str(root)}))
raise SystemExit(0 if report['passed'] else 1)
