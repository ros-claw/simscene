"""Independent, read-only P3/P4 supplements for the explicitly versioned v43 plugin.

No scene construction, launch, force, release, pose write or missing-data fill.
Scenario IDs, signs, geometry and tolerances must be frozen from nominal input
and static review before any formal house attempt. Pure helpers do not certify
file provenance; the file-level entry point requires complete sealed evidence.
"""
import copy
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path

from simscene.verification import passive_network_v3 as p, mechanism_v2 as m, structural_loads as loads
from simscene.snapshot_integrity import comparison_identity
from experiments import composed_event_mechanisms_v2 as composed
from simscene.verification import d6_admission as admission
from simscene import d6 as d6_math

SCHEMA = 'simscene.whole_home_fidelity.v7'
ORCHESTRATION_VERSION = 9
COMPOSITION_SHA256 = '0442d93e1455bcea309d646f59a427f856ad55750d2c686238237414fda5b91f'
KERNEL_SHA256 = {
    'passive_network': '0fd01c035c7b4db3143cab88015be7c93f9bdd77c0826d13b97a229191167b27',
    'mechanism': '0b8a9d4220c8093d5b8b030c9ab4351a15a742c1f9734f17d9a910e1755e2457',
    'd6_admission': 'c3588cfcffe55ea1d23e7584eb5a623dd126ec701588eaf1f7456df9182f29e2',
    'd6_math': '095a8507fcd81e9516fc77e8e04bee2066b2622ba5630b7d325b89a8f5cfafd1',
    'structural_loads': 'e75f33f48ac0c4f5e491b0666d0b5c5694f1698240a1561e7d01a2fa6b986c42',
}
SOFTWARE_FREEZE_SHA256 = '5cecd9539706764105a8ee7b59eb535e9e0bb6e0ff3c1b9cb38c3f2723c548fa'
CLOCK_SHA256 = '50457355ecb7c8763fec5f1c70920ab48bafe51f737f45a5d4589e39dd780f4c'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def assert_kernel():
    require(sha(composed.__file__) == COMPOSITION_SHA256, 'frozen local composition adapter changed')
    composed.assert_kernel()
    for name, module in (('passive_network', p), ('mechanism', m), ('structural_loads', loads), ('d6_admission', admission), ('d6_math', d6_math)):
        require(sha(module.__file__) == KERNEL_SHA256[name], 'frozen v43 kernel changed: '+name)


def assert_software_freeze(path):
    require(sha(path) == SOFTWARE_FREEZE_SHA256, 'v43 software freeze record changed')
    record = json.loads(Path(path).read_text())
    package = Path(record['package']).resolve()
    hashes = record['installed_package_files_sha256']
    actual = {node.relative_to(package).as_posix() for node in package.rglob('*') if node.is_file() and '__pycache__' not in node.parts and node.suffix != '.pyc'}
    require(actual == set(hashes), 'installed frozen package file inventory changed')
    require(all(not (package/name).is_symlink() and sha(package/name) == digest for name, digest in hashes.items()), 'installed frozen package bytes changed')
    root = Path(__file__).resolve().parents[1]
    require(all(sha(root/name) == digest for name, digest in record['checkout_source_sha256'].items()), 'frozen checkout source changed')
    assert_kernel()
    return {'passed': True, 'software_freeze_sha256': sha(path), 'installed_file_count': len(hashes), 'checkout_source_file_count': len(record['checkout_source_sha256'])}


def validate_floors(case, dt):
    p.validate_case(case)
    require(case['schema'] == p.SCHEMA_V3, 'explicit v3 D6 network schema required')
    require(case['profile'] == 'P3' and math.isfinite(dt) and dt > 0, 'P3 case and actual positive timestep required')
    require((case['terminal']['hold_steps']-1)*dt >= 2, 'freeze >=2 whole seconds onset-to-confirmation (121 samples at 60Hz)')
    require(set(case['required_controls']) >= {'no_trigger', 'broken_rope', 'locked_door'}, 'all three P3 interventions required')
    kinds = {c['mechanism'] for c in case.get('mechanism_cases', {}).values()}
    require(kinds == {'rope_drawer'}, 'stock contains complete rope assertions only; event modules require explicit composed contracts')
    return True


def canonical_spec(spec, identities):
    """Fingerprint nominal input after independently proving its assets.

    Identity inputs must come from pinned static preflight or sealed run files;
    this helper never asserts that arbitrary in-memory identities are trusted.
    """
    result = copy.deepcopy(spec)
    for key in ('scene_id', 'revision', 'requests'):
        result.pop(key, None)
    assets = {n for n, obj in result['objects'].items() if obj.get('kind') == 'asset'}
    require(assets == set(identities), 'complete verified asset identities required')
    for name in assets:
        result['objects'][name]['asset_path'] = {'verified_identity_sha256': canonical_sha(identities[name])}
    return result


def sealed_identities(data):
    require(data['passed'], 'sealed input/output proof required')
    records = json.loads((data['root']/'asset-lock.json').read_text())
    return {name: comparison_identity(data['root'], obj, records[name], data['lock']['runtime_python'])
            for name, obj in data['spec']['objects'].items() if obj.get('kind') == 'asset'}


def suite_metadata(data, identities):
    """Copy only bounded comparison/provenance data, never raw observations.

    This is called while one fully locked run is available. The suite can then
    release its samples and its complete report before reading another run.
    Original reports and masks are persisted separately rather than truncated.
    """
    require(data['passed'], 'accepted file locks required for suite metadata')
    run, root = data['run'], data['root']
    evidence = json.loads((root/'evidence-lock.json').read_text())
    return {'passed': True, 'root': str(root), 'lock': copy.deepcopy(data['lock']), 'case': copy.deepcopy(data['case']),
            'canonical_spec': canonical_spec(data['spec'], identities), 'verified_asset_identities': copy.deepcopy(identities),
            'geometry_settings': copy.deepcopy(run.get('mechanism_configuration', {}).get('geometry_settings')),
            'integrity': copy.deepcopy(data['integrity']),
            'evidence_sha256': {'run-lock.json': sha(root/'run-lock.json'), 'evidence-lock.json': sha(root/'evidence-lock.json'),
                                'result.json': evidence['artifacts']['result.json']['sha256']},
            'native_metadata': {'run': {'run_zero_absolute_physics_step': run.get('run_zero_absolute_physics_step'), 'videos': copy.deepcopy(run.get('videos', {}))},
                                'spec': {'objects': {name: copy.deepcopy(obj) for name, obj in data['spec']['objects'].items() if obj.get('kind') == 'camera'}}}}


def _window(run, report, phase):
    require(set(phase) == {'start_event', 'end_event'}, 'freeze exact event phase')
    start, end = [report['events'][phase[key]]['onset_step'] for key in ('start_event', 'end_event')]
    require(type(start) is int and type(end) is int and 0 <= start < end, 'phase events absent or unordered')
    samples = {s['physics_steps']: s for s in [run['initial_observation'], *run['samples']]}
    require(all(n in samples for n in range(start, end+1)), 'missing phase observation; never interpolate')
    return start, end, samples


def cart_rolling(run, spec, report, cfg, dt, _journal=None):
    """Distance-weighted same-interval wheel rotation/contact witnesses.

    R*theta/travel is descriptive, not a calibrated no-slip measurement. Wheel
    angle and contact observations never add activity seconds or categories.
    """
    require(set(cfg) == {'body_id', 'phase', 'direction_world', 'minimum_progress_m', 'minimum_progress_speed_m_s', 'minimum_grounded_rotation_distance_fraction', 'wheels'}, 'freeze complete cart fidelity fields')
    require(m.unit(cfg['direction_world']) and cfg['minimum_progress_m'] > 0 and cfg['minimum_progress_speed_m_s'] > 0, 'cart needs signed direction and positive progress floors')
    fraction = cfg['minimum_grounded_rotation_distance_fraction']
    require(m.finite(fraction) and 0 < fraction <= 1 and cfg['wheels'], 'freeze wheel contact/rotation coverage')
    start, end, samples = _window(run, report, cfg['phase'])
    journal = _journal if _journal is not None else p.contact_journal(run, spec)
    require(journal['passed'], 'invalid/missing per-step contact callbacks')
    contacts_by_step = {}
    for record in journal['records']:
        contacts_by_step.setdefault(record['observation_step'], []).append(record)
    direction, body = cfg['direction_world'], cfg['body_id']
    displacement = m.dot(m.sub(m.pose(samples[end], spec, body)[0], m.pose(samples[start], spec, body)[0]), direction)
    intervals = []
    for step in range(start+1, end+1):
        advance = m.dot(m.sub(m.pose(samples[step], spec, body)[0], m.pose(samples[step-1], spec, body)[0]), direction)
        intervals.append((step, advance if advance/dt >= cfg['minimum_progress_speed_m_s'] else 0.))
    eligible_distance = sum(distance for _, distance in intervals)
    loaded = {j['path']: j for j in run['mechanism_configuration']['joints']}
    wheels = {}
    require(len({w['body_id'] for w in cfg['wheels']}) == len(cfg['wheels']) and len({w['joint_id'] for w in cfg['wheels']}) == len(cfg['wheels']), 'duplicate wheels/joints cannot inflate fidelity')
    for wheel in cfg['wheels']:
        require(set(wheel) == {'body_id', 'joint_id', 'carrier_body_id', 'support_body_ids', 'radius_m', 'spin_sign', 'minimum_rotation_degrees', 'minimum_signed_angular_speed_degrees_s'}, 'freeze all wheel fields')
        require(type(wheel['spin_sign']) is int and wheel['spin_sign'] in (-1, 1) and all(m.finite(wheel[k]) and wheel[k] > 0 for k in ('radius_m', 'minimum_rotation_degrees', 'minimum_signed_angular_speed_degrees_s')), 'invalid wheel sign/radius/motion floor')
        require(wheel['support_body_ids'] and len(set(wheel['support_body_ids'])) == len(wheel['support_body_ids']), 'freeze distinct support body IDs')
        require(all(n not in (wheel['body_id'], wheel['carrier_body_id'], body) and spec['objects'].get(n, {}).get('collision') is True and spec['objects'][n].get('dynamic') is not True for n in wheel['support_body_ids']), 'wheel supports must be distinct colliding static ground, not cart/self contact')
        joint = loaded.get(m.path(wheel['joint_id']), {})
        require(joint.get('type') == 'PhysicsRevoluteJoint' and joint.get('enabled') is True and not joint.get('drives') and not joint.get('drive_attributes') and joint.get('body0') == [m.path(wheel['carrier_body_id'])] and joint.get('body1') == [m.path(wheel['body_id'])], 'wheel must have its actual passive carrier revolute')
        def angle(step):
            state = samples[step]['joints'][wheel['joint_id']]
            require(state.get('enabled') is True and state.get('drive_present') is False and m.finite(state.get('angle_degrees')), 'missing/passively invalid wheel observation')
            return state['angle_degrees']
        signed_angle = wheel['spin_sign']*(angle(end)-angle(start))
        witnessed_distance, records = 0., []
        for step, distance in intervals:
            if distance <= 0:
                continue
            rotation = wheel['spin_sign']*(angle(step)-angle(step-1))
            contacts = [r for r in contacts_by_step.get(step, []) if wheel['body_id'] in r['body_ids'] and any(n in r['body_ids'] for n in wheel['support_body_ids'])]
            rotating = rotation/dt >= wheel['minimum_signed_angular_speed_degrees_s']
            if rotating and contacts:
                witnessed_distance += distance
                records.append({'interval_start_step': step-1, 'interval_end_step': step, 'signed_angle_degrees': rotation, 'progress_m': distance, 'contact_callback_records': contacts})
        coverage = witnessed_distance/eligible_distance if eligible_distance else 0.
        wheels[wheel['body_id']] = {'passed': signed_angle >= wheel['minimum_rotation_degrees'] and coverage >= fraction and eligible_distance > 0,
            'signed_angle_degrees': signed_angle, 'radius_times_angle_m': wheel['radius_m']*math.radians(signed_angle),
            'radius_angle_to_net_progress_ratio': wheel['radius_m']*math.radians(signed_angle)/displacement if displacement > 0 else None,
            'grounded_signed_rotation_distance_fraction': coverage, 'witnessed_intervals': records}
    return {'passed': displacement >= cfg['minimum_progress_m'] and all(w['passed'] for w in wheels.values()), 'phase_steps': [start, end],
            'signed_net_progress_m': displacement, 'speed_qualified_forward_distance_m': eligible_distance, 'wheels': wheels,
            'scope': 'Actual signed wheel rotation and ground callbacks during cart progress; Rtheta comparison is descriptive. Does not prove no-slip or visible marker readability.'}


def cable_no_bypass(run, spec, cfg):
    require(set(cfg) == {'load_body_id', 'weight_body_id', 'load_attachment_joint_id', 'additional_passive_joint_ids', 'model_description'}, 'freeze cable topology and approximation disclosure')
    require(isinstance(cfg['model_description'], str) and cfg['model_description'], 'describe the actual cable approximation')
    joints = run['mechanism_configuration']['joints']
    cut = m.path(cfg['load_attachment_joint_id'])
    require(sum(j['path'] == cut for j in joints) == 1, 'unique loaded attachment joint required')
    dynamic = {m.path(n) for n, o in spec['objects'].items() if o.get('dynamic')}
    def reachable(omit_cut):
        edges = []
        for joint in joints:
            if joint.get('enabled') is not True or omit_cut and joint['path'] == cut:
                continue
            require(not joint.get('drives') and not joint.get('drive_attributes'), 'active cable/body constraint')
            if len(joint.get('body0', [])) == len(joint.get('body1', [])) == 1:
                a, b = joint['body0'][0], joint['body1'][0]
                if a in dynamic and b in dynamic:
                    edges.extend(((a, b), (b, a)))
        seen = {m.path(cfg['weight_body_id'])}
        while True:
            more = seen | {b for a, b in edges if a in seen}
            if more == seen:
                return m.path(cfg['load_body_id']) in seen
            seen = more
    extras = [j for j in joints if j['path'] in {m.path(n) for n in cfg['additional_passive_joint_ids']}]
    require(len(extras) == len(cfg['additional_passive_joint_ids']), 'additional cable joint inventory incomplete/duplicated')
    require(all(m.path(cfg['load_body_id']) not in j.get('body0', [])+j.get('body1', []) for j in extras), 'auxiliary cable constraint reaches load directly')
    return {'passed': reachable(False) and not reachable(True), 'connected_before_cut': reachable(False), 'connected_after_cut': reachable(True), 'additional_passive_joint_count': len(extras),
            'model_description': cfg['model_description'], 'scope': 'Loaded dynamic joint graph only. Actual contact load transmission and stopping behavior still require the nested rope assertion and matching broken-rope control.'}


def bridge_support(run, spec, report, declarations, composition, cfg, _journal=None):
    require(set(cfg) == {'composed_mechanism_key', 'phase', 'minimum_support_callback_updates'}, 'freeze composed bridge support phase and witness count')
    nested = declarations[cfg['composed_mechanism_key']]['mechanism_case']
    require(nested['mechanism'] == 'wheel_door_bridge', 'complete composed wheel/door/retainer/pin definition required')
    require(type(cfg['minimum_support_callback_updates']) is int and cfg['minimum_support_callback_updates'] > 0, 'freeze positive actual support callback count')
    start, end, _ = _window(run, report, cfg['phase'])
    journal = _journal if _journal is not None else p.contact_journal(run, spec)
    require(journal['passed'], 'per-step contact evidence missing')
    bodies = {nested['roles']['door'], nested['roles']['rollingpin']}
    records = [r for r in journal['records'] if start < r['observation_step'] <= end and set(r['body_ids']) == bodies]
    count = len({r['observation_step'] for r in records})
    return {'passed': composition['passed'] and composition['mechanisms'][cfg['composed_mechanism_key']]['passed'] and count >= cfg['minimum_support_callback_updates'],
            'phase_steps': [start, end], 'support_callback_updates': count, 'callback_records': records,
            'scope': 'Explicit composed wheel/latch/bridge/release/region assertion plus actual pin-door callbacks in the declared crossing phase. No synthetic stock/P1 pilot report is constructed.'}


def bind_non_contact_auxiliary_bodies(spec, case, body_ids):
    """Static role binding only; runtime zero-contact proof remains mandatory."""
    require(isinstance(body_ids, list) and len(set(body_ids)) == len(body_ids) and all(isinstance(n, str) and n for n in body_ids), 'freeze distinct non-contact auxiliary IDs')
    forbidden = {case['trigger_id'], case['terminal']['body_id'], case['terminal']['receiver_id']}
    forbidden |= {n for h in case['handoffs'] for n in h['body_path']}
    forbidden |= {n for category in case['household_categories'].values() for n in category['body_ids']}
    forbidden |= {source['id'] for stage in case['activity']['stages'] for source in stage['bodies']}
    forbidden |= set(case.get('rope_body_ids', [])) | set(case.get('structural_loads', {}))
    forbidden |= {n for nested in case.get('mechanism_cases', {}).values() for n in nested['roles'].values()}
    forbidden |= set().union(*(p._event_body_ids(event, spec) for event in case['events'].values())) if case['events'] else set()
    require(not set(body_ids) & forbidden, 'non-contact auxiliaries cannot be task/event/category/terminal/load/mechanism bodies')
    for name in body_ids:
        obj = spec['objects'].get(name, {})
        collision = obj.get('collision') is True or obj.get('kind') == 'compound' and obj.get('dynamic') is True and any(part.get('collision', True) is True for part in obj.get('parts', []))
        require(obj.get('kind') in ('box', 'sphere', 'cylinder', 'capsule', 'compound') and obj.get('dynamic') is True and not obj.get('spawn_step', 0) and collision, 'non-contact auxiliary must be an initially present real dynamic collider')
    return body_ids


def non_contact_auxiliary_bodies(run, spec, case, body_ids, dt, _journal=None):
    """Zero-contact proof from every original callback, never an exemption.

    The declared bodies remain subject to stock passive/quiet/control checks.
    No graph/path, household, activation or activity credit is created here.
    """
    result = {'passed': False, 'body_ids': body_ids, 'errors': [], 'contact_records': [],
              'formal_stage_accepted': False, 'activity_or_category_credit': False}
    try:
        bind_non_contact_auxiliary_bodies(spec, case, body_ids)
        timeline = m.timeline(run, spec, dt)
        strict = m.strict_initial_state(run, spec, {'require_strict_initial_state': True}, dt)
        result['timeline'] = timeline;result['strict_initial_state'] = strict
        require(timeline['passed'] and strict['passed'] and run.get('contacts_truncated') is False and spec.get('observation', {}).get('record_contact_pairs') is True, 'complete original strict clock and callback capture required')
        journal = _journal if _journal is not None else p.contact_journal(run, spec)
        require(journal.get('passed') is True and isinstance(journal.get('records'), list), 'valid full original callback journal required')
        known = {n for n, obj in spec['objects'].items() if obj.get('kind') in ('box', 'sphere', 'cylinder', 'capsule', 'compound') and (obj.get('dynamic') or obj.get('collision'))}
        examined = 0
        for sample in run['samples']:
            pairs = sample.get('contact_pairs')
            require(isinstance(pairs, list), 'every original step needs its actual callback list')
            for record in pairs:
                require(isinstance(record, dict), 'malformed original callback')
                ids, actors, colliders = [record.get(k) for k in ('body_ids', 'actor_paths', 'collider_paths')]
                absolute = sample['absolute_physics_step'];first = record.get('first_callback_absolute_physics_step');last = record.get('last_callback_absolute_physics_step')
                valid = isinstance(ids, list) and len(ids) == 2 and all(isinstance(n, str) and n in known for n in ids) and isinstance(actors, list) and len(actors) == 2 and isinstance(colliders, list) and len(colliders) == 2
                if valid:
                    valid = all(isinstance(actor, str) and (actor == m.path(n) or actor.startswith(m.path(n)+'/')) and (collider is None or isinstance(collider, str) and (collider == m.path(n) or collider.startswith(m.path(n)+'/'))) for n, actor, collider in zip(ids, actors, colliders))
                valid = valid and type(record.get('count')) is int and record['count'] > 0 and type(first) is int and type(last) is int and absolute-1 <= first <= last <= absolute
                valid = valid and ('minimum_separation_m' not in record or m.finite(record['minimum_separation_m']))
                require(valid, 'invalid original actor/collider/count/callback boundary')
                examined += 1
                if set(ids) & set(body_ids):
                    result['contact_records'].append({'observation_step': sample['physics_steps'], 'observation_absolute_step': absolute, **copy.deepcopy(record)})
        require(examined == len(journal['records']), 'original callback/journal inventory differs')
        result['original_callback_records_examined'] = examined
        result['original_steps_examined'] = len(run['samples'])
        result['passed'] = not result['contact_records']
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
        result['errors'].append({'type': type(error).__name__, 'reason': str(error)})
    result['scope'] = 'Zero contacts involving each declared auxiliary in every original task-step callback, including cue/static/task/other auxiliary actors. Absence of a reported callback does not establish continuous separation or measured guide reaction. All original stock physics, quiet, control and static role review remain mandatory.'
    return result


def export_motion_csv(report, case, destination, clock_path, dt):
    require(sha(clock_path) == CLOCK_SHA256, 'provided motion clock changed')
    require(not Path(destination).exists(), 'preserve existing clock exports; choose a fresh output path')
    activity = report['activity'];metrics = activity['metrics']
    first, last = metrics['window_start_step'], metrics['window_end_step']
    roles = sorted({body['id'] for stage in case['activity']['stages'] for body in stage['bodies']})
    flags = activity['per_step_motion_flags']
    require([f['physics_step'] for f in flags] == list(range(first+1, last+1)), 'missing/duplicate/out-of-order activity intervals')
    require(all(set(f['body_ids']) <= set(roles) and type(f['active']) is bool and f['active'] == bool(f['body_ids']) for f in flags), 'unregistered/inconsistent role masks')
    with Path(destination).open('w', newline='') as stream:
        writer = csv.writer(stream);writer.writerow(['step', *roles])
        for flag in flags:
            writer.writerow([flag['physics_step']-1, *[int(role in flag['body_ids']) for role in roles]])
    loader = importlib.util.spec_from_file_location('provided_whole_home_motion_clock', clock_path)
    clock = importlib.util.module_from_spec(loader);loader.loader.exec_module(clock)
    with Path(destination).open(newline='') as stream:
        measured = clock.intervals(stream, first, last, 1/dt)
    expected = {'span_s': metrics['chain_duration_s'], 'net_progress_s': metrics['net_effective_action_s'], 'fraction': metrics['motion_occupancy'], 'longest_idle_s': metrics['maximum_idle_s']}
    require(all(math.isclose(measured[k], v, abs_tol=1e-10, rel_tol=1e-10) for k, v in expected.items()), 'CSV clock disagrees with frozen masks')
    return {'csv_sha256': sha(destination), 'provided_clock_sha256': sha(clock_path), 'interval_start_inclusive': first, 'interval_end_exclusive': last, 'role_columns': roles, 'metrics': measured,
            'scope': 'CSV step=checker physics_step-1; every original [N,M) interval, union once, no stability-confirmation waiting.'}


def activity_breakdown(report, case, groups, dt):
    stages = {stage['id'] for stage in case['activity']['stages']}
    require(isinstance(groups, dict) and groups and all(isinstance(name, str) and name and isinstance(values, list) and values for name, values in groups.items()), 'freeze named acts and their stage IDs')
    flattened = [name for values in groups.values() for name in values]
    require(len(flattened) == len(set(flattened)) and set(flattened) == stages, 'acts must partition every registered task stage exactly once')
    flags = report['activity']['per_step_motion_flags']
    require(all(set(row['stage_ids']) <= stages and row['active'] == bool(row['stage_ids']) for row in flags), 'invalid activity stage masks')
    roles = sorted({body['id'] for stage in case['activity']['stages'] for body in stage['bodies']})
    return {'act_union_effective_seconds': {name: sum(bool(set(row['stage_ids']) & set(values)) for row in flags)*dt for name, values in groups.items()},
            'role_effective_seconds': {role: sum(role in row['body_ids'] for row in flags)*dt for role in roles},
            'scope': 'Each act is a per-step union of its frozen eligible stages. Act/role totals can overlap and must never be summed as whole-chain elapsed time.'}


def canonical_joint_unbreakable_default(prim, name, attribute):
    """Recognize two typed schema defaults, never a force/drive exemption."""
    from pxr import Usd, UsdPhysics, Sdf
    if name not in ('physics:breakForce', 'physics:breakTorque') or not prim.IsA(UsdPhysics.Joint) or attribute.GetNumTimeSamples():
        return None
    value = attribute.Get()
    if type(value) is not float or not math.isinf(value) or value < 0:
        return None
    definition = Usd.SchemaRegistry().FindConcretePrimDefinition(prim.GetTypeName())
    if not definition:
        return None
    schema_attribute = definition.GetSchemaAttributeSpec(name)
    fallback = definition.GetAttributeFallbackValue(name)
    opinions = attribute.GetPropertyStack()
    if not schema_attribute or schema_attribute.typeName != Sdf.ValueTypeNames.Float or attribute.GetTypeName() != schema_attribute.typeName or any(opinion.typeName != schema_attribute.typeName for opinion in opinions) or type(fallback) is not float or not math.isinf(fallback) or fallback < 0 or value != fallback:
        return None
    return {'interpretation': 'Canonical positive-infinite joint breaking threshold: unbreakable limit, not applied force or torque.',
            'schema_prim_type': str(prim.GetTypeName()), 'schema_attribute_type': str(schema_attribute.typeName),
            'authored_property_stack_types': [str(opinion.typeName) for opinion in opinions],
            'canonical_fallback': {'nonfinite_schema_value': repr(fallback)},
            'primary_schema_reference': 'https://openusd.org/release/api/class_usd_physics_joint.html'}


def static_stage_catalog(stage_path):
    """Read authored/composed USD only; not a live PhysX force sensor."""
    from pxr import Usd, UsdPhysics, Sdf
    layer = Sdf.Layer.FindOrOpen(str(stage_path))
    require(layer is not None and layer.Reload(force=True), 'cannot freshly read nominal stage')
    stage = Usd.Stage.Open(str(stage_path))
    require(stage is not None, 'cannot load nominal stage')
    joints, bodies, forbidden, physics_attributes, physics_scenes = [], [], [], {}, []
    canonical_defaults = []
    def json_value(value):
        if type(value) is float and not math.isfinite(value):
            return {'nonfinite_schema_value': repr(value)}
        if value is None or type(value) in (str, bool, int, float):
            return value
        if hasattr(value, 'GetReal') and hasattr(value, 'GetImaginary'):
            return {'real': json_value(value.GetReal()), 'imaginary': json_value(value.GetImaginary())}
        try:
            return [json_value(item) for item in value]
        except TypeError:
            return str(value)
    def nonfinite(value):
        if isinstance(value, dict):
            return 'nonfinite_schema_value' in value or any(nonfinite(v) for v in value.values())
        return isinstance(value, list) and any(nonfinite(v) for v in value)
    for prim in stage.TraverseAll():
        schemas = [str(value) for value in prim.GetAppliedSchemas()]
        names = [str(a.GetName()) for a in prim.GetAttributes()]
        for schema in schemas:
            if 'DriveAPI' in schema or any(word in schema.lower() for word in ('forceapi', 'surfacevelocity', 'tendon', 'gearjoint', 'rackandpinion')):
                forbidden.append({'path': str(prim.GetPath()), 'schema': schema})
        for name in names:
            if name.lower().startswith(('drive:', 'physxforce:', 'physxsurfacevelocity:')):
                forbidden.append({'path': str(prim.GetPath()), 'actuation_attribute': name})
            if name.lower().startswith(('omni:script', 'omni:graph')):
                forbidden.append({'path': str(prim.GetPath()), 'behavior_attribute': name})
        if prim.GetTypeName().lower().startswith(('omnigraph', 'behaviorscript')):
            forbidden.append({'path': str(prim.GetPath()), 'behavior_prim_type': prim.GetTypeName()})
        values = {name: {'value': json_value(prim.GetAttribute(name).Get()), 'time_samples': prim.GetAttribute(name).GetTimeSamples(), 'authored_value_opinion': prim.GetAttribute(name).HasAuthoredValueOpinion()} for name in names if name.startswith(('physics:', 'physx', 'drive:'))}
        if values:
            physics_attributes[str(prim.GetPath())] = values
            for name, value in values.items():
                interpretation = canonical_joint_unbreakable_default(prim, name, prim.GetAttribute(name))
                if interpretation:
                    value['canonical_default_interpretation'] = interpretation
                    canonical_defaults.append({'path': str(prim.GetPath()), 'attribute': name, 'authored_value_opinion': value['authored_value_opinion'], **interpretation})
                if value['time_samples']:
                    forbidden.append({'path': str(prim.GetPath()), 'time_authored_physics_attribute': name})
                if value['authored_value_opinion'] and nonfinite(value['value']) and not interpretation:
                    forbidden.append({'path': str(prim.GetPath()), 'nonfinite_authored_physics_attribute': name, 'value': value['value']})
        if prim.IsA(UsdPhysics.Scene):
            scene = UsdPhysics.Scene(prim)
            physics_scenes.append({'path': str(prim.GetPath()), 'gravity_direction': json_value(scene.GetGravityDirectionAttr().Get()), 'gravity_magnitude_m_s2': json_value(scene.GetGravityMagnitudeAttr().Get())})
        if prim.IsA(UsdPhysics.Joint):
            joint = UsdPhysics.Joint(prim)
            joints.append({'path': str(prim.GetPath()), 'type': prim.GetTypeName(), 'enabled': joint.GetJointEnabledAttr().Get(),
                           'body0': [str(x) for x in joint.GetBody0Rel().GetTargets()], 'body1': [str(x) for x in joint.GetBody1Rel().GetTargets()], 'applied_schemas': schemas,
                           'local_position0_m': json_value(joint.GetLocalPos0Attr().Get()), 'local_position1_m': json_value(joint.GetLocalPos1Attr().Get()), 'local_rotation0': json_value(joint.GetLocalRot0Attr().Get()), 'local_rotation1': json_value(joint.GetLocalRot1Attr().Get())})
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            body = UsdPhysics.RigidBodyAPI(prim)
            enabled, kinematic = body.GetRigidBodyEnabledAttr().Get(), body.GetKinematicEnabledAttr().Get()
            scopes = list(Usd.PrimRange(prim));ancestor = prim.GetParent()
            while ancestor and not ancestor.IsPseudoRoot():
                scopes.append(ancestor);ancestor = ancestor.GetParent()
            times = {str(scope.GetPath())+'.'+str(attr.GetName()): attr.GetTimeSamples() for scope in scopes for attr in scope.GetAttributes() if str(attr.GetName()).startswith('xformOp:') and attr.GetNumTimeSamples()}
            bodies.append({'path': str(prim.GetPath()), 'enabled': enabled, 'kinematic': kinematic, 'authored_transform_time_samples': times,
                           'velocity': json_value(body.GetVelocityAttr().Get() or [0, 0, 0]), 'angular_velocity': json_value(body.GetAngularVelocityAttr().Get() or [0, 0, 0]), 'applied_schemas': schemas})
            if enabled and (kinematic or times):
                forbidden.append({'path': str(prim.GetPath()), 'reason': 'enabled kinematic or time-authored action body'})
    return {'passed': not forbidden, 'stage_sha256': sha(stage_path), 'joints': joints, 'rigid_bodies': bodies, 'physics_scenes': physics_scenes, 'physics_attributes': physics_attributes, 'forbidden_actuation_candidates': forbidden, 'canonical_passive_joint_defaults': canonical_defaults,
            'scope': 'Static composed USD inventory. Requires independent role/proxy/energy review plus frozen worker and actual runtime passive/mass readbacks; does not establish live force absence alone.'}


def mass_catalog(run, spec):
    """Require positive cooked mass/COM/inertia proof for every task rigid body."""
    records = run.get('mechanism_configuration', {}).get('mass_properties_by_prim_path', {})
    wanted = {m.path(n) for n, obj in spec['objects'].items() if obj.get('dynamic')}
    checks = {}
    for path in sorted(wanted):
        value = records.get(path, {})
        matrix = value.get('inertia_at_com_in_prim_axes_kg_m2')
        valid = isinstance(matrix, list) and len(matrix) == 3 and all(m.vector(row) for row in matrix)
        if valid:
            a, b, c = matrix
            determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
            valid = all(math.isclose(matrix[i][j], matrix[j][i], abs_tol=1e-8, rel_tol=1e-5) for i in range(3) for j in range(3)) and a[0] > 0 and a[0]*b[1]-a[1]*b[0] > 0 and determinant > 0
        checks[path] = bool(valid and m.finite(value.get('mass_kg')) and value['mass_kg'] > 0 and m.vector(value.get('center_of_mass_local_m')) and m.quaternion(value.get('principal_axes_local_wxyz')) and type(value.get('observed_at_physics_step')) is int and 0 <= value['observed_at_physics_step'] <= run['actual_physics_steps'] and isinstance(value.get('source'), str) and value['source'].startswith('PhysX tensor readback'))
    return {'passed': bool(wanted) and all(checks.values()), 'body_checks': checks, 'mass_properties_by_prim_path': records,
            'scope': 'Actual cooked mass/COM/inertia readback; positive symmetric inertia required. Does not calibrate a searched visual mesh as a physical object.'}


def validate_contract(contract, case, dt):
    required = {'schema', 'network_case_sha256', 'nominal_configuration_sha256', 'static_review_sha256', 'physics_dt_s', 'cart', 'cable', 'bridge', 'activity_excluded_body_ids', 'activity_groups', 'non_contact_auxiliary_body_ids', 'composed_mechanisms'}
    require(isinstance(contract, dict) and set(contract) == required and contract['schema'] == SCHEMA, 'expected complete '+SCHEMA)
    require(contract['physics_dt_s'] == dt and m.finite(dt) and dt > 0, 'timestep differs from preflight')
    for key in ('network_case_sha256', 'nominal_configuration_sha256', 'static_review_sha256'):
        require(isinstance(contract[key], str) and len(contract[key]) == 64 and all(c in '0123456789abcdef' for c in contract[key]), 'freeze exact SHA256: '+key)
    validate_floors(case, dt)
    composed.validate_declarations(contract['composed_mechanisms'], case)
    excluded = contract['activity_excluded_body_ids']
    require(isinstance(excluded, list) and len(set(excluded)) == len(excluded), 'distinct structural activity exclusions required')
    structural = set(case['rope_body_ids']) | {w['body_id'] for w in contract['cart']['wheels']}
    structural |= {v['roles']['pulley'] for v in case['mechanism_cases'].values() if v['mechanism'] == 'rope_drawer' and v['rope_model'] == 'segmented_over_free_pulley'}
    structural |= set(case.get('structural_loads', {}))
    auxiliary = contract['non_contact_auxiliary_body_ids']
    require(isinstance(auxiliary, list) and all(isinstance(n, str) and n for n in auxiliary) and len(set(auxiliary)) == len(auxiliary), 'freeze explicit distinct non-contact auxiliary IDs')
    cart_roles = {contract['cart']['body_id']} | {wheel[key] for wheel in contract['cart']['wheels'] for key in ('body_id', 'carrier_body_id')}
    require(not cart_roles & set(auxiliary), 'non-contact auxiliaries cannot replace cart/wheel/carrier fidelity roles')
    structural |= set(auxiliary)
    require(structural <= set(excluded), 'exclude cable, free pulley and cart wheel structural spin')
    sources = {body['id'] for stage in case['activity']['stages'] for body in stage['bodies']}
    require(not sources & set(excluded), 'structural spin may not buy task activity')
    cart_stages = [stage for stage in case['activity']['stages'] if stage['start_event'] == contract['cart']['phase']['start_event'] and stage['end_event'] == contract['cart']['phase']['end_event'] and any(source['id'] == contract['cart']['body_id'] and source.get('direction_world') == contract['cart']['direction_world'] and source.get('minimum_speed_m_s') == contract['cart']['minimum_progress_speed_m_s'] and 'minimum_angular_speed_degrees_s' not in source for source in stage['bodies'])]
    require(cart_stages, 'cart fidelity phase must match its signed-progress task stage; angular bobbing/spin cannot qualify that source')
    stage_ids = [stage for values in contract['activity_groups'].values() for stage in values]
    require(len(stage_ids) == len(set(stage_ids)) and set(stage_ids) == {stage['id'] for stage in case['activity']['stages']}, 'freeze act partition of every task stage')
    rope = [v for v in case['mechanism_cases'].values() if v['mechanism'] == 'rope_drawer' and v['joints']['drawer_end'] == contract['cable']['load_attachment_joint_id']]
    require(len(rope) == 1 and rope[0]['joints']['drawer_end'] == case['controls']['broken_rope']['joint_id'] and rope[0]['roles']['weight'] == contract['cable']['weight_body_id'] and rope[0]['roles']['drawer'] == contract['cable']['load_body_id'], 'supplemental cable must bind the exact nested load-end cut and roles')
    door = contract['composed_mechanisms'][contract['bridge']['composed_mechanism_key']]['mechanism_case']
    require(door['mechanism'] == 'wheel_door_bridge' and door['roles']['door'] == case['controls']['locked_door']['door_body_id'] and door['joints']['door'] == case['controls']['locked_door']['joint_id'], 'bridge and locked-door control must bind the same physical hinge')
    return contract


def reconstruct_contact_journal(run, spec, stock_summary):
    """One original-data reconstruction, exact unchanged stock projection."""
    require(isinstance(stock_summary, dict) and set(stock_summary) == {'passed', 'record_count', 'errors', 'scope'}, 'complete original stock contact summary required; never manufacture it')
    require(type(stock_summary['passed']) is bool and type(stock_summary['record_count']) is int and stock_summary['record_count'] >= 0 and isinstance(stock_summary['errors'], list) and isinstance(stock_summary['scope'], str), 'original contact summary types changed')
    journal = p.contact_journal(run, spec)
    require(set(journal) == {'passed', 'records', 'errors', 'scope'}, 'unknown original journal inventory')
    projected = {'passed': journal['passed'], 'record_count': len(journal['records']), 'errors': journal['errors'], 'scope': journal['scope']}
    require(projected == stock_summary, 'reconstructed original callbacks differ from unchanged stock summary')
    require(journal['passed'] is True, 'original callback journal failed')
    return journal


def verify_one(directory, contract_path, static_review_path, mode='positive', reference_run=None):
    """One sealed run; scenario contract and static review must predate formals.

    The suite/independent examiner also checks freeze timestamps and complete
    attempt inventory. A positive alone cannot accept P3/P4 or video delivery.
    """
    assert_kernel()
    contract = json.loads(Path(contract_path).read_text())
    require(sha(static_review_path) == contract['static_review_sha256'], 'independent static review changed')
    review = json.loads(Path(static_review_path).read_text())
    require(review.get('passed') is True and review.get('scope') == 'nominal_static_preflight' and review.get('reviewer_role') == 'independent_examiner' and review.get('nominal_configuration_sha256') == contract['nominal_configuration_sha256'] and review.get('network_case_sha256') == contract['network_case_sha256'] and review.get('role_asset_proxy_review_passed') is True and review.get('energy_force_catalog_passed') is True, 'independent nominal role/asset/proxy/energy review bound to this exact configuration required')
    require(review.get('non_contact_auxiliary_review_passed') is True and review.get('non_contact_auxiliary_body_ids') == contract['non_contact_auxiliary_body_ids'], 'independent static auxiliary role and exact non-contact declaration required')
    # Keep the outer raw run absent while the unchanged stock checker owns its
    # current/reference runs. A control still has stock's intrinsic paired
    # peak, but this wrapper no longer adds a third expanded copy on top.
    root = Path(directory).expanduser().resolve()
    require((root/'evidence-lock.json').is_file(), 'complete evidence-lock.json is required before verification')
    proof = {name: sha(root/name) for name in ('run-lock.json', 'evidence-lock.json')}
    stock = p.verify_run(directory, mode=mode, reference_run=reference_run)
    require(all(sha(root/name) == digest for name, digest in proof.items()), 'run evidence locks changed during stock verification')
    data = p._read_locked(directory)
    require(all(sha(root/name) == digest for name, digest in proof.items()), 'run evidence locks changed between stock and supplemental verification')
    if not data['passed']:
        return {'passed': False, 'formal_house_accepted': False, 'stock': stock, 'integrity': data['integrity'], 'suite_metadata': {'passed': False}}
    case, dt = data['case'], data['lock']['physics_dt_s']
    validate_contract(contract, case, dt)
    require(data['integrity']['case_sha256'] == contract['network_case_sha256'], 'network case changed after supplemental freeze')
    identities = sealed_identities(data)
    result = {'passed': False, 'formal_house_accepted': False, 'mode': mode, 'run_directory': str(data['root']),
              'run_lock_sha256': sha(data['root']/'run-lock.json'), 'evidence_lock_sha256': sha(data['root']/'evidence-lock.json'),
              'supplemental_code_sha256': sha(__file__), 'supplemental_contract_sha256': sha(contract_path),
              'orchestration_version': ORCHESTRATION_VERSION, 'suite_metadata': suite_metadata(data, identities),
              'stock': stock, 'static_stage': static_stage_catalog(data['root']/'scene.usda'), 'mass_properties': mass_catalog(data['run'], data['spec'])}
    try:
        journal = reconstruct_contact_journal(data['run'], data['spec'], stock.get('contact_journal'))
        result['original_contact_journal_reconstruction'] = {'passed': True, 'record_count': len(journal['records']),
            'scope': 'One complete original-data callback reconstruction; exact projection equals the unmodified stock summary. No records invented or stock report changed.'}
    except (ValueError, TypeError, KeyError) as error:
        result['original_contact_journal_reconstruction'] = {'passed': False, 'error': str(error)}
        result['scope'] = 'Original stock result retained; missing or inconsistent original contact summary prevents supplemental inference.'
        return result
    result['non_contact_auxiliaries'] = non_contact_auxiliary_bodies(data['run'], data['spec'], case, contract['non_contact_auxiliary_body_ids'], dt, _journal=journal)
    if mode != 'positive':
        result['positive_fidelity_scope'] = 'Composed wheel/spoon, cart/bridge completion and terminal hold are intentionally stopped; exact isolated controls, downstream quiet and all stock passive/typed-load/no-contact predicates remain mandatory. No composed completion success is asserted.'
        result['passed'] = bool(stock['passed'] and result['static_stage']['passed'] and result['mass_properties']['passed'] and result['non_contact_auxiliaries']['passed'])
        return result
    identity = canonical_sha(result['suite_metadata']['canonical_spec'])
    result['nominal_configuration_matches'] = identity == contract['nominal_configuration_sha256']
    if not stock['passed']:
        result['scope'] = 'Failed stock physical result preserved; supplemental completion is not inferred.'
        return result
    result['cart'] = cart_rolling(data['run'], data['spec'], stock, contract['cart'], dt, _journal=journal)
    result['cable'] = cable_no_bypass(data['run'], data['spec'], contract['cable'])
    result['composed_mechanisms'] = composed.evaluate(data['run'], data['spec'], case, contract['composed_mechanisms'], stock, dt, _journal=journal)
    result['bridge'] = bridge_support(data['run'], data['spec'], stock, contract['composed_mechanisms'], result['composed_mechanisms'], contract['bridge'], _journal=journal)
    result['activity_breakdown'] = activity_breakdown(stock, case, contract['activity_groups'], dt)
    terminal = stock['terminal']
    seconds = (terminal['stable_confirmation_step']-terminal['stable_onset_step'])*dt
    result['whole_stable_confirmation_interval_s'] = seconds
    result['passed'] = bool(result['nominal_configuration_matches'] and seconds >= 2 and all(result[key]['passed'] for key in ('static_stage', 'mass_properties', 'cart', 'cable', 'bridge', 'non_contact_auxiliaries', 'composed_mechanisms')))
    result['scope'] = 'One frozen positive only; suite repeats/controls/variant/new-directory replay and native visual review remain separate.'
    return result
