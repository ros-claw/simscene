"""Run the three real negative controls after the frozen seed-17 baseline.

The baseline suite and controls use the cooperative GPU queue. This supervisor
records failures and never treats a crashed run as a successful control.
"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv) != 3:
    raise SystemExit('usage: run_negative_suite.py SCENE_ID CASE_JSON')
scene_id, case = sys.argv[1:]
root = Path(os.environ['SIMSCENE_HOME']).resolve()
frozen=root/'negative-frozen'
names=('run_three_arm_negative_control.py','verify_three_arm_negative_control.py')
if not frozen.exists():
    frozen.mkdir()
    for name in names:shutil.copyfile(Path('experiments')/name,frozen/name)
    (frozen/'sha256.json').write_text(json.dumps({name:hashlib.sha256((frozen/name).read_bytes()).hexdigest() for name in names},indent=2)+'\n')
hashes=json.loads((frozen/'sha256.json').read_text())
def verify_frozen():
    if set(hashes)!=set(names) or any(hashlib.sha256((frozen/name).read_bytes()).hexdigest()!=hashes[name] for name in names):
        raise ValueError('frozen negative-control code changed')
verify_frozen()
progress = root/'formal-suite-progress.json'
while True:
    try:
        records = json.loads(progress.read_text())
        break
    except (OSError, ValueError):
        time.sleep(5)
base = next((r for r in records if r.get('seed') == 17), None)
if not base or base.get('state') != 'completed':
    (root/'negative-suite-result.json').write_text(json.dumps({'passed':False,'reason':'baseline seed 17 did not complete','baseline':base},indent=2)+'\n')
    raise SystemExit(1)
positive = Path(base['directory']).resolve()
if positive.parent != (root/'runs').resolve():
    raise SystemExit('baseline directory is outside this scene store')
from simscene.verification.case_runner import evaluate
try:
    report = evaluate(positive)
    if report.get('passed') is not True:
        raise ValueError('baseline did not pass its full frozen physical case')
    if not all(report['objects'][part]['passed'] for part in ('part0000','part0002')):
        raise ValueError('required blue and red baseline picks did not both pass')
except (OSError,ValueError,KeyError,TypeError) as error:
    (root/'negative-suite-result.json').write_text(json.dumps({'passed':False,'reason':str(error),'baseline':str(positive)},indent=2)+'\n')
    raise SystemExit(1)
out = []
for mode in ('disable_drive','disable_suction','stop_belt'):
    verify_frozen()
    log = root/('negative-'+mode+'.stdout'); err = root/('negative-'+mode+'.stderr')
    with log.open('w') as stdout, err.open('w') as stderr:
        process = subprocess.run([sys.executable,str(frozen/'run_three_arm_negative_control.py'),scene_id,mode,case],stdout=stdout,stderr=stderr,check=False)
    item = {'mode':mode,'run_exit_code':process.returncode,'passed':False}
    try:
        data = json.loads(log.read_text().splitlines()[-1]); directory = Path(data['directory']).resolve()
        if directory.parent != (root/'runs').resolve():raise ValueError('control directory outside run store')
        item['directory']=str(directory)
        verify_frozen()
        verified = subprocess.run([sys.executable,str(frozen/'verify_three_arm_negative_control.py'),str(positive),str(directory),mode],capture_output=True,text=True,check=False)
        (directory/'negative-control-verification.json').write_text(verified.stdout)
        (directory/'negative-control-verification.stderr').write_text(verified.stderr)
        item['passed'] = process.returncode == 0 and verified.returncode == 0 and bool(json.loads(verified.stdout)['passed'])
    except (OSError,ValueError,KeyError,IndexError,TypeError) as error:
        item['error']=str(error)
    out.append(item)
    (root/'negative-suite-result.json').write_text(json.dumps({'passed':False,'baseline':str(positive),'controls':out},indent=2)+'\n')
result={'passed':len(out)==3 and all(item['passed'] for item in out),'baseline':str(positive),'controls':out}
(root/'negative-suite-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['passed'] else 1)
