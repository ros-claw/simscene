"""Aggregate independently retained full original examinations on unchanged bytes.

This is explicitly post-job delivery/computation orchestration. It neither
claims a suite8 rerun nor changes any pre-job physical or timing authority.
"""
import argparse
import datetime
import gc
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import whole_home_suite_v9 as original
from experiments import retained_report_integrity_v3 as retained
from experiments import bounded_entry_clock_v6 as entry

f = original.f
require = f.require
SCHEMA = 'simscene.retained_whole_home_suite.v3'
ORIGINAL_SUITE_SHA256 = '1d40de426d0f0d85ba968a25d7da61c7e927725fbfa3ca895d1f0a50b35b5dc3'
ORIGINAL_CLOCK_SHA256 = 'd60ce3423b8b25f22372399656be5e6b7459542464c6d1a6626d90c9a855e102'
_load, verify_freeze = original._load, original.verify_freeze
compare_variant, compare_variant_contract = original.compare_variant, original.compare_variant_contract
consecutive_three, check_attempt_inventory = original.consecutive_three, original.check_attempt_inventory
verify_native, save_run_report = original.verify_native, original.save_run_report


def assert_dependencies():
    f.assert_kernel()
    entry.assert_dependencies()
    require(f.sha(original.__file__) == ORIGINAL_SUITE_SHA256 and
            f.sha(entry.__file__) == ORIGINAL_CLOCK_SHA256, 'original frozen gate/clock source changed')


def verify_generic_freeze(manifest, started):
    path = Path(manifest['aggregator_freeze_path']).resolve()
    require(f.sha(path) == manifest['aggregator_freeze_sha256'], 'aggregator generic freeze changed')
    freeze = _load(path)
    require(freeze.get('schema') == 'simscene.retained_aggregation_generic_freeze.v1', 'explicit aggregation generic freeze required')
    require(original._date(freeze['frozen_at_utc']) < original._date(started), 'generic aggregation freeze must predate this application')
    for module in (__file__, retained.__file__, original.__file__, f.__file__, entry.__file__):
        key = str(Path(module).resolve())
        require(freeze.get('source_files_sha256', {}).get(key) == f.sha(key), 'aggregation freeze omits/changes source '+key)
    return {'passed': True, 'generic_freeze_sha256': f.sha(path),
            'scope': 'Frozen before this aggregation query, not asserted to predate physical jobs.'}


def physical_entry_clock(report, examination_record, certificate_record, directory, clock_path,
                         original_csv, started, *, write_csv):
    """Rescore unchanged original CSV at certified physical E, not stock S."""
    require(set(certificate_record) == {'path', 'sha256'}, 'pin the original complete clock6 certificate')
    path = Path(certificate_record['path']).resolve()
    require(f.sha(path) == certificate_record['sha256'], 'original clock6 certificate changed')
    certificate = _load(path)
    require(certificate.get('schema') == entry.SCHEMA and certificate.get('errors') == [] and
            all(certificate.get(name) is True for name in ('file_integrity_verified', 'supplemental_complete',
                'geometry_queries_complete', 'bounded_timing_floors_passed', 'physical_entry_no_escape_complete', 'inner_no_escape')),
            'original complete physical-entry/no-escape certificate required')
    receipt = _load(examination_record['receipt_path'])
    require(f.sha(examination_record['receipt_path']) == examination_record['receipt_sha256'] and
            original._date(receipt['recorded_at_utc']) < original._date(started), 'independent receipt must already exist')
    provenance = certificate['provenance'];root = Path(directory).resolve()
    require(provenance['helper_sha256'] == ORIGINAL_CLOCK_SHA256 and
            provenance['independently_retained_full_report_sha256'] == receipt['full_report']['sha256'] and
            f.sha(provenance['full_report_path']) == receipt['full_report']['sha256'], 'clock certificate belongs to another original report/helper')
    expected = {'run-lock.json': report['run_lock_sha256'], 'evidence-lock.json': report['evidence_lock_sha256'],
                'result.json': report['suite_metadata']['evidence_sha256']['result.json'],
                'spec.json': report['suite_metadata']['lock']['spec_sha256']}
    require(provenance['original_files_sha256'] == expected and
            provenance['independently_retained_lock_sha256'] == {k:expected[k] for k in ('run-lock.json','evidence-lock.json')},
            'clock original run/evidence/result/spec anchors differ')
    external = provenance['external_files_sha256']
    require(isinstance(external, dict) and len(external) == 6 and
            all(Path(name).is_file() and f.sha(name) == digest for name,digest in external.items()), 'clock frozen external inputs changed')
    documents = {name:_load(name) for name in external}
    freezes = [(name,value) for name,value in documents.items() if value.get('schema') == 'simscene.bounded_entry_clock_freeze.v1']
    contracts = [value for value in documents.values() if value.get('schema') == entry.SCHEMA]
    require(len(contracts)==1, 'one original bounded-clock contract required')
    contract=contracts[0]
    require(contract['case_sha256']==report['stock']['case_sha256'] and
            {contract['case_sha256'],contract['inner_contract_sha256'],contract['outer_contract_sha256'],
             contract['static_review_sha256']} <= set(external.values()), 'clock external role bindings differ')
    cases=[value for name,value in documents.items() if external[name]==contract['case_sha256']]
    reviews=[value for name,value in documents.items() if external[name]==contract['static_review_sha256']]
    require(len(cases)==len(reviews)==1 and cases[0]==report['suite_metadata']['case'] and
            reviews[0].get('scope')=='independent_static_inner_outer_entry_bounds' and
            all(reviews[0].get(k) is True for k in ('passed','inner_inside_physical_cavity','physical_cavity_inside_outer')),
            'clock static cavity/case premises differ')
    require(len(freezes) == 1 and original._date(freezes[0][1]['frozen_at_utc']) <
            original._date(report['suite_metadata']['lock']['created_at_utc']), 'original clock binding must predate the physical job')
    freeze_path,freeze=freezes[0]
    required_paths={name for name in external if name!=freeze_path}|{
        str(Path(module).resolve()) for module in (entry.__file__,entry.h.__file__,f.__file__)}
    require(required_paths <= set(freeze.get('files_sha256',{})) and
            all(freeze['files_sha256'][name]==f.sha(name) for name in required_paths),
            'original clock freeze omits source/case/contracts')
    require(all(Path(name).is_file() and f.sha(name) == digest for name,digest in freeze['files_sha256'].items()) and
            isinstance(reviews[0].get('files_sha256'),dict) and bool(reviews[0]['files_sha256']) and
            all(Path(name).is_file() and f.sha(name)==digest for name,digest in reviews[0]['files_sha256'].items()),
            'original clock source/static proof closure changed')
    bounds = certificate['actual_first_entry_observed_step_bounds_inclusive']
    require(isinstance(bounds,list) and len(bounds)==2 and type(bounds[0]) is int and bounds[0]==bounds[1], 'physical earliest entry bounds must collapse')
    end=bounds[0];stock=report['stock'];metadata=report['suite_metadata'];case=metadata['case'];dt=metadata['lock']['physics_dt_s']
    require(certificate['original_stock_entry_step'] == stock['terminal']['first_whole_entry_step'] and
            certificate['inner_first_entry']['physics_steps'] == certificate['outer_first_entry']['physics_steps'] == end,
            'certificate entry boundaries differ')
    recomputed=entry.prefixes(stock,case,end,end,dt)
    require(recomputed == certificate['every_possible_original_prefix'] and recomputed['passed'], 'certificate differs from the unchanged original flags/prefix clock')
    result={'passed':True, 'original_certificate':str(path), 'certificate_sha256':certificate_record['sha256'],
            'original_full_report_sha256':receipt['full_report']['sha256'], 'physical_entry_step':end,
            'original_stock_entry_step':stock['terminal']['first_whole_entry_step'],
            'metrics':recomputed['prefixes'][0]['metrics'], 'scope':'Physical entry E is authoritative; stock S clock is auxiliary. Original flags are unchanged.'}
    if write_csv:
        require(f.sha(clock_path) == f.CLOCK_SHA256, 'provided user clock changed')
        loader=importlib.util.spec_from_file_location('retained_aggregation_user_clock',clock_path)
        clock=importlib.util.module_from_spec(loader);loader.loader.exec_module(clock)
        # The provided clock deliberately rejects extra rows. Select a
        # byte-identical prefix into a NEW file; keep the full stock CSV intact.
        source_bytes=Path(original_csv).read_bytes()
        lines=source_bytes.splitlines(keepends=True)
        count=end-case['release_step']
        require(len(lines)==stock['activity']['metrics']['window_end_step']-case['release_step']+1,
                'original stock CSV row count differs')
        physical_csv=Path(original_csv).with_name(Path(original_csv).stem+'.physical-entry.csv')
        with physical_csv.open('xb') as stream:
            stream.write(b''.join(lines[:count+1]))
        with physical_csv.open(newline='') as stream:
            measured=clock.intervals(stream,case['release_step'],end,1/dt)
        require(Path(original_csv).read_bytes()==source_bytes, 'original stock CSV changed during prefix export')
        metrics=result['metrics'];expected_clock={'span_s':metrics['chain_duration_s'],
            'net_progress_s':metrics['net_effective_action_s'],'fraction':metrics['motion_occupancy'],
            'longest_idle_s':metrics['maximum_idle_s']}
        require(all(math.isclose(measured[k],v,abs_tol=1e-10,rel_tol=1e-10) for k,v in expected_clock.items()), 'unchanged CSV physical-prefix clock differs')
        result.update(original_stock_csv=str(Path(original_csv).resolve()),original_stock_csv_sha256=f.sha(original_csv),
                      physical_prefix_csv=str(physical_csv.resolve()),physical_prefix_csv_sha256=f.sha(physical_csv),
                      prefix_rows_byte_identical=True,
                      provided_clock_sha256=f.sha(clock_path),interval_start_inclusive=case['release_step'],
                      interval_end_exclusive=end,user_clock_metrics=measured)
    return result


def verify_suite(manifest):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    assert_dependencies()
    verify_generic_freeze(manifest, started)
    required = {'schema', 'software_freeze_path', 'contract_path', 'static_review_path', 'freeze_path', 'positive_runs', 'controls', 'variant', 'replay', 'attempt_ledger_path', 'formal_runs_roots', 'native_cameras', 'native_positive_index', 'clock_directory', 'provided_clock_path', 'retained_examinations', 'bounded_entry_certificates', 'aggregator_freeze_path', 'aggregator_freeze_sha256'}
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
    memoized, physical_clocks = {}, {}
    require(set(manifest['retained_examinations']) == set(names), 'all eight original examinations required')
    require(set(manifest['bounded_entry_certificates']) == {'positive_1', 'positive_2', 'positive_3', 'variant', 'replay'}, 'exactly five original physical-entry certificates required')
    native = {'passed': False, 'scope': 'Selected positive did not provide accepted completion evidence.'}

    def process(name, directory, contract_path, review_path, freeze_path, mode='positive', reference=None, additional_files=()):
        nonlocal native
        verify_freeze(freeze_path, contract_path, review_path, directory, additional_files)
        current, proof = retained.load_retained(directory, contract_path, review_path, freeze_path,
            manifest['retained_examinations'][name], mode=mode, reference_run=reference,
            reference_record=manifest['retained_examinations']['positive_1'] if reference else None,
            aggregation_started_at_utc=started, additional_files=additional_files,
            software_freeze_path=manifest['software_freeze_path'])
        memoized[name] = proof
        metadata = current.get('suite_metadata', {'passed': False})
        if mode == 'positive':
            physical_clocks[name] = physical_entry_clock(current, manifest['retained_examinations'][name],
                manifest['bounded_entry_certificates'][name], directory, manifest['provided_clock_path'],
                clock_root/(name+'.csv'), started, write_csv=False)
        if mode == 'positive':
            if current.get('stock', {}).get('passed') and metadata['passed']:
                clocks[name] = {'passed': True, **f.export_motion_csv(current['stock'], metadata['case'], clock_root/(name+'.csv'), manifest['provided_clock_path'], metadata['lock']['physics_dt_s'])}
                if name == 'positive_'+str(manifest['native_positive_index']+1):
                    native = verify_native(directory, manifest['native_cameras'], current['stock'], _metadata=metadata['native_metadata'])
            else:
                clocks[name] = {'passed': False, 'scope': 'Failed physical report; no valid completion clock asserted.'}
        reports[name] = save_run_report(current, report_root/(name+'.json'))
        require(reports[name]['individual_report']['sha256'] == proof['original_full_report_sha256'], 'full original report copy differs; never normalize or reduce it')
        if mode == 'positive':
            physical_clocks[name] = physical_entry_clock(current, manifest['retained_examinations'][name],
                manifest['bounded_entry_certificates'][name], directory, manifest['provided_clock_path'],
                clock_root/(name+'.csv'), started, write_csv=True)
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
    external_changed = compare_variant_contract(_load(manifest['contract_path']), _load(variant['contract_path']), _load(variant['declaration_path']))
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
              'exact_frozen_variant': changed['passed'] and external_changed['passed'], 'all_formal_attempts_retained': inventory['passed'], 'new_directory_editable_replay_preflight': bool(export_ok), 'native_same_run_main_and_tracking': native['passed'], 'all_exact_half_open_clocks_exported': all(c['passed'] for c in clocks.values())}
    checks['all_original_examinations_memoized_with_complete_closure'] = len(memoized) == 8 and all(value['passed'] for value in memoized.values())
    checks['all_five_original_physical_entry_clocks_complete'] = len(physical_clocks) == 5 and all(value['passed'] for value in physical_clocks.values())
    return {'execution_mode': 'retained_original_report_aggregation', 'original_suite8_rerun': False,
            'aggregation_started_at_utc': started, 'memoization_proofs': memoized, 'physical_entry_clocks': physical_clocks,
            'passed': all(checks.values()), 'physics_suite_accepted': all(checks.values()), 'complete_delivery_accepted': False, 'orchestration_version': f.ORCHESTRATION_VERSION, 'checks': checks, 'paired_manifests': manifest_matches,
            'runs': reports, 'variant_comparison': changed, 'variant_external_contract_comparison': external_changed, 'attempt_inventory': inventory, 'native': native, 'motion_clocks': clocks, 'software': software,
            'memory_scope': 'Sequential reuse of complete independently retained original f9 reports, all original input/output bytes revalidated. No raw physics recomputation or data truncation; original suite8 remains available.',
            'scope': 'One designed full-house configuration, three clean consecutive repeats, exact controls, one predeclared variant and editable new-directory replay. Not randomized robustness, calibrated 3D cable, automatic visual approval or permission to publish.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest');parser.add_argument('--output',required=True)
    args=parser.parse_args();output=Path(args.output)
    require(not output.exists(),'preserve existing aggregation reports')
    result=verify_suite(_load(args.manifest))
    with output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'passed':result['passed'],'execution_mode':result['execution_mode'],'output':str(output)}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
