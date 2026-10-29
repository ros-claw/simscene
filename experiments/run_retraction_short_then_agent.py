"""Check the first simultaneous cycle before a full retimed diagnostic."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from simscene.jobs import status, verify_evidence, verify_lock, verify_task

base = Path('/code/rosclaw/simscene')
short = Path(os.environ['SIMSCENE_HOME'])
full = Path('/tmp/simscene-synchronize-diagnostic-v30d')
suite = Path('/tmp/simscene-agent-v30d-suite')
archive = base/'evidence/agent-v30d-short'
job = json.loads((short/'launched.json').read_text())
progress = short/'short-probe-progress.json'

def write(value):
    progress.write_text(json.dumps(value, indent=2)+'\n')

write({'state': 'running', 'job': job})
while True:
    state = status(job['job_id'])
    if state['state'] not in ('running', 'queued', 'paused', 'stalled'):
        break
    time.sleep(10)
checks = {'completed': state['state'] == 'completed',
          'observed_exit_zero': state.get('exit_code') == 0 and state.get('exit_code_inferred') is False}
report = None
if checks['completed']:
    try:
        report = verify_task(job['job_id'])
        run = json.loads((short/'runs'/job['run_id']/'result.json').read_text())
        checks.update({'first_three_correct': report['ledger']['correct'] >= 3,
                       'three_arm_overlap': bool(report['parallel_steps'] and report['parallel_steps'][1]-report['parallel_steps'][0] >= 60),
                       'no_robot_errors': all(not f.get('sequence_error') for f in run['followers'].values()),
                       'no_forbidden_environment': report['checks']['no_forbidden_robot_environment_contact'],
                       'no_arm_arm_contact': report['checks']['no_arm_arm_contact'],
                       'no_wrong_robot_contact': report['checks']['no_wrong_robot_contact'],
                       # The full nine-item audit correctly reports incomplete
                       # shape coverage here because four later parts have not
                       # spawned. Treat this only as a provisional first-cycle
                       # diagnostic; the full run must pass the unmodified audit.
                       'partial_collision_observations': all(report['collision_audit']['checks'][name] for name in
                           ('case_policy_matches_scene', 'self_collision_enabled', 'each_step_queried',
                            'queries_complete', 'contact_reporting_complete', 'no_unexpected_overlaps_or_contacts')),
                       'input_lock': verify_lock(job['job_id']).get('passed') is True,
                       'output_lock': verify_evidence(job['job_id']).get('passed') is True})
    except Exception as error:
        checks['verification_completed'] = False
        report = {'error': str(error)}
passed = all(checks.values())
(short/'short-probe-result.json').write_text(json.dumps({'passed': passed, 'checks': checks, 'report': report,
    'scope': 'first-cycle diagnostic only; collision shape coverage and full nine-item acceptance remain required'}, indent=2)+'\n')
write({'state': 'passed' if passed else 'requires_investigation', 'checks': checks})
shutil.copytree(short, archive)
if not passed:
    raise SystemExit(1)
env = dict(os.environ, SIMSCENE_HOME=str(full), PYTHONPATH=str(base/'src'))
env.pop('SIMSCENE_PROBE_STEPS', None)
with (Path('/tmp')/'simscene-synchronize-v30d-launch.log').open('w') as log:
    started = subprocess.run([sys.executable, str(base/'experiments/probe_synchronize_agent_scene.py')], cwd=base, env=env, stdout=log, stderr=log)
if started.returncode:
    write({'state': 'full_probe_start_failed', 'exit_code': started.returncode})
    raise SystemExit(started.returncode)
env['PYTHONPATH'] = '/home/dell/.local/share/simscene/plugins/simscene-v30/server/vendor'
with (Path('/tmp')/'simscene-agent-v30d-supervisor.log').open('w') as log, (Path('/tmp')/'simscene-agent-v30d-archive.log').open('w') as archive_log:
    watcher = subprocess.Popen([sys.executable, str(base/'experiments/archive_v30_agent.py'), str(suite), str(full),
        str(base/'evidence/agent-v30d-suite')], cwd=base, stdout=archive_log, stderr=archive_log, start_new_session=True)
    result = subprocess.run([sys.executable, str(base/'experiments/run_v30_agent_after_synchronization.py'), str(suite)],
                            cwd=base, env=env, stdout=log, stderr=log)
    if result.returncode and not (suite/'gate-progress.json').exists():
        watcher.terminate()
write({'state': 'agent_suite_complete' if result.returncode == 0 else 'agent_suite_requires_investigation',
       'supervisor_exit': result.returncode, 'archive_pid': watcher.pid})
raise SystemExit(result.returncode)
