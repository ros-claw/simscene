"""Strict-origin, metadata-only Hugging Face repository discovery transport."""
from dataclasses import dataclass
import json
import math
import re
import time
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from ..network import MetadataDeadline, MetadataError, fetch_metadata

REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
REVISION = re.compile('[0-9a-fA-F]{40}')


def repository_id(value):
    if not isinstance(value, str) or len(value) > 256 or not REPOSITORY.fullmatch(value) or any(p in {'.', '..'} for p in value.split('/')):
        raise ValueError('invalid Hugging Face repository ID')
    return value


def pinned_revision(value):
    if not isinstance(value, str) or not REVISION.fullmatch(value):
        raise ValueError('Hugging Face discovery requires a full commit SHA')
    return value.lower()


class _OriginOnly(HTTPRedirectHandler):
    def __init__(self, origin, deadline):
        self.origin, self.deadline = origin, deadline
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, destination = urlsplit(req.full_url), urlsplit(urljoin(req.full_url, newurl))
        match = re.fullmatch(r'/datasets/(codepawl/abo-glb)/resolve/([0-9a-f]{40})/metadata.jsonl', old.path)
        allowed = '/api/resolve-cache/datasets/' + match[1] + '/' + match[2] + '/metadata.jsonl' if match else None
        parameters = parse_qs(destination.query, keep_blank_values=True)
        if ((destination.scheme, destination.netloc) != self.origin or destination.username or destination.password
                or destination.fragment or allowed is None or destination.path != allowed
                or set(parameters) - {'etag', 'download', old.path}
                or old.path in parameters and parameters[old.path] != ['']
                or any(len(v) != 1 or len(v[0]) > 512 for v in parameters.values())):
            raise ValueError('discovery redirect changed the pinned metadata identity')
        return super().redirect_request(req, fp, code, msg, headers, destination.geturl())
    def http_error_302(self, req, fp, code, msg, headers):
        # The stock handler drains redirect bodies without the caller's byte
        # ledger. Close instead, and permit only the exact pinned JSONL cache
        # redirect above. API search/tree redirects are not followed.
        try:
            new = self.redirect_request(req, fp, code, msg, headers, headers.get('Location', ''))
        finally:
            fp.close()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise MetadataDeadline('discovery redirect deadline exceeded')
        return self.parent.open(new, timeout=remaining)
    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _json(payload):
    def constant(_):
        raise ValueError('nonfinite metadata JSON')
    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError('nonfinite metadata number')
        return parsed
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError('duplicate metadata JSON key')
            result[key] = value
        return result
    try:
        return json.loads(payload, parse_constant=constant, parse_float=number, object_pairs_hook=pairs)
    except (ValueError, TypeError, RecursionError):
        raise MetadataError('metadata_schema_changed: invalid bounded JSON') from None


class DiscoveryTransfer:
    def __init__(self, deadline, max_bytes):
        self.deadline = deadline
        self.max_bytes = max_bytes
        self.ledger = []
    @property
    def used(self):
        return sum(item.get('bytes', 0) for item in self.ledger)
    @property
    def remaining(self):
        return self.max_bytes - self.used
    def check(self):
        if time.monotonic() >= self.deadline:
            raise MetadataDeadline('source_unavailable: discovery deadline exceeded')
        if self.remaining <= 1:
            raise MetadataError('budget_exceeded: discovery metadata byte budget exhausted')


@dataclass(frozen=True)
class RepositoryPage:
    repositories: tuple
    next_url: str | None


class HFDiscoveryProvider:
    def __init__(self, *, base_url='https://huggingface.co'):
        parsed = urlsplit(base_url)
        fixture = parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
        if (not fixture and (parsed.scheme, parsed.netloc) != ('https', 'huggingface.co')) or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('discovery requires the fixed Hugging Face origin (loopback only for fixtures)')
        self.base_url = base_url.rstrip('/')
        self.origin = (parsed.scheme, parsed.netloc)

    def _fetch(self, url, transfer, *, prefix_bytes=None):
        transfer.check()
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.netloc) != self.origin or parsed.username or parsed.password or parsed.fragment or not parsed.path.startswith('/api/datasets') and '/resolve/' not in parsed.path:
            raise ValueError('unsafe discovery metadata URL')
        metadata = {}
        # fetch_metadata reads one lookahead byte when enforcing its cap. Reserve
        # that byte so total received bytes, including failed reads, never exceed
        # this discovery transaction's hard limit.
        limit = transfer.remaining - 1
        result = fetch_metadata(url, deadline=transfer.deadline, max_bytes=limit, ledger=transfer.ledger,
                                opener=build_opener(_OriginOnly(self.origin, transfer.deadline)), response_metadata=metadata,
                                prefix_bytes=min(prefix_bytes, limit) if prefix_bytes is not None else None)
        return result, metadata

    def _next(self, link, current, *, immutable_query):
        if not link:
            return None
        next_links = []
        for segment in link.split(','):
            if not re.search(r'rel\s*=\s*["\']?next(?:["\']|\s|$)', segment):
                continue
            match = re.search(r'<([^>]+)>', segment)
            if not match:
                raise MetadataError('unsafe_cursor: malformed metadata pagination link')
            next_links.append(urljoin(current, match.group(1)))
        if len(next_links) > 1:
            raise MetadataError('unsafe_cursor: ambiguous metadata pagination')
        if not next_links:
            return None
        target, original = urlsplit(next_links[0]), urlsplit(current)
        if ((target.scheme, target.netloc) != self.origin or target.username or target.password or target.fragment
                or target.path != original.path):
            raise MetadataError('unsafe_cursor: metadata pagination changed origin, repository or revision')
        params = parse_qs(target.query, keep_blank_values=True)
        expected = parse_qs(original.query, keep_blank_values=True)
        # HF's native tree links make the default expand=false explicit. This
        # is the only accepted added query field; expanded blobs remain denied.
        if '/tree/' in original.path and 'expand' in params:
            if params['expand'] != ['false']:
                raise MetadataError('unsafe_cursor: expanded tree blobs are not permitted')
            if 'expand' not in expected:
                params.pop('expand')
        if set(params) != set(expected) | {'cursor'} or any(params.get(key) != expected[key] for key in immutable_query) or any(len(v) != 1 for v in params.values()):
            raise MetadataError('unsafe_cursor: metadata pagination changed query or limits')
        token = params.get('cursor', [''])[0]
        if not token or len(token) > 4096:
            raise MetadataError('unsafe_cursor: missing or oversized metadata cursor')
        return next_links[0]

    def search_page(self, query, transfer, *, next_url=None, page_limit=25):
        route = self.base_url + '/api/datasets?' + urlencode({'search': query, 'limit': page_limit, 'full': 'true'})
        url = next_url or route
        if next_url:
            # Revalidate injected continuations before performing any request.
            self._next('<' + next_url + '>; rel="next"', route, immutable_query=('search', 'limit', 'full'))
        payload, headers = self._fetch(url, transfer)
        rows = _json(payload)
        if not isinstance(rows, list) or len(rows) > page_limit or any(not isinstance(row, dict) for row in rows):
            raise MetadataError('metadata_schema_changed: invalid repository search page')
        next_page = self._next(headers.get('link', ''), url, immutable_query=('search', 'limit', 'full'))
        return RepositoryPage(tuple(rows), next_page)

    def tree(self, repo, revision, transfer, *, entries=20):
        repo, revision = repository_id(repo), pinned_revision(revision)
        route = self.base_url + '/api/datasets/' + repo + '/tree/' + revision
        url = route + '?' + urlencode({'recursive': 'false', 'limit': entries})
        payload, headers = self._fetch(url, transfer)
        rows = _json(payload)
        if not isinstance(rows, list) or len(rows) > entries or any(not isinstance(row, dict) for row in rows):
            raise MetadataError('metadata_schema_changed: invalid pinned file tree')
        next_url = self._next(headers.get('link', ''), url, immutable_query=('recursive', 'limit'))
        result = []
        for row in rows:
            path = row.get('path')
            if not isinstance(path, str) or path.startswith('/') or any(c in path for c in ('\\', '%', '?', '#', ':')) or any(p in ('', '.', '..') for p in path.split('/')):
                raise MetadataError('metadata_schema_changed: unsafe repository file path')
            size = row.get('size')
            if size is not None and (type(size) is not int or size < 0):
                raise MetadataError('metadata_schema_changed: invalid repository file size')
            result.append({'path': path, 'type': row.get('type'), 'size_bytes': size})
        return {'entries': result, 'complete': next_url is None, 'revision': revision,
                'scope': 'bounded root tree only; directories and dataset rows are not object counts'}

    def probe_abo_index(self, repo, revision, transfer):
        # Only the curated adapter's already known metadata path is eligible.
        # This is a schema prefix, never a full index or a model acquisition.
        if repository_id(repo) != 'codepawl/abo-glb':
            return None
        revision = pinned_revision(revision)
        url = self.base_url + '/datasets/' + repo + '/resolve/' + revision + '/metadata.jsonl'
        payload, _ = self._fetch(url, transfer, prefix_bytes=16384)
        line = payload.split(b'\n', 1)[0]
        row = _json(line)
        expected = {'id', 'file', 'name', 'product_type', 'size_metres', 'pack_bytes'}
        compatible = isinstance(row, dict) and expected <= set(row)
        if compatible:
            identity, size, dimensions = row['id'], row['pack_bytes'], row['size_metres']
            compatible = (isinstance(identity, str) and re.fullmatch('[A-Za-z0-9_-]+', identity) is not None
                          and row['file'] == f'objects/{identity}/{identity}.glb'
                          and (size is None or type(size) is int and size > 0)
                          and all(row[key] is None or isinstance(row[key], str) for key in ('name', 'product_type'))
                          and (dimensions is None or isinstance(dimensions, list) and len(dimensions) == 3
                               and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in dimensions)))
        return {'compatible_schema_prefix': bool(compatible),
                'complete_index_inspected': False, 'path': 'metadata.jsonl', 'revision': revision}
