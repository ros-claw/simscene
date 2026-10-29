"""Gate a presentation run on an online robot probe and a feeder diagnostic."""
import json, os, subprocess, sys, time
from pathlib import Path
from simscene.run_integrity import verify as verify_inputs
from simscene.evidence_integrity import verify as verify_outputs
if len(sys.argv)!=6:
    raise SystemExit('usage: run_presentation_after_probes.py ONLINE_RUN FEEDER_RUN RECOVERY_RUN HOME CASE')
online,feeder,recovery,home,case=map(lambda x:Path(x).resolve(),sys.argv[1:])
(home/'presentation-gate-policy.json').write_text(json.dumps({'online_fixed_case_and_locks':True,
  'feeder_steps':15000,'minimum_archived_total':10,'minimum_green':2,'minimum_blue':2,
  'recovery_tray_physical_probe':True,
  'scope':'diagnostic gate only; the presentation still requires its own complete 18-object case'},indent=2)+'\n')
for directory in (online,feeder,recovery):
    while not (directory/'job-status.json').is_file():time.sleep(5)
    status=json.loads((directory/'job-status.json').read_text())
    if status.get('state')=='completed':
        deadline=time.monotonic()+300
        expected='recovery-verification.json' if directory==recovery else 'verification.json'
        while not (directory/expected).is_file() and time.monotonic()<deadline:time.sleep(1)
online_status=json.loads((online/'job-status.json').read_text())
feeder_status=json.loads((feeder/'job-status.json').read_text())
recovery_status=json.loads((recovery/'job-status.json').read_text())
recovery_report=json.loads((recovery/'recovery-verification.json').read_text()) if (recovery/'recovery-verification.json').is_file() else {}
report=json.loads((online/'verification.json').read_text()) if (online/'verification.json').is_file() else {}
observation=json.loads((feeder/'latest-observation.json').read_text()) if (feeder/'latest-observation.json').is_file() else {}
counts=observation.get('verified_counts',{});by_class=counts.get('by_class',{})
try:inputs=verify_inputs(online);outputs=verify_outputs(online)
except Exception as e:inputs={'passed':False,'error':repr(e)};outputs={'passed':False,'partial':True}
checks={'online_completed':online_status.get('state')=='completed' and online_status.get('exit_code')==0 and online_status.get('exit_code_inferred') is False,
  'online_fixed_case':report.get('passed') is True,'online_input_lock':inputs.get('passed') is True,
  'online_output_lock':outputs.get('passed') is True and not outputs.get('partial'),
  'feeder_completed':feeder_status.get('state')=='completed' and observation.get('physics_steps')==15000,
  'feeder_total':counts.get('total',0)>=10,'feeder_green':by_class.get('green',0)>=2,'feeder_blue':by_class.get('blue',0)>=2,
  'recovery_tray':recovery_status.get('state')=='completed' and recovery_status.get('exit_code')==0 and
      recovery_status.get('exit_code_inferred') is False and recovery_report.get('passed') is True}
gate={'checks':checks,'feeder_counts':counts,'passed':all(checks.values())}
(home/'presentation-gate.json').write_text(json.dumps(gate,indent=2)+'\n');print(json.dumps(gate),flush=True)
if not gate['passed']:raise SystemExit(1)
env=dict(os.environ,SIMSCENE_HOME=str(home),SIMSCENE_RECOVERY_TRAY_SCENE=str(recovery.parent.parent/'recovery.json'))
with (home/'presentation.stdout').open('w') as out,(home/'presentation.stderr').open('w') as err:
    run=subprocess.run([sys.executable,'experiments/run_three_arm_presentation.py','stream',str(case),'-.016'],env=env,stdout=out,stderr=err,check=False)
(home/'presentation-exit.json').write_text(json.dumps({'exit_code':run.returncode},indent=2)+'\n')
raise SystemExit(run.returncode)
