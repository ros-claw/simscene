"""Wait for one persisted job using its existing host-side state directory."""
import argparse
import json
from pathlib import Path
import sys
import _bootstrap
from simscene.workflows import wait_job
p = argparse.ArgumentParser(); p.add_argument('--job', required=True); p.add_argument('--receipt', required=True); p.add_argument('--timeout-s', type=float, default=1800)
a = p.parse_args(); print(json.dumps(wait_job(a.job, a.receipt, a.timeout_s), ensure_ascii=False))
