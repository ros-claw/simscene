"""Versioned, JSON-only catalog contracts; unknown facts remain ``None``.

Source lifecycle describes adapter admission, never physical verification of an asset.
"""
from dataclasses import asdict, dataclass, fields, is_dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1
VOLATILE_FIELDS = frozenset({'created_at', 'updated_at', 'checked_at', 'job_id',
                             'elapsed_ms', 'temporary_path', 'temp_path', 'temporary_directory'})
EVIDENCE_LEVELS = frozenset({'unknown', 'declared', 'inspected', 'runtime_verified'})


def _json_value(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError('JSON object keys must be strings')
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError('record must contain only finite JSON values')


def canonical_json(value, *, exclude_volatile=True):
    """Canonical UTF-8 JSON; paths are excluded only via named volatile fields.

    Real input/toolchain paths and all other actual parameters stay in the identity.
    """
    def clean(item):
        if isinstance(item, dict):
            return {k: clean(v) for k, v in item.items()
                    if not exclude_volatile or k not in VOLATILE_FIELDS}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return item
    return json.dumps(clean(_json_value(value)), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def stable_hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')


def _number(value, name, *, positive=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite numeric')
    if integer and not isinstance(value, int):
        raise ValueError(f'{name} must be integer')
    if value < 0 or (positive and value == 0):
        raise ValueError(f'{name} out of range')


class Record:
    def to_dict(self):
        return _json_value(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError(f'{cls.__name__} must be an object')
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f'unknown {cls.__name__} fields: {sorted(unknown)}')
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError(str(error)) from error

    def _version(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError('unsupported schema_version')
        _json_value(self)


@dataclass(frozen=True)
class MetadataEntry(Record):
    path: str
    format: str
    size_bytes: int | None
    revision: str | None
    contains_images: bool
    contains_code: bool

    def __post_init__(self):
        _text(self.path, 'metadata path')
        _text(self.format, 'metadata format')
        if self.size_bytes is not None:
            _number(self.size_bytes, 'metadata size', integer=True)
        if self.revision is not None:
            _text(self.revision, 'metadata revision')
        if type(self.contains_images) is not bool or type(self.contains_code) is not bool:
            raise ValueError('metadata image/code declarations must be explicit booleans')
        if self.contains_images or self.contains_code:
            raise ValueError('metadata-only indexes cannot embed images or executable code')
        if self.format not in {'json', 'jsonl', 'csv', 'sqlite', 'service'}:
            raise ValueError('unsupported metadata-only format')
        from urllib.parse import urlsplit
        parsed = urlsplit(self.path)
        if parsed.scheme:
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('metadata URL must be credential-free HTTPS')
            if parsed.query or parsed.fragment:
                raise ValueError('metadata URL must not embed query credentials')
        if parsed.path.lower().endswith(('.glb', '.gltf', '.usd', '.usda', '.usdc', '.usdz', '.zip', '.tar', '.gz', '.png', '.jpg', '.jpeg', '.py', '.pkl', '.pickle')):
            raise ValueError('model/image/archive/code payload cannot be a metadata index')
        if not parsed.scheme and (self.path.startswith('/') or '\\' in self.path or any(p in {'', '.', '..'} for p in self.path.split('/'))):
            raise ValueError('metadata path must be a safe relative path')


@dataclass(frozen=True)
class SourceRecord(Record):
    source_id: str
    kind: str
    homepage: str
    adapter: str
    state: str
    default_enabled: bool
    metadata_entries: tuple[MetadataEntry, ...]
    acquisition_granularity: str | None
    access: dict
    license_policy: dict
    capabilities: dict
    checked_at: str | None
    evidence: tuple
    schema_version: int = 1
    repository: str | None = None

    def __post_init__(self):
        self._version()
        for name in ('source_id', 'homepage', 'adapter'):
            _text(getattr(self, name), name)
        if self.kind not in {'asset_dataset', 'search_service', 'procedural_backend', 'reference'}:
            raise ValueError('invalid source kind')
        if self.state not in {'candidate', 'audited', 'enabled', 'quarantined', 'reference_only'}:
            raise ValueError('invalid source state')
        if type(self.default_enabled) is not bool or (self.default_enabled and self.state != 'enabled'):
            raise ValueError('only enabled sources may be default enabled')
        if self.acquisition_granularity not in {None, 'single_file', 'dependency_closure', 'asset_package', 'category_archive', 'dataset_archive', 'generated'}:
            raise ValueError('invalid acquisition granularity')
        object.__setattr__(self, 'metadata_entries', tuple(
            MetadataEntry.from_dict(item) if isinstance(item, dict) else item
            for item in self.metadata_entries))
        if not self.metadata_entries or not all(isinstance(e, MetadataEntry) for e in self.metadata_entries):
            raise ValueError('declared metadata entries required')
        if not isinstance(self.access, dict) or set(self.access) != {'visibility', 'gated', 'credentials_required'}:
            raise ValueError('access requires visibility, gated, credentials_required; credentials are forbidden')
        if self.access['visibility'] not in {'public', 'private', 'unknown'}:
            raise ValueError('invalid visibility')
        for key in ('gated', 'credentials_required'):
            if self.access[key] is not None and type(self.access[key]) is not bool:
                raise ValueError('access flags must be bool or null')
        if not isinstance(self.license_policy, dict) or self.license_policy.get('status') not in {'known', 'unknown', 'conflicting', 'restricted'}:
            raise ValueError('explicit license status required')
        if self.license_policy['status'] == 'known' and not self.license_policy.get('license'):
            raise ValueError('known source license requires license identifier')
        _capabilities(self.capabilities)
        if self.checked_at is not None:
            _text(self.checked_at, 'checked_at')
        if not isinstance(self.evidence, (list, tuple)):
            raise ValueError('evidence must be a sequence')
        if self.repository is not None:
            _text(self.repository, 'repository')
        object.__setattr__(self, 'evidence', tuple(self.evidence))


@dataclass(frozen=True)
class AssetRef(Record):
    source_id: str
    asset_id: str
    revision: str
    variant_id: str | None = None

    def __post_init__(self):
        for name in ('source_id', 'asset_id'):
            _text(getattr(self, name), name)
        _text(self.revision, 'revision')
        if self.variant_id is not None:
            _text(self.variant_id, 'variant_id')

    def validate_selection(self, *, huggingface=False):
        if self.revision is None:
            raise ValueError('selection requires a lockable revision')
        if (huggingface or self.source_id == 'abo-glb') and not re.fullmatch(r'[0-9a-fA-F]{40}', self.revision):
            raise ValueError('Hugging Face selection requires a full commit SHA')
        return self


@dataclass(frozen=True)
class BackendTarget(Record):
    engine: str
    isaac_version: str
    usd_version: str
    platform: str

    def __post_init__(self):
        for field in fields(self):
            _text(getattr(self, field.name), field.name)


def _capabilities(values):
    if not isinstance(values, dict):
        raise ValueError('capabilities must be an object')
    for name, fact in values.items():
        _text(name, 'capability')
        if not isinstance(fact, dict) or set(fact) != {'value', 'evidence'}:
            raise ValueError('capability requires value and evidence')
        if fact['evidence'] not in EVIDENCE_LEVELS:
            raise ValueError('invalid capability evidence')
        if fact['value'] is not None and type(fact['value']) is not bool:
            raise ValueError('capability value must be bool or null')
        if fact['evidence'] == 'unknown' and fact['value'] is not None:
            raise ValueError('unknown capability cannot assert a value')
        if fact['evidence'] != 'unknown' and fact['value'] is None:
            raise ValueError('known capability requires a value')


@dataclass(frozen=True)
class AssetRecord(Record):
    ref: AssetRef
    title: str
    category: str | None = None
    tags: tuple[str, ...] = ()
    format: str | None = None
    entry_path: str | None = None
    preview: dict | None = None
    license: dict | None = None
    dimensions_m: tuple[float, float, float] | None = None
    physics: dict | None = None
    availability: dict | None = None
    provenance: dict | None = None
    evidence_level: str = 'unknown'
    capabilities: dict | None = None
    schema_version: int = 1

    def __post_init__(self):
        self._version()
        if isinstance(self.ref, dict):
            object.__setattr__(self, 'ref', AssetRef.from_dict(self.ref))
        if not isinstance(self.ref, AssetRef):
            raise ValueError('asset ref required')
        _text(self.title, 'title')
        for name in ('category', 'format', 'entry_path'):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        for name in ('preview', 'availability', 'provenance'):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), dict):
                raise ValueError(f'{name} must be an object or null')
        if not isinstance(self.tags, (list, tuple)):
            raise ValueError('tags must be a sequence')
        object.__setattr__(self, 'tags', tuple(self.tags))
        if not all(isinstance(tag, str) for tag in self.tags):
            raise ValueError('tags must be strings')
        if self.evidence_level not in EVIDENCE_LEVELS:
            raise ValueError('invalid asset evidence level')
        if self.dimensions_m is not None:
            if not isinstance(self.dimensions_m, (tuple, list)) or len(self.dimensions_m) != 3:
                raise ValueError('dimensions_m requires three measured extents or null')
            for value in self.dimensions_m:
                _number(value, 'dimension', positive=True)
            object.__setattr__(self, 'dimensions_m', tuple(self.dimensions_m))
        if self.license is not None:
            if not isinstance(self.license, dict) or self.license.get('status') not in {'known', 'unknown', 'conflicting', 'restricted'}:
                raise ValueError('license requires explicit status')
            if self.license['status'] == 'known' and not self.license.get('license'):
                raise ValueError('known license requires identifier')
        if self.physics is not None:
            if not isinstance(self.physics, dict):
                raise ValueError('physics must be an object')
            for name, fact in self.physics.items():
                if not isinstance(fact, dict) or 'value' not in fact or fact.get('evidence') not in EVIDENCE_LEVELS:
                    raise ValueError('each physics fact requires value and evidence')
                if fact['evidence'] == 'unknown' and fact['value'] is not None:
                    raise ValueError('unknown physics cannot assert a value')
                if fact['evidence'] != 'unknown' and fact['value'] is None:
                    raise ValueError('known physics requires a value')
                value = fact['value']
                if value is not None and name in {'rigid_body', 'collider'} and type(value) is not bool:
                    raise ValueError(f'{name} requires bool or null')
                if value is not None and name in {'mass', 'mass_kg', 'inertia', 'friction'}:
                    for scalar in value if isinstance(value, (list, tuple)) else (value,):
                        _number(scalar, name, positive=name in {'mass', 'mass_kg'})
                if value is not None and name in {'joint_count', 'n_joints'}:
                    _number(value, name, integer=True)
        if self.capabilities is not None:
            _capabilities(self.capabilities)

    def has_capability(self, name):
        fact = (self.capabilities or {}).get(name, {})
        return fact.get('value') is True and fact.get('evidence') in EVIDENCE_LEVELS - {'unknown'}


@dataclass(frozen=True)
class SearchRequest(Record):
    query: str
    source_ids: tuple[str, ...] = ()
    category: str | None = None
    formats: tuple[str, ...] = ()
    usage_policy: str | None = None
    required_capabilities: tuple[str, ...] = ()
    size_range_m: tuple[float | None, float | None] | None = None
    max_acquire_bytes: int | None = None
    allow_unknown_constraints: bool = False
    limit: int = 8
    cursor: str | None = None
    deadline_seconds: float = 12.0
    max_providers: int = 3
    schema_version: int = 1

    def __post_init__(self):
        self._version()
        _text(self.query, 'query')
        for name in ('category', 'usage_policy', 'cursor'):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        for name in ('source_ids', 'formats', 'required_capabilities'):
            value = getattr(self, name)
            if not isinstance(value, (tuple, list)) or not all(isinstance(v, str) and v for v in value):
                raise ValueError(f'{name} must be a sequence of strings')
            object.__setattr__(self, name, tuple(value))
        _number(self.limit, 'limit', positive=True, integer=True)
        _number(self.max_providers, 'max_providers', positive=True, integer=True)
        if self.limit > 20 or self.max_providers > 3:
            raise ValueError('limit must be <=20 and max_providers <=3')
        _number(self.deadline_seconds, 'deadline_seconds', positive=True)
        if self.max_acquire_bytes is not None:
            _number(self.max_acquire_bytes, 'max_acquire_bytes', integer=True)
        if type(self.allow_unknown_constraints) is not bool:
            raise ValueError('allow_unknown_constraints must be boolean')
        if self.size_range_m is not None:
            if not isinstance(self.size_range_m, (list, tuple)) or len(self.size_range_m) != 2:
                raise ValueError('size_range_m requires lower/upper bounds')
            low, high = self.size_range_m
            for value in (low, high):
                if value is not None:
                    _number(value, 'size bound', positive=True)
            if low is None and high is None or low is not None and high is not None and low > high:
                raise ValueError('invalid size range')
            object.__setattr__(self, 'size_range_m', tuple(self.size_range_m))


@dataclass(frozen=True)
class SearchPage(Record):
    query_id: str
    status: str
    items: tuple
    next_cursor: str | None
    source_statuses: dict
    budgets: dict
    elapsed_ms: float
    schema_version: int = 1

    def __post_init__(self):
        self._version()
        _text(self.query_id, 'query_id')
        if self.status not in {'ok', 'partial', 'unavailable'}:
            raise ValueError('invalid search status')
        if not isinstance(self.items, (tuple, list)):
            raise ValueError('items must be a sequence')
        if self.next_cursor is not None:
            _text(self.next_cursor, 'next_cursor')
        object.__setattr__(self, 'items', tuple(self.items))
        _number(self.elapsed_ms, 'elapsed_ms')
        if not isinstance(self.source_statuses, dict) or not isinstance(self.budgets, dict):
            raise ValueError('source statuses and budgets must be objects')
        if self.status == 'ok' and any(
                (v.get('status') if isinstance(v, dict) else v) not in {'ok', 'success'}
                for v in self.source_statuses.values()):
            raise ValueError('failed sources cannot produce an ok search')
