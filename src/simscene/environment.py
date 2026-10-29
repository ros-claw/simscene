"""Inspect the configured environment without starting a simulator."""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from .assets import USDSearch

def probe():
    from .settings import get
    executable = get('isaac_python')
    runtime = {'configured_python':executable, 'available':False, 'version':None}
    if executable:
        path = Path(executable).expanduser().resolve()
        runtime['available'] = path.is_file() and os.access(path, os.X_OK)
        version = path.parent / 'VERSION'
        if version.is_file(): runtime['version'] = version.read_text().strip()
    candidates=[]
    for base in [Path('/data/omniverse'),Path('~/.local/share/ov/pkg').expanduser(),Path('/opt')]:
        if not base.is_dir():continue
        for directory in sorted(base.glob('isaac-sim*')):
            python=directory/'python.sh'
            if python.is_file() and os.access(python,os.X_OK):
                version=directory/'VERSION'
                candidates.append({'python':str(python.resolve()),'version':version.read_text().strip() if version.is_file() else None})
    standalone=Path('/isaac-sim/python.sh')
    if standalone.is_file() and os.access(standalone,os.X_OK):candidates.append({'python':str(standalone.resolve()),'version':None})
    runtime['candidates']=candidates
    gpu = {'available':False, 'devices':[], 'error':None}
    tool = shutil.which('nvidia-smi')
    if tool:
        try:
            result = subprocess.run([tool, '--query-gpu=index,name,driver_version,memory.total,memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5, check=True)
            gpu['available'] = True
            gpu['devices'] = [line.split(', ') for line in result.stdout.splitlines()]
        except (subprocess.SubprocessError, OSError) as error:
            gpu['error'] = str(error)
    return {'python':sys.version, 'platform':platform.platform(), 'gpu':gpu, 'isaac':runtime,
            'usd_search_url':USDSearch().base_url, 'simulation':'experimental',
            'robot_profiles_verified':[], 'agent_clients_verified':[]}
