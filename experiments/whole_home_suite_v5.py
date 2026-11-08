"""Read-only orchestration of frozen full-house repeats and interventions.

This external examiner never launches jobs or exports/repairs a project. Root
provides the independent exported-project preflight; the replay must still
pass the identical physics/fidelity contract from a distinct new directory.
"""
import argparse
import copy
import datetime
import gc
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from simscene import passive

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import whole_home_fidelity_v5 as f

SCHEMA = 'simscene.whole_home_suite.v3'


def _load(path):
    return json.loads(Path(path).read_text())


def _date(value):
    result = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    f.require(result.tzinfo is not None, 'timezone-aware freeze/run dates required')
    return result


def verify_freeze(path, contract_path, review_path, run_directory, additional_files=()):
    record = _load(path)
    f.require(record.get('schema') == 'simscene.whole_home_examiner_freeze.v1', 'independent examiner freeze required')
    pinned = record.get('files_sha256', {})
    for file in (Path(contract_path), Path(review_path), Path(f.__file__), Path(__file__), *[Path(v) for v in additional_files]):
        f.require(pinned.get(str(file.resolve())) == f.sha(file), 'supplemental freeze omits/changes '+str(file))
    lock = _load(Path(run_directory)/'run-lock.json')
    f.require(_date(record['frozen_at_utc']) < _date(lock['created_at_utc']), 'freeze must precede formal job snapshot')
    return {'passed': True, 'freeze_sha256': f.sha(path), 'frozen_at_utc': record['frozen_at_utc'], 'job_created_at_utc': lock['created_at_utc'],
            'scope': 'Recorded local chronology and exact files; not an external timestamp signature.'}


def consecutive_three(selected, ledger):
    chosen = [str(Path(value).resolve()) for value in selected]
    attempts = [str(Path(value['run_directory']).resolve()) for value in ledger if value['kind'] == 'main_positive']
    dates = [_date(_load(Path(value)/'run-lock.json')['created_at_utc']) for value in attempts]
    # A human ledger order cannot move an intervening failure out of the way.
    chronological = all(first < last for first, last in zip(dates, dates[1:]))
    ordered = [path for _, path in sorted(zip(dates, attempts))]
    return chronological and len(chosen) == len(set(chosen)) == 3 and chosen == ordered[-3:]


def check_attempt_inventory(ledger, roots, case_hashes):
    f.require(isinstance(ledger, list) and ledger, 'retain complete formal-attempt ledger')
    paths = [Path(entry['run_directory']).resolve() for entry in ledger]
    f.require(len(paths) == len(set(paths)), 'duplicate attempt ledger record')
    discovered = set()
    for root in roots:
        root = Path(root).resolve()
        for lock_path in root.rglob('run-lock.json'):
            # Worker packages and editable-project source trees are not jobs.
            if lock_path.parent.parent != root:
                continue
            lock = _load(lock_path)
            if lock.get('acceptance_case_sha256') in case_hashes:
                discovered.add(lock_path.parent.resolve())
    f.require(discovered == set(paths), 'formal run inventory differs from retained attempt ledger')
    for entry, path in zip(ledger, paths):
        lock = _load(path/'run-lock.json')
        f.require(lock.get('acceptance_case_sha256') in case_hashes and lock.get('run_id') == path.name, 'attempt is not a named snapshotted formal run')
        f.require(entry['kind'] in ('main_positive', 'no_trigger', 'broken_rope', 'locked_door', 'variant', 'replay'), 'unknown formal attempt kind')
        f.require((path/'spec.json').is_file(), 'failed attempt spec was removed')
    dates = [_date(_load(path/'run-lock.json')['created_at_utc']) for path in paths]
    f.require(all(first < last for first, last in zip(dates, dates[1:])), 'attempt ledger reordered relative to original job snapshot chronology')
    return {'passed': True, 'retained_formal_attempts': len(paths), 'run_directories': [str(p) for p in paths],
            'scope': 'All runs with the frozen main/variant case under every declared run root. Root completeness also requires independent workspace review.'}


def _patch(document, changes, permitted):
    result = copy.deepcopy(document)
    seen = set()
    for change in changes:
        f.require(set(change) == {'path', 'before', 'after'} and isinstance(change['path'], list) and change['path'], 'freeze exact before/after patch')
        path = change['path'];key = tuple(path)
        f.require(key not in seen and permitted(path), 'duplicate or forbidden variant edit path')
        f.require(not any(key[:len(other)] == other or other[:len(key)] == key for other in seen), 'overlapping edits are ambiguous')
        seen.add(key)
        current = result
        for component in path[:-1]:
            current = current[component]
        f.require(current[path[-1]] == change['before'] and change['before'] != change['after'], 'variant does not match frozen before/after value')
        current[path[-1]] = copy.deepcopy(change['after'])
    return result


def _world_anchor_path(path):
    return len(path) == 4 and path[0] == 'objects' and path[2:] == ['joint', 'local_pos0']


def _synchronized_world_anchors(base_spec, expected, changes):
    """Only translate an existing world frame with its unchanged-orientation body.

    The 1e-12m bound compares two floating-point subtractions; it is not a
    physics/anchor-error tolerance or evidence of an independent layout change.
    """
    records = []
    for change in changes:
        if not _world_anchor_path(change['path']):
            continue
        name = change['path'][1]
        obj = base_spec['objects'].get(name, {})
        cfg = obj.get('joint', {})
        f.require(obj.get('kind') == 'joint' and not passive.validate_joint(base_spec, obj), 'synchronized anchor requires an existing supported passive joint')
        f.require(cfg.get('enabled', True) is True and cfg.get('body0') is None, 'synchronized anchor requires an enabled world/body1 joint')
        body_id = cfg['body1']
        body, moved = base_spec['objects'][body_id], expected['objects'][body_id]
        def physical(value):
            collision = (not passive.validate_parts(value) and any(part.get('collision', True) is True for part in value['parts'])) if value.get('kind') == 'compound' else value.get('kind') in passive.GEOMETRY[:-1] and value.get('collision') is True
            return value.get('dynamic') is True and not value.get('spawn_step', 0) and collision
        f.require(physical(body) and physical(moved), 'synchronized anchor body1 must be an initially present dynamic colliding rigid body')
        position_path = ['objects', body_id, 'position']
        f.require(any(edit['path'] == position_path for edit in changes), 'synchronized anchor needs an explicit whole body1 position patch')
        before, after = body.get('position'), moved.get('position')
        f.require(f.m.vector(before) and f.m.vector(after) and before != after, 'synchronized anchor needs a finite nonzero body1 translation')
        f.require(body.get('orientation_wxyz') == moved.get('orientation_wxyz'), 'synchronized anchor body1 orientation must remain unchanged')
        f.require(f.m.vector(change['before']) and f.m.vector(change['after']), 'world anchor patch must replace the whole finite three-vector')
        body_delta = f.m.sub(after, before)
        anchor_delta = f.m.sub(change['after'], change['before'])
        f.require(f.m.vector(body_delta) and f.m.vector(anchor_delta) and all(math.isclose(a, b, rel_tol=0, abs_tol=1e-12) for a, b in zip(anchor_delta, body_delta)), 'world anchor delta must equal body1 translation without preload')
        records.append({'joint_id': name, 'body1_id': body_id, 'body_translation_m': body_delta, 'world_anchor_translation_m': anchor_delta})
    return records


def compare_variant(base_spec, variant_spec, base_case, variant_case, declaration):
    """Canonical, asset-proven specs only; never ignores full-scene edits."""
    f.require(set(declaration) == {'cup_body_id', 'cup_delta_world_m', 'additional_spec_changes', 'case_geometry_changes'}, 'freeze complete variant declaration')
    cup = declaration['cup_body_id'];delta = declaration['cup_delta_world_m']
    f.require(cup == base_case['terminal']['receiver_id'] == variant_case['terminal']['receiver_id'] and f.m.vector(delta) and math.isclose(math.sqrt(f.m.dot(delta, delta)), .20, abs_tol=1e-9, rel_tol=0), 'variant must move actual cup exactly 0.20m')
    expected = copy.deepcopy(base_spec)
    position = expected['objects'][cup]['position']
    expected['objects'][cup]['position'] = [a+b for a, b in zip(position, delta)]
    changes = declaration['additional_spec_changes']
    f.require(changes, 'cup shift plus another declared physical local layout/asset change required')
    def local_geometry(path):
        if len(path) < 3 or path[0] != 'objects' or path[1] == cup or path[2] not in ('position', 'orientation_wxyz', 'size', 'parts', 'asset_path'):
            return False
        obj = base_spec['objects'].get(path[1], {})
        return obj.get('kind') == 'asset' or obj.get('collision') is True
    def world_anchor(path):
        if not _world_anchor_path(path):
            return False
        obj = base_spec['objects'].get(path[1], {})
        return obj.get('kind') == 'joint' and isinstance(obj.get('joint'), dict) and 'local_pos0' in obj['joint']
    f.require(any(local_geometry(change['path']) for change in changes), 'world-frame synchronization alone is not an independent physical local geometry change')
    expected = _patch(expected, changes, lambda path: local_geometry(path) or world_anchor(path))
    anchors = _synchronized_world_anchors(base_spec, expected, changes)
    def case_geometry(path):
        if path[:2] == ['terminal', 'interior_local']:
            return True
        if len(path) >= 5 and path[:2] == ['activity', 'stages'] and type(path[2]) is int and path[3] == 'roi_world':
            return True
        if len(path) >= 5 and path[0] == 'events' and path[2] == 'conditions' and type(path[3]) is int and path[4] == 'support_region_local':
            return True
        if len(path) >= 4 and path[0] == 'mechanism_cases':
            return path[2] == 'bridge_regions_world' or path[2:4] == ['receiver', 'interior_world'] or path[2] == 'support_region_local'
        return False
    expected_case = _patch(base_case, declaration['case_geometry_changes'], case_geometry)
    return {'passed': expected == variant_spec and expected_case == variant_case, 'cup_translation_norm_m': math.sqrt(f.m.dot(delta, delta)),
            'only_frozen_scene_geometry_changes': expected == variant_spec, 'only_frozen_case_geometry_changes': expected_case == variant_case,
            'synchronized_world_anchor_edits': anchors,
            'scope': 'Exact predeclared cup translation plus local geometric/asset edits; independent static review must confirm the additional layout change. A synchronized world-anchor translation adds no independent layout credit. No other joint/frame/axis/limit/connection/enable edit, force, mass, friction, damping, activity threshold, quiet budget or global acceptance relaxation is exempted.'}


def verify_native(run_directory, cameras, stock, _metadata=None):
    """Native hashes/frame timeline/decode checks; human visibility is separate."""
    from simscene.video_tools import inspect
    root = Path(run_directory).resolve()
    # The suite extracts these small fields from the already accepted raw run;
    # do not reread a multi-gigabyte result just to inspect two native videos.
    run = _metadata['run'] if _metadata is not None else _load(root/'result.json')
    spec = _metadata['spec'] if _metadata is not None else _load(root/'spec.json')
    videos = run.get('videos', {})
    f.require(set(cameras) == {'fixed', 'tracking'} and cameras['fixed'] != cameras['tracking'], 'one fixed and one same-run tracking camera required')
    result = {}
    for role, camera in cameras.items():
        obj = spec['objects'].get(camera, {})
        f.require(obj.get('kind') == 'camera' and (not obj.get('camera_path') and not obj.get('camera_orbit') if role == 'fixed' else bool(obj.get('camera_path')) and not obj.get('camera_orbit')), 'camera role does not match fixed/along-path nominal camera configuration')
        record = videos[camera]
        f.require(record['native_resolution'] == [1920, 1080] and record['fps'] == 30 and record['timebase'] == 'simulation', 'require native1080p30 simulation capture')
        inspection = inspect(record['path'], record=record)
        rows = [json.loads(line) for line in Path(record['frame_manifest']).read_text().splitlines()]
        zero = run['run_zero_absolute_physics_step']
        clocks = all(row.get('render_context', {}).get('absolute_physics_step') == zero+row['physics_step'] for row in rows)
        covers = rows and rows[0]['physics_step'] <= stock['activity']['metrics']['window_start_step'] and rows[-1]['physics_step'] >= stock['terminal']['stable_confirmation_step']
        result[role] = {'passed': not inspection['issues'] and inspection.get('simulation_timeline', {}).get('passed') is True and clocks and bool(covers), 'camera_id': camera,
                        'inspection': inspection, 'strict_absolute_frame_boundaries_match': clocks, 'covers_release_through_confirmation': bool(covers)}
    return {'passed': all(v['passed'] for v in result.values()), 'cameras': result,
            'scope': 'Uninterrupted native recordings from one physics run. Wheel-marker readability, causal visibility, material/proxy appearance and editorial film need independent visual review.'}


def save_run_report(report, destination):
    """Spill the complete report, retaining only a small suite summary.

    json.dump streams encoder chunks; json.dumps would allocate a second
    report-sized string. No stock checks, callbacks or masks are discarded
    from the individual evidence report stored on disk.
    """
    destination = Path(destination)
    # Publish only complete reports, without overwriting any prior attempt.
    # The temporary is in the same directory; an exclusive hard link makes
    # publication atomic even if another examiner chose the same destination.
    with tempfile.NamedTemporaryFile('w', dir=destination.parent, prefix='.'+destination.name+'.partial-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    stock = report.get('stock', {})
    keys = ('passed', 'mode', 'profile', 'checks', 'case_sha256', 'checker_sha256', 'reused_mechanism_sha256',
            'paired_manifest_fields_match', 'paired_runtime_configuration_matches', 'paired_geometry_settings_match', 'reference_positive_passed')
    return {'passed': report['passed'], 'mode': report.get('mode'), 'scope': report.get('scope'),
            'stock': {key: copy.deepcopy(stock[key]) for key in keys if key in stock},
            'stock_activity_metrics': copy.deepcopy(stock.get('activity', {}).get('metrics')),
            'fidelity_checks': {key: report[key]['passed'] for key in ('static_stage', 'mass_properties', 'cart', 'cable', 'bridge', 'non_contact_auxiliaries') if key in report},
            'run_lock_sha256': report.get('run_lock_sha256'), 'evidence_lock_sha256': report.get('evidence_lock_sha256'),
            'supplemental_code_sha256': report.get('supplemental_code_sha256'), 'supplemental_contract_sha256': report.get('supplemental_contract_sha256'),
            'individual_report': {'path': str(destination.resolve()), 'sha256': f.sha(destination), 'size': destination.stat().st_size}}


def verify_suite(manifest):
    f.assert_kernel()
    required = {'schema', 'software_freeze_path', 'contract_path', 'static_review_path', 'freeze_path', 'positive_runs', 'controls', 'variant', 'replay', 'attempt_ledger_path', 'formal_runs_roots', 'native_cameras', 'native_positive_index', 'clock_directory', 'provided_clock_path'}
    f.require(isinstance(manifest, dict) and set(manifest) == required and manifest['schema'] == SCHEMA, 'expected complete '+SCHEMA)
    software = f.assert_software_freeze(manifest['software_freeze_path'])
    positives = manifest['positive_runs'];controls = manifest['controls'];variant = manifest['variant'];replay = manifest['replay']
    f.require(len(positives) == 3 and set(controls) == {'no_trigger', 'broken_rope', 'locked_door'}, 'exactly three positives and all three controls required')
    f.require(set(variant) == {'run_directory', 'contract_path', 'static_review_path', 'freeze_path', 'declaration_path'} and set(replay) == {'run_directory', 'export_preflight_path'}, 'complete independent variant/replay records required')
    directories = [*positives, *controls.values(), variant['run_directory'], replay['run_directory']]
    resolved = [Path(d).resolve() for d in directories]
    f.require(len(set(resolved)) == len(resolved), 'a run cannot be reused as a repeat/control/variant/replay')
    f.require(type(manifest['native_positive_index']) is int and 0 <= manifest['native_positive_index'] < 3, 'choose a declared repeat for native footage')
    clock_root = Path(manifest['clock_directory']).resolve()
    f.require(not any(clock_root.is_relative_to(path) for path in resolved), 'clock exports must remain outside sealed run directories')
    report_root = clock_root/'individual-run-reports'
    report_root.mkdir(parents=True, exist_ok=True)
    names = ['positive_1', 'positive_2', 'positive_3', *controls, 'variant', 'replay']
    f.require(all(not (report_root/(name+'.json')).exists() for name in names), 'preserve prior individual reports; choose a fresh clock/report directory')
    reports, data, clocks = {}, {}, {}
    native = {'passed': False, 'scope': 'Selected positive did not provide accepted completion evidence.'}

    def process(name, directory, contract_path, review_path, freeze_path, mode='positive', reference=None, additional_files=()):
        nonlocal native
        verify_freeze(freeze_path, contract_path, review_path, directory, additional_files)
        current = f.verify_one(directory, contract_path, review_path, mode, reference)
        metadata = current.get('suite_metadata', {'passed': False})
        if mode == 'positive':
            if current.get('stock', {}).get('passed') and metadata['passed']:
                clocks[name] = {'passed': True, **f.export_motion_csv(current['stock'], metadata['case'], clock_root/(name+'.csv'), manifest['provided_clock_path'], metadata['lock']['physics_dt_s'])}
                if name == 'positive_'+str(manifest['native_positive_index']+1):
                    native = verify_native(directory, manifest['native_cameras'], current['stock'], _metadata=metadata['native_metadata'])
            else:
                clocks[name] = {'passed': False, 'scope': 'Failed physical report; no valid completion clock asserted.'}
        reports[name] = save_run_report(current, report_root/(name+'.json'))
        data[name] = metadata
        del current
        gc.collect()

    for index, directory in enumerate(positives):
        process('positive_'+str(index+1), directory, manifest['contract_path'], manifest['static_review_path'], manifest['freeze_path'])
    base = data['positive_1'];base_dir = positives[0]
    for mode, directory in controls.items():
        process(mode, directory, manifest['contract_path'], manifest['static_review_path'], manifest['freeze_path'], mode, base_dir)
    process('variant', variant['run_directory'], variant['contract_path'], variant['static_review_path'], variant['freeze_path'], additional_files=[variant['declaration_path']])
    process('replay', replay['run_directory'], manifest['contract_path'], manifest['static_review_path'], manifest['freeze_path'])
    f.require(all(d['passed'] for d in data.values()), 'one or more run locks failed; no suite inference')
    manifest_matches = {name: {key: key in current['lock'] and key in base['lock'] and current['lock'][key] == base['lock'][key] for key in f.m.PAIRED_MANIFEST_FIELDS} for name, current in data.items()}
    geometry_matches = all(current['geometry_settings'] == base['geometry_settings'] for current in data.values())
    base_spec = base['canonical_spec']
    variant_spec = data['variant']['canonical_spec']
    changed = compare_variant(base_spec, variant_spec, base['case'], data['variant']['case'], _load(variant['declaration_path']))
    ledger = _load(manifest['attempt_ledger_path'])
    inventory = check_attempt_inventory(ledger, manifest['formal_runs_roots'], {base['integrity']['case_sha256'], data['variant']['integrity']['case_sha256']})
    export = _load(replay['export_preflight_path'])
    replay_root = Path(replay['run_directory']).resolve()
    distinct_parent = all(not replay_root.is_relative_to(path.parent.parent) for path in resolved[:-1])
    export_ok = export.get('passed') is True and export.get('scope') == 'independent_editable_export_preflight' and distinct_parent and Path(export.get('source_run_directory', '')).resolve() in [Path(v).resolve() for v in positives] and replay_root.is_relative_to(Path(export.get('project_directory', '/nonexistent-export-project')).resolve())
    for filename, digest in export.get('files_sha256', {}).items():
        export_ok = export_ok and Path(filename).is_file() and f.sha(filename) == digest
    export_ok = export_ok and bool(export.get('files_sha256'))
    checks = {'all_original_physics_and_fidelity_pass': all(r['passed'] for r in reports.values()), 'all13_runtime_fields_match': all(all(values.values()) for values in manifest_matches.values()),
              'same_recorded_geometry_policy': geometry_matches, 'three_consecutive_retained_main_positives': consecutive_three(positives, ledger),
              'exact_frozen_variant': changed['passed'], 'all_formal_attempts_retained': inventory['passed'], 'new_directory_editable_replay_preflight': bool(export_ok), 'native_same_run_main_and_tracking': native['passed'], 'all_exact_half_open_clocks_exported': all(c['passed'] for c in clocks.values())}
    return {'passed': all(checks.values()), 'physics_suite_accepted': all(checks.values()), 'complete_delivery_accepted': False, 'orchestration_version': f.ORCHESTRATION_VERSION, 'checks': checks, 'paired_manifests': manifest_matches,
            'runs': reports, 'variant_comparison': changed, 'attempt_inventory': inventory, 'native': native, 'motion_clocks': clocks, 'software': software,
            'memory_scope': 'Sequential full stock/fidelity/mask verification, streaming complete individual reports to disk; only configuration/proof metadata and summaries survive between runs. Frozen stock controls still load their own current/reference pair.',
            'scope': 'One designed full-house configuration, three clean consecutive repeats, exact controls, one predeclared variant and editable new-directory replay. Not randomized robustness, calibrated 3D cable, automatic visual approval or permission to publish.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest');parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = verify_suite(_load(args.manifest))
    output = Path(args.output)
    f.require(not output.exists(), 'preserve prior suite reports; choose a fresh output path')
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': result['passed'], 'checks': result['checks'], 'output': str(output)}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
