"""Archive finished run evidence without claiming that it is a portable replay."""
import json
import shutil
import sys
import time
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit('usage: archive_formal_suite.py SUITE_HOME OUTPUT_DIRECTORY')
home, out = (Path(x).resolve() for x in sys.argv[1:])
seen = set()

def read(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default

def copy_run(path):
    if not path.is_dir() or path.name in seen or not (path/'job-status.json').is_file():
        return
    out.mkdir(parents=True, exist_ok=True)
    (out/'runs').mkdir(exist_ok=True)
    target = out/'runs'/path.name
    if not target.exists():
        shutil.copytree(path, target)
    seen.add(path.name)
    print('archived run', path.name, flush=True)

while True:
    for item in read(home/'formal-suite-progress.json', []):
        if item.get('directory'):
            copy_run(Path(item['directory']))
    for item in read(home/'negative-suite-result.json', {}).get('controls', []):
        if item.get('directory'):
            copy_run(Path(item['directory']))
    progress = read(home/'agent-acceptance'/'progress.json', {})
    state = progress.get('state', '')
    terminal = state in ('complete', 'requires_investigation') or state.startswith('blocked_by_')
    if terminal and (home/'suite.stdout').exists() and not (home/'combined-result.json').exists():
        time.sleep(10)
        continue
    if terminal:
        out.mkdir(parents=True, exist_ok=True)
        for name in ('case.json', 'case-before-feeder.json', 'suite-feeder-plan.json',
                     'formal-suite-progress.json', 'formal-suite-verification.json',
                     'formal-suite-error.txt', 'combined-result.json', 'negative-suite-result.json',
                     'probe-gate.json', 'supervisor-sha256.txt', 'gate-frozen-v2.py',
                     'agent-supervisor-frozen.py', 'gate-v2.log', 'agent-v25.log', 'agent-v26.log', 'agent-v28.log', 'agent-v29.log',
                     'suite.stdout', 'suite.stderr', 'negative.stdout', 'negative.stderr'):
            source = home/name
            if source.is_file():
                shutil.copy2(source, out/name)
        for name in ('suite-frozen', 'negative-frozen', 'agent-acceptance'):
            source = home/name
            if source.is_dir() and not (out/name).exists():
                shutil.copytree(source, out/name)
        for item in read(home/'negative-suite-result.json', {}).get('controls', []):
            if item.get('directory'):
                copy_run(Path(item['directory']))
        print('terminal', state, flush=True)
        break
    time.sleep(10)
