"""Sealed-file adapter for the immutable P1 physical mechanism evaluator.

Only verified acquired snapshot relocation is normalized, on a copy of the
reference spec. The current spec and all observations reach ce05 unchanged.
Direct mechanism.evaluate/verify_run remain byte-identical and strict.
"""
import hashlib
from pathlib import Path

from . import mechanism as m
from .asset_snapshots import paired_reference
from .passive_network import _read_locked


def verify_run(directory, case_path=None, mode='positive', reference_run=None):
    if mode not in ('positive', 'detached_drawer'):
        raise ValueError('unknown mechanism mode')
    data = _read_locked(directory, case_path, m.validate_case)
    integrity = data['integrity']
    integrity['checker_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    integrity['runtime_worker_snapshot_pinned'] = integrity['worker_snapshot_pinned']
    integrity['adapter_scope'] = 'Sealed-file provenance and acquired asset relocation; unchanged ce05 physical predicates.'
    if not data['passed']:
        return {'passed': False, 'mode': mode, **integrity, 'scope': 'Input/output provenance failed; telemetry was not accepted.'}
    reference_spec = None
    if mode != 'positive' or reference_run is not None:
        if reference_run is None:
            raise ValueError('detached_drawer requires a positive reference run')
        reference = _read_locked(reference_run, case_path, m.validate_case)
        integrity['reference_integrity_passed'] = reference['passed']
        if not reference['passed']:
            return {'passed': False, 'mode': mode, **integrity, 'scope': 'Positive reference provenance failed.'}
        integrity['reference_run'] = str(reference['root'])
        integrity['same_frozen_case_as_reference'] = integrity['case_sha256'] == reference['integrity']['case_sha256']
        integrity['paired_manifest_fields_match'] = {k: k in data['lock'] and k in reference['lock'] and data['lock'][k] == reference['lock'][k] for k in m.PAIRED_MANIFEST_FIELDS}
        integrity['paired_runtime_configuration_matches'] = all(integrity['paired_manifest_fields_match'].values())
        cfg, refcfg = (v['run'].get('mechanism_configuration', {}) for v in (data, reference))
        present = 'geometry_settings' in cfg or 'geometry_settings' in refcfg
        integrity['paired_geometry_settings_match'] = not present or isinstance(cfg.get('geometry_settings'), dict) and isinstance(refcfg.get('geometry_settings'), dict) and cfg['geometry_settings'] == refcfg['geometry_settings']
        positive = m.evaluate(reference['run'], reference['spec'], reference['case'], dt=reference['lock'].get('physics_dt_s', 1/60))
        integrity['reference_positive_passed'] = positive['passed']
        reference_spec, integrity['paired_asset_snapshots'] = paired_reference(data, reference)
    report = m.evaluate(data['run'], data['spec'], data['case'], mode, reference_spec, data['lock'].get('physics_dt_s', 1/60))
    report.update(integrity)
    report['passed'] = bool(report['passed'] and all(integrity.get(k, True) for k in ('same_frozen_case_as_reference', 'paired_runtime_configuration_matches', 'paired_geometry_settings_match', 'reference_positive_passed')) and integrity.get('paired_asset_snapshots', {}).get('passed', True))
    if mode == 'positive':
        report['paired_control_required_for_causal_acceptance'] = data['case']['mechanism'] == 'rope_drawer'
    elif report['passed']:
        report['paired_causal_acceptance'] = True
        report['wrapped_pulley_success'] = report.get('rope_model') == 'segmented_over_free_pulley'
    return report
