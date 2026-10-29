"""Gate fresh v30 agent sessions on the observed-timing physics probe.

The v29 formal physical suite is reused only for its unchanged Isaac worker;
the new timing planner has its own pre-frozen physical diagnostic. Each
agent evaluator separately freezes its case, checker, package and skill.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from simscene.jobs import status, verify_evidence, verify_lock, verify_task

base = Path('/code/rosclaw/simscene')
probe = Path(os.environ['SIMSCENE_HOME'])
suite = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/simscene-agent-v30-suite')
original = Path('/tmp/simscene-formal-v19-camera-warmup')
package = Path('/home/dell/.local/share/simscene/plugins/simscene-v30')
suite.mkdir(parents=True, exist_ok=False)
progress = suite/'gate-progress.json'

def write(data):
    temp = progress.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2)+'\n')
    temp.replace(progress)

job = json.loads((probe/'launched.json').read_text())
write({'state': 'waiting_for_synchronization_probe', 'job': job})
while True:
    current = status(job['job_id'])
    if current['state'] not in ('queued', 'running', 'paused', 'stalled'):
        break
    time.sleep(10)
checks = {'completed': current['state'] == 'completed',
          'observed_exit_zero': current.get('exit_code') == 0 and current.get('exit_code_inferred') is False}
report = None
if checks['completed']:
    try:
        report = verify_task(job['job_id'])
        checks.update({'physical_case': report.get('passed') is True,
                       'three_arm_overlap': bool(report.get('parallel_steps') and
                                                 report['parallel_steps'][1]-report['parallel_steps'][0] >= 60),
                       'input_lock': verify_lock(job['job_id']).get('passed') is True,
                       'output_lock': verify_evidence(job['job_id']).get('passed') is True})
    except Exception as error:
        checks['verification_completed'] = False
        report = {'error': str(error)}
result = {'passed': all(checks.values()), 'checks': checks, 'status': current,
          'report': report, 'scope': 'retiming of a previous agent scene; not a fresh-agent acceptance'}
(suite/'synchronization-probe-result.json').write_text(json.dumps(result, indent=2)+'\n')
if not result['passed']:
    write({'state': 'synchronization_probe_failed', 'checks': checks})
    raise SystemExit(1)
for name in ('formal-suite-verification.json', 'negative-suite-result.json', 'combined-result.json'):
    shutil.copyfile(original/name, suite/name)
supervisor = base/'experiments/run_agent_acceptance_after_suite.py'
shutil.copyfile(supervisor, suite/'agent-supervisor-frozen.py')
write({'state': 'running_fresh_agent_suite', 'synchronization_probe_passed': True})
args = [sys.executable, str(suite/'agent-supervisor-frozen.py'), str(package), str(suite),
        '/tmp/simscene-presentation-v26-lift-settle/presentation.stdout',
        '/tmp/simscene-feeder-probe-v16/probe.log']
with (suite/'agent-suite.stdout').open('w') as out, (suite/'agent-suite.stderr').open('w') as err:
    process = subprocess.run(args, cwd=base, env=os.environ.copy(), stdout=out, stderr=err)
write({'state': 'agent_suite_complete' if process.returncode == 0 else 'agent_suite_requires_investigation',
       'agent_supervisor_exit': process.returncode})
raise SystemExit(process.returncode)
