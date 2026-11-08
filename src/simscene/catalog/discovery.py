"""Bounded repository discovery with frozen local candidate pagination.

Discovery never changes the curated registry or obtains model payloads. Remote
repository descriptions/cards are untrusted data, not executable instructions.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile
import os
import re
import time
from urllib.parse import parse_qs, urlsplit
from .models import canonical_json
from .network import MetadataDeadline, MetadataError
from .providers.hf_discovery import DiscoveryTransfer, HFDiscoveryProvider, pinned_revision, repository_id

DEFAULTS = {'limit': 30, 'max_pages': 2, 'max_repositories': 50,
            'max_bytes': 4 * 1024**2, 'deadline_seconds': 20}
MAX_PAGE_BYTES = 96 * 1024


@dataclass(frozen=True)
class DiscoveryPage:
    query: str
    status: str
    candidates: tuple
    next_cursor: str | None
    budgets: dict
    errors: tuple
    elapsed_ms: float
    schema_version: int = 1
    def to_dict(self):
        return json.loads(json.dumps(asdict(self), allow_nan=False))


class DiscoveryCursorInvalid(ValueError):
    code = 'cursor_invalid'


def _limits(budget):
    if budget is not None and not isinstance(budget, dict):
        raise ValueError('discovery budget must be an object')
    limits = dict(DEFAULTS, **(budget or {}))
    if set(limits) != set(DEFAULTS):
        raise ValueError('unknown discovery budget fields')
    for key, maximum in dict(DEFAULTS, limit=50).items():
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError('invalid discovery budget: ' + key)
        if key != 'deadline_seconds' and type(value) is not int:
            raise ValueError('integer required for discovery budget: ' + key)
    return limits


def _license(row):
    values = []
    card = row.get('cardData') if isinstance(row.get('cardData'), dict) else {}
    supplied = card.get('license')
    if isinstance(supplied, str):
        values.append(supplied)
    elif isinstance(supplied, list):
        values.extend(item for item in supplied[:8] if isinstance(item, str))
    tags = row.get('tags') if isinstance(row.get('tags'), list) else []
    values.extend(tag.split(':', 1)[1] for tag in tags[:128] if isinstance(tag, str) and tag.startswith('license:'))
    values = sorted(set(value.lower()[:80] for value in values if value))[:8]
    status = 'unknown' if not values else 'conflicting' if len(values) > 1 else 'restricted' if '-nc' in values[0] or values[0] in {'other', 'custom', 'unknown'} else 'declared'
    return {'status': status, 'declarations': values, 'evidence': 'declared' if values else 'unknown',
            'scope': 'repository declaration; per-asset license and component exceptions remain unreviewed'}


def _candidate(row):
    repo = repository_id(row.get('id'))
    try:
        revision = pinned_revision(row.get('sha'))
    except ValueError:
        revision = None
    private = row.get('private') if type(row.get('private')) is bool else None
    gated_value = row.get('gated')
    gated = gated_value if type(gated_value) is bool else True if gated_value in ('auto', 'manual') else None
    return {'schema_version': 1, 'repository': repo, 'revision': revision,
            'homepage': 'https://huggingface.co/datasets/' + repo,
            'state': 'candidate', 'default_enabled': False,
            'access': {'visibility': 'private' if private is True else 'public' if private is False else 'unknown',
                       'gated': gated, 'credentials_required': True if private or gated else False if private is False and gated is False else None},
            'license': _license(row), 'formats': [],
            'metadata_layout': {'status': 'not_inspected', 'object_index': None},
            'metadata_entries': [], 'acquisition_granularity': None,
            'dependencies': {'status': 'unknown'}, 'physics': {'evidence': 'unknown', 'runtime_validation': 'not_run'},
            'examples': {'locally_executed': 0, 'upstream_reported': None},
            'unique_object_count': None, 'prepared_ready': False,
            'inspection_status': 'pending' if revision else 'unresolved_revision', 'issues': []}


def _error_code(error, transfer):
    last = transfer.ledger[-1] if transfer.ledger else {}
    if isinstance(error, MetadataDeadline):
        return 'timeout'
    if last.get('http_status') in (401, 403):
        return 'access_denied'
    if transfer.remaining <= 1 or str(error).startswith('budget_exceeded:'):
        return 'budget_exceeded'
    for code in ('metadata_schema_changed', 'unsafe_cursor'):
        if str(error).startswith(code + ':'):
            return code
    return 'metadata_unavailable'


def _inspect(candidate, provider, transfer):
    if candidate['revision'] is None:
        candidate['issues'].append('full_commit_sha_missing')
        return
    if candidate['access']['credentials_required'] is True:
        candidate['inspection_status'] = 'access_restricted'
        return
    tree = provider.tree(candidate['repository'], candidate['revision'], transfer)
    entries = tree['entries']
    suffixes = {Path(item['path']).suffix.lower().lstrip('.') for item in entries if item['type'] == 'file'}
    candidate['formats'] = sorted(suffixes & {'usd', 'usda', 'usdc', 'usdz', 'glb', 'gltf', 'urdf', 'mjcf', 'obj', 'fbx'})
    candidate['tree_scope'] = {'complete_root_page': tree['complete'], 'entries_inspected': len(entries),
                               'recursive': False, 'counts_are_not_unique_objects': True}
    candidate['metadata_entries'] = [{'path': entry['path'], 'size_bytes': entry['size_bytes'], 'revision': candidate['revision']}
                                     for entry in entries if entry['type'] == 'file' and entry['path'] in {'metadata.jsonl', 'metadata.json', 'manifest.json', 'com.nvidia.simready.packaging.json'}]
    from .registry import load_registry
    registered = next((source for source in load_registry().sources
                       if source.repository == candidate['repository'] and source.adapter in {'abo', 'hf_manifest', 'usdcraft'}
                       and source.metadata_entries[0].revision == candidate['revision']), None)
    archives = [entry for entry in entries if entry['type'] == 'file' and entry['path'].lower().endswith(('.tar', '.zip', '.tar.gz', '.tgz'))]
    candidate['archive_facts'] = {'present_in_inspected_page': bool(archives),
                                  'member_range_access_verified': False, 'whole_archive_bytes': [entry['size_bytes'] for entry in archives[:8]]}
    candidate['metadata_layout'] = {'status': 'unsupported_metadata_layout', 'object_index': None,
                                     'note': 'A repository/tree hit is not an object-level asset adapter.'}
    if registered is not None and any(entry['path'] == registered.metadata_entries[0].path for entry in candidate['metadata_entries']):
        candidate['metadata_layout'] = {'status': 'recognized_registered_layout', 'adapter': registered.adapter,
                                         'object_index': registered.metadata_entries[0].path,
                                         'complete_index_inspected': False, 'basis': 'existing pinned registry static review'}
        candidate['formats'] = sorted(set(candidate['formats']) | ({'glb'} if registered.adapter in {'abo', 'hf_manifest'} else {'usd'}))
        candidate['acquisition_granularity'] = registered.acquisition_granularity
        candidate['granularity_evidence'] = 'existing registered adapter at the exact reviewed revision'
    elif candidate['repository'] == 'codepawl/abo-glb' and any(e['path'] == 'metadata.jsonl' for e in candidate['metadata_entries']):
        sample = provider.probe_abo_index(candidate['repository'], candidate['revision'], transfer)
        if sample and sample['compatible_schema_prefix']:
            candidate['metadata_layout'] = {'status': 'recognized_schema_prefix', 'adapter': 'abo',
                                             'object_index': 'metadata.jsonl', 'complete_index_inspected': False}
            candidate['formats'] = sorted(set(candidate['formats']) | {'glb'})
            candidate['acquisition_granularity'] = 'single_file'
            candidate['granularity_evidence'] = 'known adapter schema prefix; selected closure still requires a plan'
    candidate['inspection_status'] = 'metadata_inspected'


def _directory(state_directory):
    if state_directory is None:
        from .config import read
        state_directory = Path(read()['index_directory']) / 'discovery'
    directory = Path(state_directory).expanduser().absolute()
    if any(part.is_symlink() for part in (directory, *directory.parents)):
        raise ValueError('discovery state directory must not contain symlinks')
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save(directory, snapshot):
    data = canonical_json(snapshot, exclude_volatile=False).encode('utf-8')
    identity = hashlib.sha256(data).hexdigest()
    with tempfile.NamedTemporaryFile('wb', dir=directory, prefix='.discovery-', delete=False) as stream:
        temporary = stream.name
        try:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, directory / (identity + '.json'))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return identity


def _page(snapshot, identity, offset, limits, *, continuation=False):
    candidates = snapshot['candidates']
    def response(selected):
        end = offset + len(selected)
        cursor = identity + ':' + str(end) if end < len(candidates) else None
        budgets = dict(snapshot['budgets'], request_metadata_bytes=0 if continuation else snapshot['budgets']['metadata_bytes'],
                       transfer_scope='frozen_discovery_candidate_buffer', remote_index_frozen=False,
                       returned_repositories=len(selected), prepared_ready_count=0)
        return DiscoveryPage(snapshot['query'], snapshot['status'], tuple(selected), cursor, budgets,
                             tuple(snapshot['errors']), snapshot['elapsed_ms'])
    selected = []
    while offset + len(selected) < len(candidates) and len(selected) < limits['limit']:
        trial = selected + [candidates[offset + len(selected)]]
        data = response(trial).to_dict()
        if max(len(json.dumps(data, ensure_ascii=True).encode()), len(json.dumps(data, ensure_ascii=False).encode())) > MAX_PAGE_BYTES:
            break
        selected = trial
    if offset < len(candidates) and not selected:
        raise ValueError('discovery candidate exceeds compact response budget')
    return response(selected)


def discover_sources(query, budget=None, cursor=None, *, provider=None, state_directory=None):
    """Discover repository candidates, at most two remote pages/50 repositories.

    The initial call freezes its bounded candidate buffer. Later cursor pages
    perform no network reads. Explicit state_directory supports isolated CLI,
    tests and inspectable maintenance runs; defaults use the catalog directory.
    """
    if not isinstance(query, str) or not query.strip() or len(query.encode('utf-8')) > 4096:
        raise ValueError('discovery query must be nonempty and at most 4096 UTF-8 bytes')
    limits = _limits(budget)
    query_key = hashlib.sha256(canonical_json({'query': query, 'budget': limits}, exclude_volatile=False).encode()).hexdigest()
    directory = _directory(state_directory)
    if cursor is not None:
        match = re.fullmatch(r'([0-9a-f]{64}):([0-9]{1,3})', cursor) if isinstance(cursor, str) else None
        if not match:
            raise DiscoveryCursorInvalid('cursor_invalid: malformed discovery cursor')
        path = directory / (match[1] + '.json')
        try:
            if path.is_symlink() or path.stat().st_size > 512 * 1024:
                raise ValueError()
            data = path.read_bytes()
            snapshot = json.loads(data)
            offset = int(match[2])
            if (hashlib.sha256(data).hexdigest() != match[1] or snapshot['query_key'] != query_key
                    or snapshot['expires_at'] < time.time() or not 0 <= offset <= len(snapshot['candidates'])):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise DiscoveryCursorInvalid('cursor_invalid: discovery query/budget/snapshot changed or expired') from None
        return _page(snapshot, match[1], offset, limits, continuation=True)
    provider = provider or HFDiscoveryProvider()
    started = time.monotonic()
    transfer = DiscoveryTransfer(started + limits['deadline_seconds'], limits['max_bytes'])
    candidates, errors, seen_repos, seen_cursors = [], [], set(), set()
    next_url = None; pages = 0; successful_pages = 0; inspections = 0; truncated = False
    page_limit = min(25, limits['limit'], max(1, limits['max_repositories'] // limits['max_pages']))
    try:
        for _ in range(limits['max_pages']):
            transfer.check()
            page = provider.search_page(query, transfer, next_url=next_url, page_limit=page_limit)
            pages += 1; successful_pages += 1
            for row in page.repositories:
                if len(seen_repos) >= limits['max_repositories']:
                    truncated = True; break
                try:
                    candidate = _candidate(row)
                except (ValueError, TypeError):
                    errors.append({'code': 'metadata_schema_changed', 'scope': 'invalid_repository_record'}); continue
                if candidate['repository'] in seen_repos:
                    continue
                seen_repos.add(candidate['repository'])
                if inspections < 4:
                    inspections += 1
                    try:
                        _inspect(candidate, provider, transfer)
                    except (MetadataError, ValueError) as error:
                        candidate['inspection_status'] = 'unavailable'
                        code = _error_code(error, transfer)
                        candidate['issues'].append(code)
                        errors.append({'code': code, 'repository': candidate['repository']})
                else:
                    candidate['inspection_status'] = 'not_inspected_budget'
                candidates.append(candidate)
            next_url = page.next_url
            if next_url:
                token = parse_qs(urlsplit(next_url).query).get('cursor', [''])[0]
                if token in seen_cursors:
                    errors.append({'code': 'repeated_cursor', 'scope': 'repository_search'}); break
                seen_cursors.add(token)
            if not next_url:
                break
            if len(seen_repos) >= limits['max_repositories']:
                truncated = True; break
        if next_url:
            truncated = True
    except (MetadataError, ValueError) as error:
        code = _error_code(error, transfer)
        errors.append({'code': code, 'scope': 'repository_search'})
    status = 'unavailable' if successful_pages == 0 else 'partial' if errors or truncated else 'ok'
    snapshot = {'schema_version': 1, 'query': query, 'query_key': query_key,
                'status': status, 'candidates': candidates, 'errors': errors,
                'budgets': {'metadata_bytes': transfer.used, 'model_bytes': 0, 'preview_bytes': 0,
                            'pages': pages, 'repositories_discovered': len(candidates), 'truncated': truncated,
                            'limits': limits, 'requests': transfer.ledger},
                'elapsed_ms': round((time.monotonic() - started) * 1000, 2), 'expires_at': time.time() + 3600}
    identity = _save(directory, snapshot)
    return _page(snapshot, identity, 0, limits)
