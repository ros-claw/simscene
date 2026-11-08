"""Bounded federated metadata search with postfilters and frozen local pagination."""
import base64
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
import json
import time
from .models import SearchPage, SearchRequest, stable_hash
from .network import MetadataDeadline, MetadataError
from .registry import load_registry
from .store import CatalogStore

MAX_RESPONSE_BYTES = 12 * 1024
MAX_CANDIDATES_PER_PROVIDER = 100
ALIASES = {'工作台': 'workbench', '桌子': 'table', '椅子': 'chair', '杯子': 'cup',
           '台灯': 'lamp', '柜子': 'cabinet', '沙发': 'sofa', '盒子': 'box', '球': 'ball'}


class CursorInvalid(ValueError):
    code = 'cursor_invalid'


def _rewrite(query):
    rewritten = query
    for original, alias in ALIASES.items():
        rewritten = rewritten.replace(original, ' ' + alias + ' ')
    return ' '.join(rewritten.split())


def constraint_decision(record, request):
    """Unknown facts never yield matched=true; known contradictions are excluded."""
    unknown, unmet = [], []
    if request.formats and (record.format or '').lower() not in {v.lower() for v in request.formats}:
        (unknown if record.format is None else unmet).append('format')
    if request.category:
        if record.category is None:
            unknown.append('category')
        elif request.category.casefold() != record.category.casefold():
            unmet.append('category')
    for capability in request.required_capabilities:
        if not record.has_capability(capability):
            # Physical requirements cannot be satisfied by inferred/unknown facts,
            # even when other unknown numeric/license constraints are admitted.
            unmet.append('required_capability:' + capability)
    if request.usage_policy and request.usage_policy != 'any':
        policy = record.license or {}
        identifier = policy.get('license')
        if policy.get('status') == 'unknown' or not identifier:
            unknown.append('usage_policy')
        elif policy.get('status') in {'conflicting', 'restricted'}:
            unmet.append('usage_policy')
        elif request.usage_policy in {'commercial', 'commercial_use', 'redistributable'}:
            if identifier.upper() not in {'CC0-1.0', 'CC-BY-4.0', 'MIT', 'APACHE-2.0', 'BSD-2-CLAUSE', 'BSD-3-CLAUSE'}:
                unmet.append('usage_policy')
        else:
            unmet.append('unsupported_usage_policy')
    if request.size_range_m is not None:
        if record.dimensions_m is None:
            unknown.append('size_range_m')
        else:
            low, high = request.size_range_m
            longest = max(record.dimensions_m)
            if low is not None and longest < low or high is not None and longest > high:
                unmet.append('size_range_m')
    if request.max_acquire_bytes is not None:
        estimate = (record.availability or {}).get('estimated_download_bytes')
        if estimate is None:
            unknown.append('max_acquire_bytes')
        elif type(estimate) is not int or estimate < 0:
            unknown.append('max_acquire_bytes')
        elif estimate > request.max_acquire_bytes:
            unmet.append('max_acquire_bytes')
    return {'include': not unmet and (not unknown or request.allow_unknown_constraints),
            'matched': not unmet and not unknown, 'unknown': unknown, 'unmet': unmet}


def _cursor(snapshot, offset):
    payload = json.dumps({'snapshot': snapshot, 'offset': offset}, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip('=')


def _decode_cursor(cursor):
    try:
        if len(cursor) > 512:
            raise ValueError()
        data = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if set(data) != {'snapshot', 'offset'} or type(data['offset']) is not int or data['offset'] < 0:
            raise ValueError()
        return data
    except (ValueError, TypeError, UnicodeError):
        raise CursorInvalid('cursor_invalid: malformed cursor') from None


def _summary(record, decision, detail, experimental, provider_rank=0):
    def clipped(value, count=100):
        return value[:count] if isinstance(value, str) else value
    availability = record.availability or {}
    gaps = ['runtime_not_verified'] + decision['unknown']
    if (record.license or {}).get('status', 'unknown') != 'known':
        gaps.append('license_unknown_or_restricted')
    if record.dimensions_m is None:
        gaps.append('dimensions_unknown')
    if record.physics is None:
        gaps.append('physics_unknown')
    if availability.get('estimated_download_bytes') is None:
        gaps.append('acquisition_size_unknown')
    return {'ref': record.ref.to_dict(), 'title': clipped(record.title), '_provider_rank': provider_rank,
            'category': clipped(record.category, 60), 'format': record.format,
            'license': {'status': (record.license or {}).get('status', 'unknown'),
                        'license': (record.license or {}).get('license')},
            'dimensions_m': list(record.dimensions_m) if record.dimensions_m else None,
            'evidence_level': record.evidence_level, 'experimental': experimental,
            'matched': decision['matched'], 'unknown_constraints': decision['unknown'],
            'unmet_constraints': decision['unmet'],
            'match_reasons': ['text_search'] + (['constraints_satisfied'] if decision['matched'] else []),
            'key_gaps': list(dict.fromkeys(gaps)),
            'acquisition': {'granularity': availability.get('granularity'),
                            'estimated_download_bytes': availability.get('estimated_download_bytes')},
            'detail_ref': detail}


def _page(snapshot, offset, request, elapsed_ms):
    items = snapshot['items']
    if offset > len(items):
        raise CursorInvalid('cursor_invalid: offset outside frozen candidate buffer')
    selected = []
    end = offset
    budgets = dict(snapshot['budgets'])
    budgets['transfer_scope'] = 'frozen_query_snapshot'
    budgets['request_metadata_bytes'] = 0 if request.cursor else budgets['metadata_bytes']
    budgets['request_preview_bytes'] = 0 if request.cursor else budgets['preview_bytes']
    budgets['candidate_buffer_frozen'] = True
    budgets['remote_index_frozen'] = False
    while end < len(items) and len(selected) < request.limit:
        trial = selected + [items[end]]
        next_cursor = _cursor(snapshot['snapshot_id'], end + 1) if end + 1 < len(items) else None
        candidate = SearchPage(snapshot['query_id'], snapshot['status'], tuple(trial), next_cursor,
                               snapshot['source_statuses'], budgets, round(elapsed_ms, 2))
        if max(len(json.dumps(candidate.to_dict(), ensure_ascii=False).encode('utf-8')),
               len(json.dumps(candidate.to_dict(), ensure_ascii=True).encode('utf-8'))) > MAX_RESPONSE_BYTES:
            if not selected:
                raise ValueError('catalog decision summary exceeds response budget')
            break
        selected = trial
        end += 1
    cursor = _cursor(snapshot['snapshot_id'], end) if end < len(items) else None
    return SearchPage(snapshot['query_id'], snapshot['status'], tuple(selected), cursor,
                      snapshot['source_statuses'], budgets, round(elapsed_ms, 2))


def search_assets(request, *, registry=None, providers=None, index_directory=None):
    if not isinstance(request, SearchRequest):
        raise ValueError('search_assets requires a SearchRequest')
    if len(request.query.encode('utf-8')) > 4096:
        raise ValueError('catalog query exceeds 4096 UTF-8 bytes')
    started = time.monotonic()
    deadline = started + request.deadline_seconds
    configuration = None
    if registry is None or index_directory is None or providers is None:
        from .config import read
        configuration = read()
    registry = registry or load_registry(configuration.get('registry_path'))
    if index_directory is None:
        index_directory = configuration['index_directory']
    store = CatalogStore(index_directory)
    sources = registry.select(request.source_ids)
    if providers is None:
        from .providers.factory import make_provider
        providers = {source.source_id: make_provider(store,source,configuration) for source in sources}
    request_identity = request.to_dict()
    request_identity.pop('cursor')
    query_hash = stable_hash(request_identity)
    versions = {source.source_id: providers[source.source_id].snapshot
                for source in sources if source.source_id in providers}
    if request.cursor:
        decoded = _decode_cursor(request.cursor)
        try:
            snapshot = store.read_document('snapshots', decoded['snapshot'])
            if not isinstance(snapshot, dict) or snapshot.get('snapshot_id') != decoded['snapshot']:
                raise ValueError('snapshot identity mismatch')
            if stable_hash({k: v for k, v in snapshot.items() if k != 'snapshot_id'}) != decoded['snapshot']:
                raise ValueError('snapshot content changed')
        except (ValueError, OSError, TypeError):
            raise CursorInvalid('cursor_invalid: local snapshot is unavailable') from None
        if snapshot['query_hash'] != query_hash or snapshot['versions'] != versions:
            raise CursorInvalid('cursor_invalid: query/filter/index snapshot changed')
        if time.time() > snapshot['expires_at']:
            raise CursorInvalid('cursor_invalid: local snapshot expired')
        return _page(snapshot, decoded['offset'], request, (time.monotonic() - started) * 1000)
    statuses, records, ledger = {}, [], []
    rewritten = _rewrite(request.query)
    provider_request = replace(request, query=rewritten)
    executor = ThreadPoolExecutor(max_workers=request.max_providers, thread_name_prefix='catalog-metadata')
    futures = {}
    try:
        for source in sources[:request.max_providers]:
            provider = providers.get(source.source_id)
            if provider is None:
                statuses[source.source_id] = {'status': 'unavailable', 'reason': 'adapter_unavailable'}
                continue
            provider.configure(deadline, ledger)
            futures[executor.submit(provider.search, provider_request)] = source
        for source in sources[request.max_providers:]:
            statuses[source.source_id] = {'status': 'unavailable', 'reason': 'provider_budget'}
        completed, pending = wait(futures, timeout=max(0, deadline - time.monotonic()))
        for future in completed:
            source = futures[future]
            try:
                page = future.result()
                if len(page.items) > MAX_CANDIDATES_PER_PROVIDER:
                    raise ValueError('provider_candidate_budget_exceeded')
                # A first search may lazily populate its bounded metadata index.
                # Freeze the generation actually used, not its pre-load marker.
                versions[source.source_id] = page.snapshot
                statuses[source.source_id] = {'status': 'ok', 'candidates': len(page.items),
                                              'experimental': source.state != 'enabled',
                                              'warnings': list(page.warnings)}
                source_records = []
                for rank, record in enumerate(page.items):
                    if record.ref.source_id != source.source_id:
                        raise ValueError('provider returned a foreign source')
                    decision = constraint_decision(record, request)
                    if decision['include']:
                        detail = store.remember(record)
                        source_records.append(_summary(record, decision, detail, source.state != 'enabled', rank))
                records.extend(source_records)
            except MetadataDeadline:
                statuses[source.source_id] = {'status': 'timeout'}
            except MetadataError as error:
                statuses[source.source_id] = {'status':'unavailable','reason':error.code}
            except Exception:
                # Errors must not leak provider URLs, credentials or raw rows.
                statuses[source.source_id] = {'status': 'unavailable', 'reason': 'metadata_provider_failed'}
        for future in pending:
            future.cancel()
            statuses[futures[future].source_id] = {'status': 'timeout'}
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    successes = sum(s['status'] == 'ok' for s in statuses.values())
    status = 'ok' if statuses and successes == len(statuses) else 'partial' if successes else 'unavailable'
    # Only identical immutable refs are deduplicated; similar titles/geometries
    # and upstream/mirror relations remain distinct evidence-bearing records.
    unique = {stable_hash(item['ref']): item for item in records}
    records = sorted(unique.values(), key=lambda r: (not r['matched'], -{'unknown': 0, 'declared': 1, 'inspected': 2, 'runtime_verified': 3}[r['evidence_level']],
                                                      r['ref']['source_id'], r['_provider_rank'], r['ref']['asset_id']))
    for record in records:
        record.pop('_provider_rank')
    preview_bytes = sum(e.get('embedded_preview_bytes', 0) for e in ledger)
    budgets = {'metadata_bytes': max(0, sum(e['bytes'] for e in ledger) - preview_bytes),
               'preview_bytes': preview_bytes, 'model_bytes': 0,
               'deadline_seconds': request.deadline_seconds, 'providers': len(futures),
               'original_query': request.query[:256], 'rewritten_query': rewritten[:256],
               'candidate_limit_per_provider': MAX_CANDIDATES_PER_PROVIDER}
    frozen = {'schema_version': 1, 'query_hash': query_hash, 'query_id': query_hash[:24],
              'status': status, 'source_statuses': statuses, 'budgets': budgets,
              'versions': versions, 'items': records, 'expires_at': time.time() + 3600}
    frozen['snapshot_id'] = stable_hash(frozen)
    store.write_document('snapshots', frozen['snapshot_id'], frozen)
    return _page(frozen, 0, request, (time.monotonic() - started) * 1000)


def resolve_asset(ref, *, index_directory=None):
    """Resolve only a prior search/index selection; never inspect/fetch models."""
    from .models import AssetRef
    if isinstance(ref, dict):
        ref = AssetRef.from_dict(ref)
    if not isinstance(ref, AssetRef):
        raise ValueError('resolve_asset requires an AssetRef')
    ref.validate_selection()
    if index_directory is None:
        from .config import read
        index_directory = read()['index_directory']
    return CatalogStore(index_directory).get(ref)
