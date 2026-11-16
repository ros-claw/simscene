#!/usr/bin/env python3
"""Check a new ArtVIP door run without changing its physics or evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from simscene.physics_binding import validate_asset_binding
from simscene.preparation.articulation import verify_source_graph
from simscene.recipes.cases import freeze_case
from simscene.verification.articulated_asset_smoke import verify_run

HERE=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(run):
    run=Path(run).resolve()
    result=json.loads((run/'result.json').read_text())
    spec=json.loads((run/'spec.json').read_text())
    frozen=json.loads((run/'acceptance-case.json').read_text())
    template=json.loads((HERE/'case.json').read_text())
    lock=json.loads((HERE/'assets.lock.json').read_text())
    supplement=json.loads((HERE/'supplement.json').read_text())
    obj=spec['objects']['door']
    binding={'asset_path':obj['asset_path'],'asset_binding':obj['asset_binding']}
    expected=freeze_case(template,{'door':binding},lock['assets'])['case']
    core=verify_run(run)
    manifest=validate_asset_binding(obj['asset_binding'],require_dynamic=True,asset_path=obj['asset_path'])
    package=Path(obj['asset_binding']['manifest_path']).parent
    source_graph=verify_source_graph(package,manifest)
    frames=[result['initial_observation']]+result['samples']
    records=[frame['mechanisms']['door']['joints']['main'] for frame in frames]
    def finite(value):return type(value) in (int,float) and math.isfinite(value)
    native=all(finite(r.get('native_position')) and finite(r.get('native_velocity'))
        and r.get('native_measurement_source')=='PhysX_articulation_tensor_DOF_readback_SI'
        and abs(r['native_position']-r['position'])<=supplement['max_native_frame_disagreement_rad']
        for r in records)
    mapped=result['body_bindings']['door'];parent=mapped['joints']['main']['parent_body']
    parent_start=frames[0]['positions'][parent]
    parent_drift=max(math.dist(parent_start,frame['positions'][parent]) for frame in frames)
    properties=result['mechanism_configuration']['mass_properties_by_prim_path']
    mass_checks=[]
    for local_id,expected_mass in supplement['mass_kg'].items():
        body=mapped['bodies'][local_id]['motion_body'];mass=properties[body]
        mass_checks.append(abs(mass['mass_kg']-expected_mass)<1e-5
            and mass.get('mass_provenance')=='explicit_experimental_assumption_overrides_source_material_density'
            and mass.get('native_repairs_ref',{}).get('manifest_sha256')==obj['asset_binding']['manifest_sha256'])
    checks={'frozen_case_matches_template':frozen==expected,
        'supplement_hash_pinned_in_case':sha(HERE/'supplement.json') in frozen['physical_model_note'],
        'core_physical_and_integrity_checks':core['passed'],
        'source_graph_and_collision_replayed':source_graph,
        'source_sha256_matches_example':manifest['source_sha256']==supplement['source_sha256'],
        'source_material_overrides_explicit':len(manifest['physics_repairs']['material_density_overrides'])==supplement['source_material_density_override_count'],
        'all_native_dof_readings_present_and_consistent':native,
        'parent_drift_within_limit':parent_drift<=supplement['max_fixed_parent_translation_m'],
        'cooked_masses_and_assumptions_match':all(mass_checks),
        'complete_physics_steps':result['actual_physics_steps']==supplement['physics_steps']}
    return {'schema':'simscene.artvip_door_example_check.v1','run':str(run),'checks':checks,
        'passed':all(checks.values()),'core_verification':core,'native_sample_count':len(records),
        'observed_joint_range_rad':[min(r['position'] for r in records),max(r['position'] for r in records)],
        'max_fixed_parent_translation_m':parent_drift,
        'scope':'One selected object, one scheduled drive, and explicitly experimental derived physics; not a general dataset certification.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();report=check(args.run)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf8') as stream:
        json.dump(report,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'passed':report['passed'],'checks':report['checks'],'report':str(output)},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
