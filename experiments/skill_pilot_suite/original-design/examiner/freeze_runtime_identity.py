#!/usr/bin/env python3
"""One-time examiner-side identity freeze from a generic completed smoke run.

Not a task authoring/scoring action. Must run before any formal prompt release.
The destination is created exclusively; no overwrite or in-place edit is allowed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from score import PAIRED_FIELDS,frozen_design,read,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-run',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--candidate-freeze',required=True,help='Preexisting complete A/B software/package/model/budget manifest')
    args=parser.parse_args()
    if not frozen_design()['passed']:raise ValueError('design or generic readers changed')
    from simscene.run_integrity import verify as inputs
    from simscene.evidence_integrity import verify as outputs
    root=Path(args.smoke_run).expanduser().resolve()
    ip,op=inputs(root),outputs(root)
    if not ip['passed'] or not op['passed'] or op.get('partial') is not False:raise ValueError('generic smoke run must have complete intact sealed evidence')
    lock=read(root/'run-lock.json');result=read(root/'result.json');spec=read(root/'spec.json')
    if any(n in spec.get('objects',{}) for n in ('driver','payload','lever','hinge','ramp','deck')):raise ValueError('smoke must be an unrelated generic bench, not a formal trial')
    if result.get('actual_physics_steps')!=result.get('requested_physics_steps') or result.get('task_status')=='failed':raise ValueError('smoke did not finish')
    if not lock.get('worker_code_sha256') or not ip.get('checks',{}).get('worker_code_snapshot'):raise ValueError('missing real worker snapshot')
    if not all(k in lock for k in PAIRED_FIELDS):raise ValueError('runtime identity incomplete')
    candidate=Path(args.candidate_freeze).resolve()
    record={'schema':'simscene.pilot_runtime_identity.v1','approved_manifest_fields':{k:lock[k] for k in PAIRED_FIELDS},
            'generic_smoke_run':str(root),'generic_smoke_run_lock_sha256':sha(root/'run-lock.json'),
            'candidate_freeze':str(candidate),'candidate_freeze_sha256':sha(candidate),
            'design_freeze_sha256':sha(Path(__file__).resolve().parents[1]/'DESIGN-FREEZE.json')}
    fd=os.open(Path(args.out).resolve(),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
    with os.fdopen(fd,'w') as file:json.dump(record,file,ensure_ascii=False,indent=2);file.write('\n')
    print(json.dumps({'created':str(Path(args.out).resolve()),'sha256':sha(args.out),'scope':'runtime identity only; no task physics acceptance'},ensure_ascii=False))


if __name__=='__main__':
    main()
