"""Memoize a prior independent f7 decision only on its unchanged byte closure.

Never evaluates physics, parses result.json, modifies old reports or constructs
an accepted report. Expected receipts must be independently retained custody
anchors, not fresh self-computed hashes of a proposed report. Local timestamps
are bookkeeping, not external signatures. The original f7 remains authority.
"""
import copy
import gc
import json
import math
from pathlib import Path, PurePosixPath

from simscene.run_integrity import verify as verify_inputs
from experiments import whole_home_fidelity_v7 as f, whole_home_suite_v7 as suite
from experiments import bounded_entry_clock_v4 as clock

SCHEMA = 'simscene.retained_report_integrity.v1'
PINS = {'fidelity': '7cf47619a2d2ffc0f3c64fd905e78df77c9d5f3a5e240fcc87ffce5322f9fca5',
        'suite': 'acdda6566c3d272cc4030a0d74e4567a3c885605abef3fe2a0e07fa4c64a5ded',
        'clock': '720933b96b241bb15e9e00fde320018cb8e6c7dfbb5f5cc660f79d4ab6b2ed8c'}
MAX_REPORT_BYTES = 1024**3
MAX_METADATA_BYTES = 64*1024**2
MAX_ARTIFACT_BYTES = 64*1024**3
MAX_ARTIFACTS = 10000
BASE_RECEIPT_FIELDS = frozenset('''schema recorded_at_utc role run_directory accepted_for_clock_query
full_report original_run_lock_sha256 original_evidence_lock_sha256 checker_orchestration_version
checker_source_sha256 full_summary anchor_origin P3_accepted P4_accepted'''.split())
PREBIND_FIELDS = frozenset('''schema created_at_utc current_run_directory mode reference_run_directory
reference_record reference_full_report reference_run_lock_sha256 reference_evidence_lock_sha256
reference_result_sha256 reference_clock_certificate'''.split())
ANCHOR_FIELDS = frozenset('''receipt_sha256 full_report_sha256 run_lock_sha256 evidence_lock_sha256
result_sha256 clock_certificate_sha256'''.split())
require, sha = f.require, f.sha


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _path(value):
    require(isinstance(value, (str, Path)), 'an exact local path is required')
    path = Path(value).expanduser()
    require(path.is_absolute() and not path.is_symlink() and path.absolute() == path.resolve(), 'absolute non-symlink path required')
    return path


def _json(path, maximum=MAX_METADATA_BYTES):
    path = _path(path)
    require(path.is_file() and 0 < path.stat().st_size <= maximum, 'missing/unsupported metadata/report size')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON metadata key')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('nonfinite JSON metadata value: '+value)
    value = json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=nonfinite)
    require(isinstance(value, dict), 'JSON metadata/report must be an object')
    return value


def _anchored(record, fields=('path', 'sha256', 'size'), maximum=MAX_REPORT_BYTES):
    require(isinstance(record, dict) and set(record) == set(fields), 'exact retained file identity required')
    path = _path(record['path'])
    require(_digest(record['sha256']) and type(record['size']) is int and 0 < record['size'] <= maximum, 'invalid retained file size/hash')
    require(path.is_file() and path.stat().st_size == record['size'] and sha(path) == record['sha256'], 'retained file bytes changed')
    return path


def assert_dependencies():
    f.assert_kernel()
    require(sha(f.__file__) == PINS['fidelity'] and sha(suite.__file__) == PINS['suite'] and sha(clock.__file__) == PINS['clock'], 'frozen original authority changed')


def _receipt(record, started, root, mode):
    require(isinstance(record, dict) and set(record) == {'receipt_path', 'receipt_sha256'} and _digest(record['receipt_sha256']), 'pre-existing independent examination record required')
    path = _path(record['receipt_path'])
    require(not path.is_relative_to(root) and sha(path) == record['receipt_sha256'], 'receipt changed or placed in sealed run')
    value = _json(path)
    v2 = value.get('schema') == 'simscene.independent_full_report_custody.v2'
    require(value.get('schema') in ('simscene.independent_full_report_custody.v1', 'simscene.independent_full_report_custody.v2'), 'unknown independent receipt schema')
    expected = BASE_RECEIPT_FIELDS | ({'evaluation_started_at_utc', 'reference_prebinding', 'reference_postcheck'} if v2 else set())
    require(set(value) == expected and v2 == (mode != 'positive'), 'v1 positives / v2 contemporaneously bound controls required')
    require(suite._date(value['recorded_at_utc']) < suite._date(started), 'receipt must pre-exist aggregation')
    require(_path(value['run_directory']) == root and value['checker_orchestration_version'] == 7 and value['checker_source_sha256'] == PINS['fidelity'], 'wrong run/original checker authority')
    require(isinstance(value['role'], str) and bool(value['role']), 'explicit original examination role required')
    require(value['P3_accepted'] is False and value['P4_accepted'] is False and isinstance(value['anchor_origin'], str) and value['anchor_origin'], 'receipt cannot claim whole delivery acceptance')
    require(type(value['accepted_for_clock_query']) is bool and value['accepted_for_clock_query'] == (mode == 'positive'), 'positive/control clock scope changed')
    require(all(_digest(value[k]) for k in ('original_run_lock_sha256', 'original_evidence_lock_sha256')), 'missing original lock anchors')
    report_path = _anchored(value['full_report'])
    require(not report_path.is_relative_to(root), 'complete report must remain outside sealed run')
    return value, path, report_path


def stream_original_outputs(root, evidence, expected_result_sha256):
    """Original accepted enumeration + same result bytes implies same paths.

    This intentionally does not call evidence_integrity.verify/_artifacts,
    which parses the full original result. That enumeration was proved by the
    retained accepted evaluation. Every originally enumerated artifact is now
    streamed again under its already independently anchored lock.
    """
    require(isinstance(evidence, dict) and set(evidence) == {'result_file', 'partial', 'artifacts'} and evidence['result_file'] == 'result.json' and evidence['partial'] is False, 'complete original output manifest required')
    entries = evidence['artifacts']
    require(isinstance(entries, dict) and 1 <= len(entries) <= MAX_ARTIFACTS and 'result.json' in entries, 'unsupported output inventory')
    require(isinstance(entries['result.json'], dict) and _digest(expected_result_sha256) and entries['result.json'].get('sha256') == expected_result_sha256, 'original result anchor differs from original accepted report')
    checks, total = {}, 0
    for name, record in entries.items():
        require(isinstance(name, str), 'invalid output artifact name')
        relative = PurePosixPath(name)
        require(isinstance(name, str) and len(relative.parts) == 1 and name not in ('.', '..') and '/' not in name and '\\' not in name and relative.name == name, 'unsafe output artifact path')
        require(isinstance(record, dict) and set(record) == {'size', 'sha256'} and type(record['size']) is int and record['size'] >= 0 and _digest(record['sha256']), 'malformed output artifact record')
        total += record['size'];require(total <= MAX_ARTIFACT_BYTES, 'streaming artifact byte budget exceeded')
        path = root/name
        require(not path.is_symlink() and path.resolve().parent == root and path.is_file(), 'missing/nonlocal/symlink output artifact')
        checks[name] = path.stat().st_size == record['size'] and sha(path) == record['sha256']
        require(checks[name], 'original artifact changed: '+name)
    return {'passed': True, 'checks': checks, 'partial': False, 'total_streamed_bytes': total,
            'enumeration_scope': 'Original full accepted enumeration, same anchored result bytes, every enumerated artifact streamed; result.json was not parsed.'}


def _original_report_shape(report, case, contract, mode, steps, dt):
    require(report.get('passed') is True and report.get('mode') == mode and report.get('orchestration_version') == 7 and report.get('formal_house_accepted') is False, 'complete accepted original f7 report required')
    require(report.get('supplemental_code_sha256') == PINS['fidelity'], 'different original fidelity source')
    stock = report.get('stock', {})
    require(stock.get('passed') is True and stock.get('mode') == mode and stock.get('profile') == 'P3', 'wrong/failed original stock mode/profile')
    require(stock.get('checker_sha256') == f.KERNEL_SHA256['passive_network'] and stock.get('reused_mechanism_sha256') == f.KERNEL_SHA256['mechanism'], 'original stock kernel identity differs')
    require(isinstance(stock.get('checks'), dict) and stock['checks'] and all(value is True for value in stock['checks'].values()), 'partial/failed stock check inventory')
    require(stock.get('timeline', {}).get('passed') is True and stock.get('strict_initial_state', {}).get('passed') is True, 'original full timeline/strict t0 proof missing')
    keys = ('static_stage', 'mass_properties', 'non_contact_auxiliaries', 'original_contact_journal_reconstruction')
    require(all(isinstance(report.get(k), dict) and report[k].get('passed') is True for k in keys), 'full original all-mode fidelity evidence missing/failed')
    require({'stage_sha256', 'joints', 'rigid_bodies', 'physics_scenes', 'physics_attributes', 'forbidden_actuation_candidates', 'canonical_passive_joint_defaults', 'scope'} <= set(report['static_stage']), 'reduced original native catalog')
    require({'body_checks', 'mass_properties_by_prim_path', 'scope'} <= set(report['mass_properties']), 'reduced original cooked-mass evidence')
    require(report['non_contact_auxiliaries'].get('original_steps_examined') == steps and report['non_contact_auxiliaries'].get('contact_records') == [] and report['non_contact_auxiliaries'].get('activity_or_category_credit') is False, 'reduced original all-step auxiliary evidence')
    if mode != 'positive':
        require(isinstance(report.get('positive_fidelity_scope'), str) and report['positive_fidelity_scope'] and not any(k in report for k in ('cart', 'bridge', 'composed_mechanisms')), 'stopping controls cannot fabricate positive completion')
        require(stock.get('reference_positive_passed') is True and stock.get('same_frozen_case_as_reference') is True and stock.get('paired_runtime_configuration_matches') is True and stock.get('paired_geometry_settings_match') is True, 'original paired control proof missing')
        require(stock.get('checks', {}).get('only_frozen_isolated_scene_change') is True and stock['checks'].get('control_downstream_remains_quiet') is True, 'isolated/quiet control predicate missing')
        if mode == 'broken_rope':
            for name, definition in case['mechanism_cases'].items():
                if definition['mechanism'] != 'rope_drawer': continue
                original = stock['mechanism_cases'][name]
                require(original['status'] == 'evaluated' and original['report']['mode'] == 'detached_drawer' and original['report']['passed'] is True, 'original detached cable assertion missing')
        return
    require(report.get('nominal_configuration_matches') is True and all(report.get(k, {}).get('passed') is True for k in ('cart', 'cable', 'bridge', 'composed_mechanisms')), 'complete original positive fidelity evidence missing')
    require({'phase_steps', 'signed_net_progress_m', 'speed_qualified_forward_distance_m', 'wheels', 'scope'} <= set(report['cart']) and set(report['cart']['wheels']) == {v['body_id'] for v in contract['cart']['wheels']}, 'reduced original cart evidence')
    require({'phase_steps', 'support_callback_updates', 'callback_records', 'scope'} <= set(report['bridge']), 'reduced original bridge evidence')
    require(f.m.finite(report.get('whole_stable_confirmation_interval_s')) and report['whole_stable_confirmation_interval_s'] >= 2, 'original whole stable2second evidence missing')
    require(set(stock.get('events', {})) == set(f.p.event_definitions(case)) and set(stock.get('handoffs', {})) == {v['id'] for v in case['handoffs']}, 'complete event/handoff report required')
    require(all(v.get('passed') is True for v in stock['handoffs'].values()), 'failed original handoff')
    require(set(stock.get('tiles', {})) == set(case['tiles']['ids']) and stock.get('actual_tipped_tile_count') == len(case['tiles']['ids']) and stock.get('actual_final_tipped_tile_count') == len(case['tiles']['ids']), 'named first/final tile evidence missing')
    require(set(stock.get('household_categories', {})) == set(case['household_categories']), 'complete household evidence required')
    terminal = stock.get('terminal', {});flags = terminal.get('whole_sugar_inside_per_step')
    require(terminal.get('passed') is True and isinstance(flags, list) and len(flags) == steps and all(type(v) is bool for v in flags), 'complete original terminal mask required')
    require(next((i for i, value in enumerate(flags, 1) if value), None) == terminal['first_whole_entry_step'], 'first original entry/mask mismatch')
    require(stock.get('activity', {}).get('passed') is True, 'original activity absent/failed')
    end = terminal['first_whole_entry_step']
    require(clock.prefixes(stock, case, end, end, dt)['passed'], 'complete original unchanged stock mask/clock required')
    modules = report['composed_mechanisms']
    require(set(modules.get('mechanisms', {})) == set(contract['composed_mechanisms']), 'complete original composed reports required')
    for name, definition in contract['composed_mechanisms'].items():
        original = modules['mechanisms'][name]
        require(original.get('passed') is True and all(v is True for v in original.get('checks', {}).values()), 'failed original composed assertion')
        raw = original.get('raw_p1_report', {})
        require(all(f.composed.inspect_raw(raw, definition['mechanism_case']).values()), 'full unchanged raw P1 check/contact inventory missing')
        require(isinstance(raw.get('motion_per_step'), list) and [v.get('step') for v in raw['motion_per_step']] == list(range(1, steps+1)) and raw.get('timeline', {}).get('physics_dt_s') == dt, 'original raw P1 per-step report was reduced or rebased')


def _load_one(root, contract_path, review_path, freeze_path, record, mode, started, software, additional):
    receipt, receipt_path, report_path = _receipt(record, started, root, mode)
    require(sha(root/'run-lock.json') == receipt['original_run_lock_sha256'] and sha(root/'evidence-lock.json') == receipt['original_evidence_lock_sha256'], 'original lock anchors changed')
    report = _json(report_path, MAX_REPORT_BYTES)
    require(_path(report.get('run_directory', '')) == root and report.get('run_lock_sha256') == receipt['original_run_lock_sha256'] and report.get('evidence_lock_sha256') == receipt['original_evidence_lock_sha256'], 'full report belongs to different original locks/run')
    require(receipt['full_summary'].get('passed') is True and receipt['full_summary'].get('mode') == mode and receipt['full_summary'].get('individual_report') == receipt['full_report'], 'reduced/failed/mismatched custody summary')
    require(report.get('supplemental_contract_sha256') == sha(contract_path), 'original contract changed')
    chronology = suite.verify_freeze(freeze_path, contract_path, review_path, root, additional)
    freeze = _json(freeze_path)
    require(isinstance(freeze.get('files_sha256'), dict) and 1 <= len(freeze['files_sha256']) <= MAX_ARTIFACTS, 'unsupported prejob source/contract closure')
    for filename, digest in freeze['files_sha256'].items():
        path = _path(filename)
        require(_digest(digest) and path.is_file() and sha(path) == digest, 'prejob static/source dependency changed')
    lock, spec, case = _json(root/'run-lock.json'), _json(root/'spec.json'), _json(contract_path)
    require(all(key in lock for key in f.m.PAIRED_MANIFEST_FIELDS), 'all original thirteen runtime fields are required')
    contract = case;case_path = root/lock.get('acceptance_case_file', '')
    require(case_path.name in ('acceptance-case.json', 'acceptance-case.yaml', 'acceptance-case.yml'), 'original case snapshot missing')
    require(case_path.suffix == '.json', 'retained reader currently supports JSON case bytes only')
    case = _json(case_path)
    require(sha(case_path) == lock.get('acceptance_case_sha256') == contract['network_case_sha256'], 'original pinned case changed')
    review = _json(review_path)
    require(sha(review_path) == contract['static_review_sha256'] and review.get('passed') is True and review.get('network_case_sha256') == contract['network_case_sha256'] and review.get('nominal_configuration_sha256') == contract['nominal_configuration_sha256'], 'original independent static review changed')
    f.validate_contract(contract, case, lock['physics_dt_s'])
    prefix = 'server/vendor/simscene/'
    expected = {n[len(prefix):]:digest for n, digest in software['installed_package_files_sha256'].items() if n.startswith(prefix)}
    require(expected and lock.get('worker_code_sha256') == expected, 'actual complete worker package differs from frozen installed package')
    metadata = report.get('suite_metadata', {})
    require(metadata.get('passed') is True and _path(metadata.get('root', '')) == root and metadata.get('lock') == lock and metadata.get('case') == case, 'complete original suite metadata changed/missing')
    anchors = metadata.get('evidence_sha256', {})
    require(anchors.get('run-lock.json') == receipt['original_run_lock_sha256'] and anchors.get('evidence-lock.json') == receipt['original_evidence_lock_sha256'], 'independently retained full-report anchors disagree')
    evidence = _json(root/'evidence-lock.json')
    outputs = stream_original_outputs(root, evidence, anchors.get('result.json'))
    original = metadata.get('integrity', {})
    require(original.get('input_integrity', {}).get('passed') is True and original.get('output_integrity', {}).get('passed') is True and original['output_integrity'].get('partial') is False and original['output_integrity'].get('checks') == outputs['checks'] and original.get('case_pinned_to_run') is True and original.get('worker_snapshot_pinned') is True, 'original complete input/output enumeration proof missing')
    inputs = verify_inputs(root)
    require(inputs['passed'] is True and inputs == original['input_integrity'], 'original input/snapshot/runtime/asset closure changed')
    data = {'passed': True, 'root': root, 'spec': spec, 'lock': lock}
    identities = f.sealed_identities(data);canonical = f.canonical_spec(spec, identities)
    require(identities == metadata.get('verified_asset_identities') and canonical == metadata.get('canonical_spec'), 'actual verified asset identities/source configuration changed')
    if mode == 'positive': require(f.canonical_sha(canonical) == contract['nominal_configuration_sha256'], 'actual nominal configuration differs')
    cameras = {n: copy.deepcopy(obj) for n, obj in spec['objects'].items() if obj.get('kind') == 'camera'}
    require(metadata.get('native_metadata', {}).get('spec') == {'objects': cameras}, 'original native camera configuration differs')
    steps = lock.get('requested_physics_steps')
    require(type(steps) is int and 0 < steps <= 20000 and report['stock']['case_sha256'] == contract['network_case_sha256'], 'unsupported original step count or case identity')
    _original_report_shape(report, case, contract, mode, steps, lock['physics_dt_s'])
    dynamic = {f.m.path(n) for n, obj in spec['objects'].items() if obj.get('dynamic')}
    mass = report['mass_properties']
    require(set(mass['body_checks']) == dynamic and all(value is True for value in mass['body_checks'].values()) and set(mass['mass_properties_by_prim_path']) == dynamic, 'original full-body cooked mass catalog was reduced')
    require(report['static_stage']['stage_sha256'] == lock['stage_sha256'], 'original native catalog belongs to different stage')
    require(sha(receipt_path) == record['receipt_sha256'] and sha(report_path) == receipt['full_report']['sha256'] and sha(root/'run-lock.json') == receipt['original_run_lock_sha256'] and sha(root/'evidence-lock.json') == receipt['original_evidence_lock_sha256'], 'custody changed during revalidation')
    proof = {'schema': SCHEMA, 'passed': True, 'original_report': copy.deepcopy(receipt['full_report']), 'original_full_report_sha256': receipt['full_report']['sha256'], 'examination_record': copy.deepcopy(record),
        'mode': mode, 'run_directory': str(root), 'original_lock_sha256': {'run-lock.json': receipt['original_run_lock_sha256'], 'evidence-lock.json': receipt['original_evidence_lock_sha256'], 'result.json': anchors['result.json']},
        'input_integrity': inputs, 'streamed_outputs': outputs, 'original_freeze_chronology': chronology,
        'verified_asset_identities_match': True, 'canonical_metadata_matches': True, 'entire_worker_package_matches_software_freeze': True,
        'original_raw_result_parsed': False, 'physics_recomputed': False,
        'scope': 'Memoized prior independent complete original f7 evaluation on unchanged closed bytes. Not a monolithic suite7 rerun, new physical decision or prejob-frozen aggregation authority.'}
    return report, proof, receipt


def _reference(prebinding, postcheck, reference, root, mode, started, evaluation_started, original_stock):
    require(isinstance(prebinding, dict) and set(prebinding) == {'path', 'sha256'} and _digest(prebinding['sha256']), 'reference prebinding missing/changed')
    path = _path(prebinding['path']);require(sha(path) == prebinding['sha256'], 'reference prebinding bytes changed')
    binding = _json(path)
    require(set(binding) == PREBIND_FIELDS and binding['schema'] == 'simscene.independent_reference_prebinding.v1', 'exact original reference prebinding required')
    require(_path(binding['current_run_directory']) == root and binding['mode'] == mode and _path(binding['reference_run_directory']) == Path(reference['root']), 'reference prebinding belongs to different invocation')
    require(binding['reference_record'] == reference['record'] and binding['reference_full_report'] == reference['receipt']['full_report'], 'reference report/custody identity changed')
    for name in ('run_lock', 'evidence_lock', 'result'):
        require(binding['reference_'+name+'_sha256'] == reference['anchors'][name], 'reference original byte anchors changed')
    certificate_path = _anchored(binding['reference_clock_certificate'], maximum=MAX_METADATA_BYTES)
    certificate = _json(certificate_path)
    require(certificate.get('schema') == clock.SCHEMA and certificate.get('errors') == [] and all(certificate.get(k) is True for k in ('file_integrity_verified', 'geometry_queries_complete', 'bounded_timing_floors_passed', 'physical_entry_no_escape_complete', 'inner_no_escape', 'supplemental_complete')), 'prior reference physical clock is incomplete')
    provenance = certificate.get('provenance', {})
    require(provenance.get('helper_sha256') == PINS['clock'] and provenance.get('independently_retained_full_report_sha256') == reference['receipt']['full_report']['sha256'] and provenance.get('independently_retained_lock_sha256') == {'run-lock.json': reference['anchors']['run_lock'], 'evidence-lock.json': reference['anchors']['evidence_lock']}, 'reference clock uses different original report/locks')
    require(provenance.get('original_files_sha256', {}).get('result.json') == reference['anchors']['result'] and provenance.get('full_report_path') == reference['receipt']['full_report']['path'], 'reference clock belongs to different original result/report path')
    bounds = certificate.get('actual_first_entry_observed_step_bounds_inclusive')
    require(isinstance(bounds, list) and len(bounds) == 2 and type(bounds[0]) is int and bounds[0] == bounds[1], 'reference physical entry bounds must collapse')
    end = bounds[0];metadata = reference['metadata']
    require(certificate.get('original_stock_entry_step') == original_stock['terminal']['first_whole_entry_step'] and certificate.get('inner_first_entry', {}).get('physics_steps') == certificate.get('outer_first_entry', {}).get('physics_steps') == end, 'reference clock entry boundaries differ')
    prefix = clock.prefixes(original_stock, metadata['case'], end, end, metadata['lock']['physics_dt_s'])
    require(prefix['passed'] and prefix == certificate.get('every_possible_original_prefix'), 'reference clock differs from complete original flags')
    require(suite._date(reference['receipt']['recorded_at_utc']) < suite._date(binding['created_at_utc']) < suite._date(evaluation_started), 'reference binding must precede control evaluation, not be added later')
    require(isinstance(postcheck, dict) and set(postcheck) == {'completed_at_utc', 'unchanged', 'anchors'} and postcheck['unchanged'] is True and set(postcheck['anchors']) == ANCHOR_FIELDS, 'contemporaneous reference postcheck required')
    expected = {'receipt_sha256': reference['record']['receipt_sha256'], 'full_report_sha256': reference['receipt']['full_report']['sha256'], 'run_lock_sha256': reference['anchors']['run_lock'], 'evidence_lock_sha256': reference['anchors']['evidence_lock'], 'result_sha256': reference['anchors']['result'], 'clock_certificate_sha256': binding['reference_clock_certificate']['sha256']}
    require(postcheck['anchors'] == expected and suite._date(evaluation_started) <= suite._date(postcheck['completed_at_utc']) <= suite._date(started), 'reference before/after proof inconsistent')
    return {'passed': True, 'prebinding_path': str(path), 'prebinding_sha256': prebinding['sha256'], 'reference_anchors': expected,
            'clock_path': str(certificate_path), 'physical_prefix_recomputed_from_original_flags': True}


def load_retained(directory, contract_path, static_review_path, freeze_path, examination_record, *,
                  mode='positive', reference_run=None, reference_record=None,
                  aggregation_started_at_utc, software_freeze_path, additional_files=()):
    """Return the COMPLETE old report and proof; caller owns all final gates.

    No actual candidate may be queried through this new API before its joint
    generic freeze/review. Its aggregation freeze is explicitly later than
    original prejob f7/clock contracts and cannot replace their authority.
    """
    assert_dependencies();suite._date(aggregation_started_at_utc)
    require(mode in f.p.MODES, 'unknown original evaluation mode')
    root = _path(directory);require(root.is_dir(), 'missing original run directory')
    f.assert_software_freeze(software_freeze_path);software = _json(software_freeze_path)
    paths = [_path(v) for v in (contract_path, static_review_path, freeze_path)]
    reference = None
    if mode == 'positive':
        require(reference_run is None and reference_record is None, 'positive cannot borrow reference custody')
    else:
        require(reference_run is not None and reference_record is not None, 'control requires pre-existing exact positive reference proof')
        reference_root = _path(reference_run);require(reference_root != root, 'control cannot reference itself')
        early_receipt, _, _ = _receipt(examination_record, aggregation_started_at_utc, root, mode)
        old, proof, receipt = _load_one(reference_root, *paths, reference_record, 'positive', aggregation_started_at_utc, software, ())
        reference = {'root': str(reference_root), 'record': copy.deepcopy(reference_record), 'receipt': receipt,
                     'anchors': {'run_lock': proof['original_lock_sha256']['run-lock.json'], 'evidence_lock': proof['original_lock_sha256']['evidence-lock.json'], 'result': proof['original_lock_sha256']['result.json']},
                     'metadata': copy.deepcopy(old['suite_metadata'])}
        require(suite._date(early_receipt['reference_postcheck']['completed_at_utc']) <= suite._date(early_receipt['recorded_at_utc']), 'postcheck cannot follow issuance')
        reference_proof = _reference(early_receipt['reference_prebinding'], early_receipt['reference_postcheck'], reference, root, mode, early_receipt['recorded_at_utc'], early_receipt['evaluation_started_at_utc'], old['stock'])
        del old;gc.collect()
    report, proof, receipt = _load_one(root, *paths, examination_record, mode, aggregation_started_at_utc, software, additional_files)
    if reference is not None:
        require(receipt == early_receipt, 'current reference receipt changed during revalidation')
        proof['reference'] = reference_proof
        current, previous = report['suite_metadata'], reference['metadata']
        require(all(current['lock'].get(k) == previous['lock'].get(k) for k in f.m.PAIRED_MANIFEST_FIELDS) and current['geometry_settings'] == previous['geometry_settings'], 'original paired runtime/geometry scope changed')
        require(f.p.isolated_control_spec(current['canonical_spec'], previous['canonical_spec'], current['case'], mode), 'current exact verified reference isolation differs')
        require(sha(Path(reference['root'])/'run-lock.json') == reference['anchors']['run_lock'] and sha(Path(reference['root'])/'evidence-lock.json') == reference['anchors']['evidence_lock'] and sha(Path(reference['root'])/'result.json') == reference['anchors']['result'] and sha(reference['record']['receipt_path']) == reference['record']['receipt_sha256'], 'reference custody changed during aggregation')
        require(sha(reference_proof['prebinding_path']) == reference_proof['prebinding_sha256'] and sha(reference_proof['clock_path']) == reference_proof['reference_anchors']['clock_certificate_sha256'], 'reference clock/prebinding changed during revalidation')
    proof['retained_report_schema'] = receipt['schema'];proof['helper_sha256'] = sha(__file__)
    proof['aggregation_started_at_utc'] = aggregation_started_at_utc
    proof['software_freeze_sha256'] = sha(software_freeze_path)
    return report, proof
