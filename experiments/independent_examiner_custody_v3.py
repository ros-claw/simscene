"""Record an original independent f9 evaluation and a separate original clock6.

Only bookkeeping/orchestration. No scene commands, new physical decisions or
retroactive reference binding. Do not apply before independent formal release.
"""
import argparse
import copy
import datetime
import gc
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments import retained_report_integrity_v3 as retained
from experiments import retained_whole_home_suite_v3 as aggregate

f, suite, clock = retained.f, retained.suite, retained.clock
require, sha = f.require, f.sha
SCHEMA = 'simscene.independent_examiner_invocation.v3'
FREEZE_SCHEMA = 'simscene.independent_examiner_custody_freeze.v3'
PINS = {'retained_report_integrity': '23389dea14d563b4358810ad80f51023306d7f7a82d2755a1f7406c75828c234',
        'retained_whole_home_suite': 'f43ff0d5444a389b373abd99170dce257efbeb3bb48eaeb73c1649c8bf8d3148'}
FIELDS = frozenset('''schema mode role run_directory contract_path static_review_path freeze_path
software_freeze_path output_directory additional_files reference bounded_clock custody_freeze'''.split())
CLOCK_FIELDS = frozenset('case_path inner_path outer_path contract_path review_path freeze_path'.split())


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_new(path, value):
    """Durable exclusive JSON; never overwrite original custody or reports."""
    path = Path(path)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.'+path.name+'.partial-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, allow_nan=False);stream.write('\n')
            stream.flush();os.fsync(stream.fileno());os.link(temporary, path)
        finally: temporary.unlink(missing_ok=True)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(directory_fd)
    finally: os.close(directory_fd)
    return {'path': str(path.resolve()), 'sha256': sha(path), 'size': path.stat().st_size}


def load_config(path, expected_sha256):
    path = retained._path(path)
    require(retained._digest(expected_sha256) and sha(path) == expected_sha256, 'independently pinned invocation config required')
    value = retained._json(path)
    require(set(value) == FIELDS and value['schema'] == SCHEMA, 'complete independent invocation config required')
    require(value['mode'] in f.p.MODES and isinstance(value['role'], str) and value['role'], 'explicit mode/role required')
    require(isinstance(value['additional_files'], list) and len(value['additional_files']) == len(set(value['additional_files'])), 'distinct additional dependency paths required')
    for key in ('run_directory', 'contract_path', 'static_review_path', 'freeze_path', 'software_freeze_path', 'output_directory'):
        retained._path(value[key])
    if value['mode'] == 'positive':
        require(value['reference'] is None and isinstance(value['bounded_clock'], dict) and set(value['bounded_clock']) == CLOCK_FIELDS, 'positive has its own frozen clock and cannot borrow reference custody')
        for filename in value['bounded_clock'].values(): retained._path(filename)
    else:
        require(value['role'] == value['mode'] and value['bounded_clock'] is None, 'stopping control has no positive clock query')
        reference = value['reference']
        require(isinstance(reference, dict) and set(reference) == {'run_directory', 'examination_record', 'clock_certificate'}, 'complete prior independent reference identities required')
        retained._path(reference['run_directory'])
        require(Path(reference['run_directory']) != Path(value['run_directory']), 'control cannot reference itself')
    return value, {'path': str(path), 'sha256': expected_sha256}


def dependencies(config, config_identity):
    require(sha(config_identity['path']) == config_identity['sha256'], 'invocation config changed')
    retained.assert_dependencies();aggregate.assert_dependencies()
    require(sha(retained.__file__) == PINS['retained_report_integrity'] and sha(aggregate.__file__) == PINS['retained_whole_home_suite'], 'frozen custody dependency changed')
    identity = config['custody_freeze']
    require(isinstance(identity, dict) and set(identity) == {'path', 'sha256'} and retained._digest(identity['sha256']), 'independently pinned custody freeze required')
    path = retained._path(identity['path']);require(sha(path) == identity['sha256'], 'custody freeze changed')
    freeze = retained._json(path)
    require(freeze.get('schema') == FREEZE_SCHEMA, 'wrong custody generic freeze')
    closure = freeze.get('source_files_sha256')
    require(isinstance(closure, dict) and 1 <= len(closure) <= 100, 'bounded custody source closure required')
    modules = (__file__, retained.__file__, aggregate.__file__, f.__file__, suite.__file__, clock.__file__)
    require(all(closure.get(str(Path(p).resolve())) == sha(p) for p in modules), 'custody freeze omits/changes original orchestration')
    for filename, digest in closure.items():
        require(retained._digest(digest) and sha(retained._path(filename)) == digest, 'custody source dependency changed')
    root = retained._path(config['run_directory']);lock = retained._json(root/'run-lock.json')
    evidence = retained._json(root/'evidence-lock.json')
    require(evidence.get('partial') is False and evidence.get('result_file') == 'result.json', 'complete original seal required before evaluation')
    require(suite._date(freeze['frozen_at_utc']) < suite._date(lock['created_at_utc']), 'custody version must precede original formal snapshot; no retrospective conversion')
    chronology = suite.verify_freeze(config['freeze_path'], config['contract_path'], config['static_review_path'], root, config['additional_files'])
    declared = retained._json(config['freeze_path'])['files_sha256']
    for filename, digest in declared.items(): require(sha(retained._path(filename)) == digest, 'original prejob dependency changed')
    software = f.assert_software_freeze(config['software_freeze_path'])
    inventory = retained._json(config['software_freeze_path'])['installed_package_files_sha256'];prefix = 'server/vendor/simscene/'
    expected = {name[len(prefix):]: digest for name, digest in inventory.items() if name.startswith(prefix)}
    require(expected and lock.get('worker_code_sha256') == expected, 'entire original worker package must match installed freeze')
    inputs = retained.verify_inputs(root);require(inputs['passed'] is True, 'original current input/dependency bytes failed')
    # This is prospective before/after consistency, not a memoized decision for
    # this unevaluated run. The full original f8 still proves enumeration and
    # all physical predicates; no hash here substitutes for that evaluation.
    outputs = retained.stream_original_outputs(root, evidence, evidence['artifacts']['result.json']['sha256'])
    return {'passed': True, 'invocation_config': copy.deepcopy(config_identity), 'custody_freeze': copy.deepcopy(identity),
            'original_run_lock_sha256': sha(root/'run-lock.json'), 'original_evidence_lock_sha256': sha(root/'evidence-lock.json'),
            'prejob_freeze_chronology': chronology, 'software': software, 'input_closure': inputs, 'output_byte_consistency': outputs}


def reference_state(config):
    """Complete original reference closure, plus its full physical clock proof."""
    reference = config['reference'];started = now()
    report, proof = retained.load_retained(reference['run_directory'], config['contract_path'], config['static_review_path'],
        config['freeze_path'], reference['examination_record'], aggregation_started_at_utc=started,
        software_freeze_path=config['software_freeze_path'])
    clock_proof = aggregate.physical_entry_clock(report, reference['examination_record'], reference['clock_certificate'],
        reference['run_directory'], None, None, started, write_csv=False)
    require(clock_proof['passed'] is True, 'reference physical clock incomplete')
    receipt = retained._json(reference['examination_record']['receipt_path'])
    require(receipt['role'] == 'main_positive_1', 'all stopping controls must use the prior accepted MAIN1 reference')
    cp = retained._path(reference['clock_certificate']['path'])
    anchors = proof['original_lock_sha256']
    state = {'reference_record': copy.deepcopy(reference['examination_record']), 'reference_full_report': copy.deepcopy(receipt['full_report']),
        'reference_run_lock_sha256': anchors['run-lock.json'], 'reference_evidence_lock_sha256': anchors['evidence-lock.json'],
        'reference_result_sha256': anchors['result.json'],
        'reference_clock_certificate': {'path': str(cp), 'sha256': reference['clock_certificate']['sha256'], 'size': cp.stat().st_size}}
    del report;gc.collect()
    return state, {'byte_closure': proof, 'physical_clock': clock_proof}


def evaluate(config_path, config_sha256):
    config, identity = load_config(config_path, config_sha256)
    before = dependencies(config, identity);out = retained._path(config['output_directory'])
    root = retained._path(config['run_directory'])
    require(not out.is_relative_to(root), 'custody must remain outside original sealed run')
    require(not any((parent/'run-lock.json').is_file() for parent in (out, *out.parents)), 'custody cannot write into any sealed-run subtree')
    if config['reference'] is not None:
        require(not out.is_relative_to(retained._path(config['reference']['run_directory'])), 'custody cannot modify reference run')
    out.mkdir(parents=True, exist_ok=False)
    try:
        prior = None
        if config['reference'] is not None:
            prior, prior_proof = reference_state(config)
            write_new(out/'reference-before-proof.json', prior_proof)
            binding = {'schema': 'simscene.independent_reference_prebinding.v1', 'created_at_utc': now(),
                'current_run_directory': str(root), 'mode': config['mode'],
                'reference_run_directory': config['reference']['run_directory'], **prior}
            prebinding = write_new(out/'reference-prebinding.json', binding)
        started = now()
        if prior is not None:
            require(suite._date(binding['created_at_utc']) < suite._date(started), 'prebinding must precede original evaluation')
        write_new(out/'evaluation-start.json', {'schema': 'simscene.independent_evaluation_start.v1', 'started_at_utc': started,
            'before': before, 'mode': config['mode'], 'reference_prebinding': prebinding if prior is not None else None})
        report = f.verify_one(root, config['contract_path'], config['static_review_path'], mode=config['mode'],
            reference_run=config['reference']['run_directory'] if prior is not None else None)
        # Always retain the full original returned report, including failure.
        summary = suite.save_run_report(report, out/'full-v9-report.json')
        after = dependencies(config, identity);require(after == before, 'dependency/lock bytes changed during original evaluation')
        require(report.get('orchestration_version') == 9 and report.get('supplemental_code_sha256') == retained.PINS['fidelity'] and
            report.get('mode') == config['mode'] and Path(report['run_directory']) == root and
            report.get('run_lock_sha256') == before['original_run_lock_sha256'] and report.get('evidence_lock_sha256') == before['original_evidence_lock_sha256'], 'original report belongs to a different evaluation')
        reference_postcheck = None
        if prior is not None:
            later, later_proof = reference_state(config)
            write_new(out/'reference-after-proof.json', later_proof)
            require(later == prior and sha(prebinding['path']) == prebinding['sha256'], 'reference dependency bytes changed during evaluation')
            reference_postcheck = {'completed_at_utc': now(), 'unchanged': True, 'anchors': {
                'receipt_sha256': prior['reference_record']['receipt_sha256'], 'full_report_sha256': prior['reference_full_report']['sha256'],
                'run_lock_sha256': prior['reference_run_lock_sha256'], 'evidence_lock_sha256': prior['reference_evidence_lock_sha256'],
                'result_sha256': prior['reference_result_sha256'], 'clock_certificate_sha256': prior['reference_clock_certificate']['sha256']}}
        accepted = report.get('passed') is True
        receipt = {'schema': 'simscene.independent_full_report_custody.v2' if prior is not None else 'simscene.independent_full_report_custody.v1',
            'recorded_at_utc': now(), 'role': config['role'], 'run_directory': str(root),
            'accepted_for_clock_query': config['mode'] == 'positive' and accepted, 'full_report': summary['individual_report'],
            'original_run_lock_sha256': before['original_run_lock_sha256'], 'original_evidence_lock_sha256': before['original_evidence_lock_sha256'],
            'checker_orchestration_version': 9, 'checker_source_sha256': retained.PINS['fidelity'], 'full_summary': summary,
            'anchor_origin': 'Independent original examination; receipt/report retained before any separate clock query. Reference anchors, when present, originate in a prior independently retained accepted examination and clock.',
            'P3_accepted': False, 'P4_accepted': False}
        if prior is not None:
            receipt.update(evaluation_started_at_utc=started, reference_prebinding={'path': prebinding['path'], 'sha256': prebinding['sha256']}, reference_postcheck=reference_postcheck)
        receipt_identity = write_new(out/'independent-full-report-receipt.json', receipt)
        record = {'receipt_path': receipt_identity['path'], 'receipt_sha256': receipt_identity['sha256']}
        record_identity = write_new(out/'examination-record.json', record)
        write_new(out/'evaluation-complete.json', {'schema': 'simscene.independent_evaluation_complete.v1', 'record': record_identity,
            'original_f9_passed': accepted, 'clock_queried': False, 'after': after, 'P3_accepted': False, 'P4_accepted': False})
        return {'original_f9_passed': accepted, 'examination_record': record, 'record_file': record_identity, 'clock_queried': False}
    except BaseException as error:
        write_new(out/'evaluation-error.json', {'schema': 'simscene.independent_evaluation_error.v1', 'recorded_at_utc': now(),
            'type': type(error).__name__, 'reason': str(error), 'accepted': False, 'scope': 'Execution/custody failure; preserve any original returned full report. No accepted receipt or physical success is inferred.'})
        raise


def verify_clock(config_path, config_sha256, record_path, record_sha256):
    config, identity = load_config(config_path, config_sha256);before = dependencies(config, identity)
    require(config['mode'] == 'positive', 'stopping controls cannot query positive completion clocks')
    path = retained._path(record_path);require(sha(path) == record_sha256, 'prior independently retained examination-record anchor required')
    record = retained._json(path)
    report, proof = retained.load_retained(config['run_directory'], config['contract_path'], config['static_review_path'],
        config['freeze_path'], record, aggregation_started_at_utc=now(), software_freeze_path=config['software_freeze_path'], additional_files=config['additional_files'])
    del report;gc.collect()
    receipt = retained._json(record['receipt_path']);require(receipt['accepted_for_clock_query'] is True, 'failed report cannot acquire a clock query')
    out = retained._path(config['output_directory'])/'clock6';out.mkdir(exist_ok=False)
    c = config['bounded_clock']
    certificate = clock.verify(config['run_directory'], *[c[k] for k in ('case_path', 'inner_path', 'outer_path', 'contract_path', 'review_path', 'freeze_path')],
        receipt['full_report']['path'], receipt['full_report']['sha256'], receipt['original_run_lock_sha256'], receipt['original_evidence_lock_sha256'])
    saved = write_new(out/'certificate.json', certificate)
    after = dependencies(config, identity)
    require(after == before and sha(path) == record_sha256 and sha(record['receipt_path']) == record['receipt_sha256'] and
        sha(receipt['full_report']['path']) == receipt['full_report']['sha256'], 'original custody/dependencies changed during clock query')
    complete = certificate.get('file_integrity_verified') is True and certificate.get('supplemental_complete') is True
    write_new(out/'clock-custody-receipt.json', {'schema': 'simscene.independent_clock_custody.v1', 'recorded_at_utc': now(),
        'certificate': saved, 'examination_record': record, 'examination_record_file_sha256': record_sha256,
        'original_closure': proof, 'clock_complete': complete, 'P3_accepted': False, 'P4_accepted': False})
    return {'clock_complete': complete, 'certificate': saved}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('evaluate', 'clock'))
    parser.add_argument('--config', required=True);parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--record');parser.add_argument('--record-sha256')
    args = parser.parse_args()
    if args.command == 'evaluate':
        require(args.record is None and args.record_sha256 is None, 'evaluation cannot retrofit an old receipt')
        result = evaluate(args.config, args.config_sha256);passed = result['original_f9_passed']
    else:
        require(args.record is not None and args.record_sha256 is not None, 'clock requires a prior retained record')
        result = verify_clock(args.config, args.config_sha256, args.record, args.record_sha256);passed = result['clock_complete']
    print(json.dumps(result, allow_nan=False))
    return 0 if passed else 1


if __name__ == '__main__': raise SystemExit(main())
