"""Check the frozen cabinet layout case and its additional physical evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from pxr import Usd
from simscene.evidence_integrity import verify as verify_evidence
from simscene.physics_binding import validate_asset_binding
from simscene.preparation.articulation import inspect_articulation
from simscene.recipes.cases import freeze_case
from simscene.run_integrity import verify as verify_inputs
from simscene.verification.asset_gallery import verify_run
from simscene.verification.settling import stable


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify(run):
    root = Path(__file__).resolve().parent
    run = Path(run).resolve()
    checks_path = root / 'supplemental-checks.json'
    checks = json.loads(checks_path.read_text())
    selections = json.loads((root / 'assets.lock.json').read_text())['assets']
    selection = selections['cabinet']
    result = json.loads((run / 'result.json').read_text())
    spec = json.loads((run / 'spec.json').read_text())
    case = json.loads((run / 'acceptance-case.json').read_text())
    bindings = {role: {'asset_path': spec['objects'][role]['asset_path'],
                       'asset_binding': spec['objects'][role]['asset_binding']} for role in selections}
    template = json.loads((root / 'case.json').read_text())
    expected_case = freeze_case(template, bindings, selections)['case']
    inputs, evidence, core = verify_inputs(run), verify_evidence(run), verify_run(run)
    frames = [result['initial_observation'], *result['samples']]
    parent, door = checks['cabinet_parent'], checks['cabinet_child']
    records = [frame.get('mechanisms', {}).get('cabinet', {}).get('joints', {}).get('main', {}) for frame in frames]

    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    native = all(finite(record.get('native_position')) and finite(record.get('native_velocity')) and
                 record.get('native_measurement_source') == 'PhysX_articulation_tensor_DOF_readback_SI' and
                 finite(record.get('position')) and abs(record['native_position'] - record['position']) <= .015
                 for record in records)
    initial = frames[0]['positions'][parent]
    displacements = [math.dist(initial, frame['positions'][parent]) for frame in frames]
    contacts = set()
    for frame in frames:
        for pair in frame.get('contact_pairs', []):
            actors = pair.get('actor_paths', [])
            if len(actors) == 2 and pair.get('count', 0) > 0:
                contacts.add(frozenset(actors))
    prop_bodies = [result['body_bindings'][name]['motion_body'] for name in checks['rigid_objects']]
    forbidden = [sorted(pair) for pair in contacts if door in pair and any(body in pair for body in prop_bodies)]
    keep = checks['reserved_volume']

    def intersects(a, b):
        return all(a['max'][i] > b['min'][i] and b['max'][i] > a['min'][i] for i in range(3))

    prop_clear = all(not intersects(frame['bounds'][name], keep) for frame in frames for name in checks['rigid_objects'])
    cabinet_contained = all(all(keep['min'][i] - .01 <= frame['bounds']['cabinet']['min'][i] and
                                frame['bounds']['cabinet']['max'][i] <= keep['max'][i] + .01
                                for i in range(3)) for frame in frames)
    obj = spec['objects']['cabinet']
    manifest = validate_asset_binding(obj['asset_binding'], require_dynamic=True, asset_path=obj['asset_path'])
    package = Path(obj['asset_binding']['manifest_path']).parent
    source_file = package / 'source' / selection['source_files'][0]['path']
    source = inspect_articulation(Usd.Stage.Open(str(source_file)))
    source_joint, prepared_joint = source['joint_map']['main'], result['body_bindings']['cabinet']['joints']['main']
    joint_keys = ('type', 'axis', 'limits', 'position_unit', 'native_authored_attributes',
                  'local_pos0_m', 'local_pos1_m', 'local_rot0_wxyz', 'local_rot1_wxyz')
    source_masses = sorted(item['mass_kg'] for item in source['body_map'].values() if item.get('role') == 'rigid')
    prepared_masses = sorted(item['mass_kg'] for item in manifest['body_map'].values() if item.get('role') == 'rigid')
    note = case['components'][-1]['case']['physical_model_note']
    supplemental = {
        'case_matches_frozen_example': case == expected_case,
        'requirements_pinned_in_case': ('Supplemental acceptance SHA-256: ' + sha(checks_path)) in note,
        'native_dof_readback_each_step': native,
        'cabinet_supported_by_table': frozenset((parent, checks['support_actor'])) in contacts,
        'cabinet_settled_two_seconds': stable(frames, parent, result['simulation_time_s'], 2.,
                                              checks['max_linear_speed_m_s'], checks['max_angular_speed_rad_s']),
        'cabinet_translation_within_limit': max(displacements) <= checks['max_parent_translation_m'],
        'props_outside_reserved_sweep': prop_clear,
        'cabinet_inside_reserved_volume': cabinet_contained,
        'no_door_prop_contacts': not forbidden,
        'source_file_hash_matches_lock': sha(source_file) == selection['source_sha256'],
        'native_joint_attributes_preserved': all(source_joint.get(key) == prepared_joint.get(key) for key in joint_keys),
        'native_rigid_masses_preserved': len(source_masses) == 2 and source_masses == prepared_masses,
        'one_joint_binding': len(result['body_bindings']['cabinet']['joints']) == 1,
    }
    return {'schema': 'simscene.cabinet_layout_example_check.v1', 'run': str(run),
            'passed': (inputs['passed'] and evidence['passed'] and evidence['partial'] is False and
                       core['passed'] and all(supplemental.values())),
            'input_integrity': inputs, 'evidence_integrity': evidence, 'core_verification': core,
            'supplemental': supplemental, 'max_parent_translation_m': max(displacements),
            'native_dof_range_rad': [min(record['native_position'] for record in records if finite(record.get('native_position'))),
                                     max(record['native_position'] for record in records if finite(record.get('native_position')))],
            'scope': 'One frozen layout and recorded run; not a general asset or structural certification.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--output', required=True, help='new JSON report path')
    args = parser.parse_args()
    report = verify(args.run)
    with Path(args.output).open('x', encoding='utf8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': report['passed'], 'output': args.output}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
