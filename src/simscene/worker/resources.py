"""Best-effort per-worker resource samples; unavailable values remain null."""
import os
import resource
import subprocess
import time
from pathlib import Path


def sample(physics_steps, started):
    rss=None
    try:
        resident=int(Path('/proc/self/statm').read_text().split()[1])
        rss=resident*os.sysconf('SC_PAGE_SIZE')
    except (OSError,ValueError,IndexError):
        pass
    gpu_bytes=None
    try:
        result=subprocess.run(['nvidia-smi','--query-compute-apps=pid,used_gpu_memory',
                               '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,check=True)
        entries=[]
        for line in result.stdout.splitlines():
            parts=[part.strip() for part in line.split(',')]
            if len(parts)==2 and int(parts[0])==os.getpid() and parts[1].isdigit():
                entries.append(int(parts[1])*1024*1024)
        if entries:gpu_bytes=sum(entries)
    except (OSError,ValueError,subprocess.SubprocessError):
        pass
    return {'physics_steps':physics_steps,'wall_time_s':time.monotonic()-started,
            'rss_bytes':rss,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'gpu_process_memory_bytes':gpu_bytes}
