"""Curated metadata-only source registry, loaded without network or CWD assumptions."""
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
import yaml
from .models import SourceRecord

KNOWN_ADAPTERS = frozenset({'nvidia', 'abo', 'hf_manifest', 'usdcraft', 'simready_package', 'http_assets', 'simready_central'})
MAX_REGISTRY_BYTES = 1024 * 1024


def validate_source(record: dict) -> SourceRecord:
    source = SourceRecord.from_dict(record)
    if source.adapter not in KNOWN_ADAPTERS:
        raise ValueError(f'unknown catalog adapter: {source.adapter}')
    if source.adapter == 'abo' and source.repository != 'codepawl/abo-glb':
        raise ValueError('ABO adapter requires the audited codepawl/abo-glb repository')
    if source.adapter == 'usdcraft' and source.repository != 'nvidia/USDCraft-10K':
        raise ValueError('USDCraft adapter requires its audited native source repository')
    if source.adapter in {'abo','hf_manifest','usdcraft','simready_package'}:
        import re
        if not source.repository or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',source.repository):
            raise ValueError('HF adapter requires an explicit repository')
        if any(not re.fullmatch('[0-9a-f]{40}',entry.revision or '') for entry in source.metadata_entries):
            raise ValueError('HF metadata entries require immutable full commit revisions')
    return source


@dataclass(frozen=True)
class Registry:
    sources: tuple[SourceRecord, ...]
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('unsupported registry schema_version')
        object.__setattr__(self, 'sources', tuple(self.sources))
        seen = set()
        for source in self.sources:
            if not isinstance(source, SourceRecord):
                raise ValueError('registry sources must be SourceRecords')
            validate_source(source.to_dict())
            if source.source_id in seen:
                raise ValueError(f'duplicate source ID: {source.source_id}')
            seen.add(source.source_id)

    def get(self, source_id: str) -> SourceRecord:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        known = [source.source_id[:64] + ('…' if len(source.source_id) > 64 else '')
                 for source in self.sources[:8]]
        hint = ', '.join(known) or '(none)'
        if len(self.sources) > 8:
            hint += ', …'
        raise KeyError(f'unknown catalog source: {source_id}; known source IDs: {hint}')

    def select(self, source_ids=None) -> tuple[SourceRecord, ...]:
        """Only explicit selection admits audited experimental sources."""
        if not source_ids:
            return tuple(s for s in self.sources if s.state == 'enabled' and s.default_enabled)
        selected = []
        for source_id in source_ids:
            source = self.get(source_id)
            if source.state not in {'audited', 'enabled'}:
                raise ValueError(f'source is not admitted for search: {source_id}')
            if source not in selected:
                selected.append(source)
        return tuple(selected)

    def validate_metadata_reference(self, source_id: str, path: str):
        source = self.get(source_id)
        for entry in source.metadata_entries:
            if entry.path == path:
                return entry
        raise ValueError(f'undeclared metadata index for {source_id}: {path}')

    def to_dict(self):
        return {'schema_version': self.schema_version, 'sources': [s.to_dict() for s in self.sources]}


def load_registry(path: Path | None = None) -> Registry:
    resource = Path(path) if path is not None else resources.files('simscene.catalog').joinpath('data/sources.yaml')
    # Bound custom registries as well as packaged resources; never execute YAML tags.
    with resource.open('rb') as stream:
        content = stream.read(MAX_REGISTRY_BYTES + 1)
    if len(content) > MAX_REGISTRY_BYTES:
        raise ValueError('catalog registry exceeds size limit')
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ValueError('invalid catalog registry YAML') from error
    if not isinstance(data, dict) or set(data) != {'schema_version', 'sources'}:
        raise ValueError('registry requires schema_version and sources')
    if not isinstance(data['sources'], list):
        raise ValueError('registry sources must be a list')
    return Registry(tuple(validate_source(record) for record in data['sources']), data['schema_version'])
