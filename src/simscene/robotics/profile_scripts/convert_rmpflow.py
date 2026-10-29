"""Adapt a local Lula RMPflow YAML to a cuMotion 2.0 diagnostic candidate."""
import argparse
from pathlib import Path
import yaml
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
a=p.parse_args()
source=yaml.safe_load(Path(a.source).read_text())
source={'format':'rmpflow','api_version':2.0,**source}
source['body_capsules']=source.pop('body_cylinders',[])
for block in source.get('rmp_params',{}).values():
    block.pop('xi_estimator_gate_std_dev',None)
Path(a.output).write_text('# Derived from NVIDIA Corporation source: SPDX-License-Identifier: Apache-2.0\n# Experimental diagnostic configuration; not safety-validated.\n'+yaml.safe_dump(source,sort_keys=False))
