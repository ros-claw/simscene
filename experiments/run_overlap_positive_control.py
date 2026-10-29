"""Inject a physical obstacle at the Franka base to check overlap reporting."""
import json
import runpy
import sys
import tempfile
from pathlib import Path

if len(sys.argv)!=2:raise SystemExit('usage: run_overlap_positive_control.py SCENE_SPEC_JSON')
source=json.load(open(sys.argv[1]))
if 'diag_probe' in source['objects']:raise ValueError('diagnostic ID already exists')
source['objects']['diag_probe']={'kind':'box','position':[2,-.05,.07],'size':[.4,.4,.14],'collision':True}
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'scene.json';path.write_text(json.dumps(source))
    sys.argv=['run_overlap_diagnostic.py',str(path)]
    runpy.run_path(str(Path(__file__).with_name('run_overlap_diagnostic.py')),run_name='__main__')
