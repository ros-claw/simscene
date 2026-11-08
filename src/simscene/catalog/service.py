"""Small shared facades for CLI and MCP. Search never starts preparation."""
from .models import SearchRequest
from .search import search_assets


def search(query, filters=None, limit=8, cursor=None):
    from .config import read
    filters = dict(filters or {})
    allowed = {'source_ids','category','formats','usage_policy','required_capabilities','size_range_m',
               'max_acquire_bytes','allow_unknown_constraints'}
    if set(filters)-allowed: raise ValueError('unknown catalog filters: '+str(sorted(set(filters)-allowed)))
    request = SearchRequest(query=query, limit=limit, cursor=cursor,
                            deadline_seconds=read()['search_deadline_seconds'], **filters)
    return search_assets(request).to_dict()


def sources():
    from .registry import load_registry
    from .config import read
    return load_registry(read().get('registry_path')).to_dict()


def discover(query, budget=None, cursor=None):
    from .discovery import discover_sources
    return discover_sources(query, budget, cursor).to_dict()


def source_list():
    from .audit import build_source_list
    from .registry import load_registry
    from .config import read
    return build_source_list(load_registry(read().get('registry_path')))


def refresh(source_id):
    import time
    from .registry import load_registry
    from .config import read
    from .store import CatalogStore
    from .providers.factory import make_provider
    config = read(); source = load_registry(config.get('registry_path')).get(source_id)
    if source.adapter not in {'abo','hf_manifest','usdcraft','http_assets'}:
        raise ValueError('source has no downloadable metadata index; search the live service directly')
    provider = make_provider(CatalogStore(config['index_directory']),source,config)
    ledger = []; provider.configure(time.monotonic()+config['search_deadline_seconds'], ledger)
    return dict(provider.refresh(), requests=ledger)
