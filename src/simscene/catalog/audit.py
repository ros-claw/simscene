"""Static candidate review and deterministic source-list generation.

An audit is not adapter admission or a physical validation. Candidate configs
are review artifacts only and never written back to the production registry.
"""
from dataclasses import asdict, dataclass
from datetime import date
import json
from .models import canonical_json
from .providers.hf_discovery import pinned_revision, repository_id
from .registry import load_registry


@dataclass(frozen=True)
class SourceAudit:
    repository: str
    revision: str | None
    status: str
    categories: dict
    blocking_reasons: tuple
    candidate_configuration: dict | None = None
    schema_version: int = 1
    def to_dict(self):
        return json.loads(json.dumps(asdict(self), allow_nan=False))


def audit_source(candidate, policy=None):
    """Classify access/license/layout/etc independently, without network or SDK."""
    if not isinstance(candidate, dict):
        raise ValueError('source candidate must be an object')
    canonical_json(candidate, exclude_volatile=False)
    if type(candidate.get('schema_version', 1)) is not int or candidate.get('schema_version', 1) != 1 or candidate.get('state', 'candidate') != 'candidate' or candidate.get('default_enabled', False) is not False:
        raise ValueError('audit input must be a disabled version-1 source candidate')
    for key in ('access', 'license', 'metadata_layout', 'dependencies', 'physics', 'examples'):
        if candidate.get(key) is not None and not isinstance(candidate[key], dict):
            raise ValueError(key + ' must be an object or null')
    if policy is not None and not isinstance(policy, dict):
        raise ValueError('source audit policy must be an object')
    policy = dict(policy or {})
    if set(policy) - {'usage_policy'}:
        raise ValueError('unknown source audit policy')
    usage = policy.get('usage_policy', 'review')
    if usage not in {'review', 'commercial'}:
        raise ValueError('unsupported source audit usage policy')
    repo = repository_id(candidate.get('repository'))
    blocking = []
    try:
        revision = pinned_revision(candidate.get('revision'))
    except ValueError:
        revision = None; blocking.append('immutable_revision_required')
    access = candidate.get('access') or {'visibility': 'unknown', 'gated': None, 'credentials_required': None}
    if access.get('gated') is True:
        blocking.append('source_gated_no_automatic_terms_acceptance')
    if access.get('visibility') == 'private' or access.get('credentials_required') is True:
        blocking.append('source_access_requires_review')
    license_info = candidate.get('license') or {'status': 'unknown', 'declarations': []}
    if license_info.get('status', 'unknown') not in {'unknown', 'declared', 'known', 'conflicting', 'restricted'}:
        raise ValueError('unknown candidate license status')
    formats = candidate.get('formats') or []
    if not isinstance(formats, (list, tuple)) or any(not isinstance(value, str) for value in formats):
        raise ValueError('candidate formats must be strings')
    declarations = license_info.get('declarations', [])
    if not isinstance(declarations, list) or any(not isinstance(item, str) for item in declarations):
        raise ValueError('license declarations must be strings')
    distinct = sorted(set(item.lower() for item in declarations))
    license_status = 'conflicting' if len(distinct) > 1 else license_info.get('status', 'unknown')
    if license_status in {'unknown', 'conflicting'}:
        blocking.append('license_' + license_status)
    if usage == 'commercial' and (license_status == 'restricted' or any('-nc' in item for item in distinct)):
        blocking.append('license_commercial_use_unresolved')
    layout = candidate.get('metadata_layout') or {'status': 'not_inspected', 'object_index': None}
    recognized = layout.get('status') in {'recognized_schema_prefix', 'recognized_registered_layout'}
    if not recognized:
        blocking.append('unsupported_metadata_layout')
    granularity = candidate.get('acquisition_granularity')
    if granularity is None:
        blocking.append('acquisition_granularity_unknown')
    categories = {
        'access': dict(access),
        'license': {'status': license_status, 'declarations': distinct,
                    'scope': 'repository declaration only; per-asset/component review still required'},
        'formats': {'values': list(candidate.get('formats') or []),
                    'evidence': 'inspected_root_file_extensions' if candidate.get('tree_scope') else 'unknown',
                    'codec_compatibility': 'not_verified'},
        'object_index': dict(layout),
        'acquisition_granularity': {'value': granularity,
                                    'evidence': candidate.get('granularity_evidence', 'unknown')},
        'dependencies': dict(candidate.get('dependencies') or {'status': 'unknown'}),
        'physics_declarations': {'upstream_reported': candidate.get('physics'),
                                 'evidence': 'declared' if (candidate.get('physics') or {}).get('evidence', 'unknown') != 'unknown' else 'unknown',
                                 'locally_executed': 'not_run'},
        'existing_examples': {'upstream_reported': (candidate.get('examples') or {}).get('upstream_reported'),
                              'locally_executed_by_this_audit': 0},
        'unique_object_count': None,
    }
    config = None
    # Only an implemented, registered adapter at its exact statically reviewed
    # revision may yield a review-only config. Similar filenames never create
    # a new provider and a source's old audit does not cover a new revision.
    registered = next((source for source in load_registry().sources
                       if source.repository == repo and source.adapter in {'abo', 'hf_manifest', 'usdcraft'}), None)
    if registered is not None and revision and recognized and layout.get('adapter') == registered.adapter:
        if distinct and distinct != [registered.license_policy['license'].lower()]:
            blocking.append('license_conflicts_with_registered_source')
        if layout.get('object_index') != registered.metadata_entries[0].path:
            blocking.append('undeclared_metadata_index')
        if revision == registered.metadata_entries[0].revision and not any(reason.startswith(('license_', 'source_gated', 'source_access', 'undeclared_')) for reason in blocking):
            config = registered.to_dict()
            config['access'] = dict(access)
            config.update(state='candidate', default_enabled=False, checked_at=date.today().isoformat())
            config['evidence'] = [{'scope': 'discovery_static_review', 'runtime_validation': 'not_run',
                                   'note': 'Known adapter/schema review only; this candidate is not a new physical acceptance record.'}]
        elif revision != registered.metadata_entries[0].revision:
            blocking.append('new_revision_requires_metadata_schema_audit')
    elif recognized and revision:
        blocking.append('adapter_not_admitted')
    # Upstream claims are copied as declarations, never upgraded by static review.
    categories['physics_declarations']['locally_verified_by_this_audit'] = False
    status = 'candidate_review' if config is not None else 'unsupported_metadata_layout' if 'unsupported_metadata_layout' in blocking else 'candidate_review_required'
    return SourceAudit(repo, revision, status, categories, tuple(dict.fromkeys(blocking)), config)


def _text(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ').replace('<', '&lt;').replace('>', '&gt;')


def build_source_list(registry=None, audit_snapshot=None):
    """Render SOURCES.md solely from registry and an explicit optional audit view."""
    registry = registry or load_registry()
    lines = ['# Asset sources', '',
             'Generated from [the packaged registry](../../src/simscene/catalog/data/sources.yaml). Edit that registry and regenerate this file; do not maintain a second source inventory.', '',
             'Source admission and asset physics are separate. Enabled means an adapter passed a finite integration example. It does not certify every object, variant, profile, license or engine.', '',
             '| Source | State | Default | Formats | Acquisition granularity | License scope | Last checked | Scoped local examples |',
             '|---|---|---|---|---|---|---|---|']
    for source in registry.sources:
        examples = [item for item in source.evidence if isinstance(item, dict) and item.get('evidence_basis') == 'locally_executed' and item.get('runtime_validation') == 'pass']
        formats = {'nvidia': 'USD', 'abo': 'GLB', 'hf_manifest': 'GLB', 'usdcraft': 'USD',
                   'simready_package':'USD', 'http_assets':'HDRI / material maps (selected IDs)',
                   'simready_central':'USD locators (metadata only)'}.get(source.adapter, 'unknown')
        license_info = source.license_policy
        license_label = license_info.get('license') or license_info.get('status', 'unknown')
        license_label += '; per-asset review required' if license_info.get('per_asset_required') else ''
        columns = [f'[{_text(source.source_id)}]({source.homepage})', source.state,
                   'yes' if source.default_enabled else 'no', formats,
                   source.acquisition_granularity or 'unknown', license_label,
                   source.checked_at or 'unknown', str(len(examples))]
        lines.append('| ' + ' | '.join(_text(value) for value in columns) + ' |')
    lines += ['', '## Lifecycle inventory', '']
    for state in ('enabled', 'audited', 'candidate', 'quarantined', 'reference_only'):
        identifiers = ', '.join(source.source_id for source in registry.sources if source.state == state) or '(none)'
        lines.append(f'- **{state}**: {_text(identifiers)}')
    lines += ['', '## Limits of the recorded examples', '']
    for source in registry.sources:
        lines += ['### ' + _text(source.source_id), '']
        records = [item for item in source.evidence if isinstance(item, dict) and item.get('evidence_basis') == 'locally_executed']
        if not records:
            lines += ['No locally executed example is recorded.', '']; continue
        for record in records:
            selected = record.get('selected_asset', {})
            lines.append('Selected asset: `' + _text(selected.get('asset_id', 'unknown')) + '` at `' + _text(selected.get('revision', 'unknown')) + '`.')
            lines.append('')
            for scope in record.get('accepted_scope', []):
                lines.append('- ' + _text(scope))
            for limitation in record.get('limitations', []):
                lines.append('- Limitation: ' + _text(limitation))
            target = record.get('target', {})
            lines += ['', 'Observed target: ' + _text(', '.join(str(target.get(key, 'unknown')) for key in ('engine', 'isaac_version', 'usd_version', 'platform'))) + '.', '']
    lines += ['HF discovery returns **candidate repositories**, not registered sources or prepared assets. It never changes this registry automatically. Repository rows, renders and variants are not unique-object counts.', '']
    if audit_snapshot:
        if isinstance(audit_snapshot, dict):
            audit_snapshot = audit_snapshot.get('audits', [audit_snapshot])
        if not isinstance(audit_snapshot, (list, tuple)):
            raise ValueError('audit_snapshot must contain explicit audit records')
        lines += ['## Explicit candidate audit snapshot', '', '| Candidate | Revision | Static audit | Blocking reasons |', '|---|---|---|---|']
        for audit in audit_snapshot:
            audit = audit.to_dict() if isinstance(audit, SourceAudit) else audit
            lines.append('| ' + ' | '.join(_text(v) for v in (audit['repository'], audit.get('revision') or 'unknown', audit['status'], ', '.join(audit.get('blocking_reasons', [])))) + ' |')
        lines.append('')
    return '\n'.join(lines)
