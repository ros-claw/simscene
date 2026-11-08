"""Compact diagnosis from an existing verifier report, not raw trajectories."""
import argparse
import json
from pathlib import Path
import sys
import _bootstrap
from simscene.diagnostics import write_diagnosis
p = argparse.ArgumentParser(); p.add_argument('--report', required=True); p.add_argument('--case', required=True); p.add_argument('--output', required=True)
a = p.parse_args(); print(json.dumps(write_diagnosis(a.report, a.case, a.output), ensure_ascii=False))
