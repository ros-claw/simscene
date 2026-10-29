"""Copy finished v30 evaluation records without changing live sessions."""
import json
from pathlib import Path
import shutil
import sys
import time

source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/simscene-agent-v30-suite')
probe = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/tmp/simscene-synchronize-diagnostic-v30')
out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path('/code/rosclaw/simscene/evidence/agent-v30-suite')
out.mkdir(parents=True, exist_ok=False)
copied = set()

def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}

while True:
    gate = read(source/'gate-progress.json')
    agent = read(source/'agent-acceptance/progress.json')
    if (source/'synchronization-probe-result.json').is_file() and 'probe' not in copied:
        target = out/'synchronization-probe'
        shutil.copytree(probe, target)
        shutil.copy2(source/'synchronization-probe-result.json', out/'synchronization-probe-result.json')
        copied.add('probe')
    for session in agent.get('sessions', []):
        name = session.get('name')
        path = source/'agent-acceptance'/str(name)
        if name and name not in copied and path.is_dir():
            shutil.copytree(path, out/name)
            copied.add(name)
    for name in ('gate-progress.json', 'agent-suite.stdout', 'agent-suite.stderr', 'agent-supervisor-frozen.py'):
        if (source/name).is_file():
            shutil.copy2(source/name, out/name)
    if (source/'agent-acceptance/progress.json').is_file():
        shutil.copy2(source/'agent-acceptance/progress.json', out/'agent-progress.json')
    if gate.get('state') in ('synchronization_probe_failed', 'agent_suite_complete', 'agent_suite_requires_investigation'):
        break
    time.sleep(10)
