"""V2 defaults live separately from the legacy non-secret settings document."""
import json
import os
from pathlib import Path

DEFAULTS = {
    'schema_version': 1, 'search_deadline_seconds': 12, 'metadata_max_bytes': 32*1024**2,
    'asset_download_bytes': 1024**3, 'scene_download_bytes': 2*1024**3,
    'unpacked_bytes': 4*1024**3, 'staging_bytes': 4*1024**3,
    'prepared_cache_bytes': 4*1024**3,
}


def read():
    from ..settings import config_path, get
    path = Path(os.getenv('SIMSCENE_V2_CONFIG', str(config_path().with_name('v2.json')))).expanduser()
    data = json.loads(path.read_text()) if path.is_file() else {}
    allowed = set(DEFAULTS) | {'index_directory', 'prepared_directory', 'registry_path', 'runtime_manifest', 'converter_tools_prefix', 'generation_runtime'}
    if not isinstance(data, dict) or set(data)-allowed:
        raise ValueError('invalid V2 settings fields')
    result = dict(DEFAULTS, **data)
    if result['schema_version'] != 1:
        raise ValueError('unsupported V2 settings version')
    for key in DEFAULTS.keys()-{'schema_version'}:
        if type(result[key]) is not int or result[key] <= 0:
            raise ValueError('positive integer required for '+key)
    home = Path(get('data_directory', '~/.local/share/simscene/scenes')).expanduser().resolve()
    cache = Path(get('cache_directory', '~/.cache/simscene/assets')).expanduser().resolve()
    result.setdefault('index_directory', os.getenv('SIMSCENE_CATALOG_DIRECTORY', str(home/'catalog-v1')))
    # A sibling avoids legacy source-cache LRU treating the entire derived
    # store as one evictable source package.
    result.setdefault('prepared_directory', str(cache.with_name(cache.name+'-prepared-v1')))
    result.setdefault('runtime_manifest', str(home/'preparation-runtime.json'))
    if os.getenv('SIMSCENE_GLTF_TRANSFORM_PREFIX'):
        result['converter_tools_prefix'] = os.environ['SIMSCENE_GLTF_TRANSFORM_PREFIX']
    for key in ('index_directory', 'prepared_directory', 'runtime_manifest', 'registry_path', 'converter_tools_prefix', 'generation_runtime'):
        if key in result:
            if not isinstance(result[key], str) or not result[key].strip():
                raise ValueError('nonempty path required for '+key)
            result[key] = str(Path(result[key]).expanduser().resolve())
    result['home'] = str(home)
    result['asset_cache_directory'] = str(cache)
    result['asset_cache_capacity_bytes'] = int(get('cache_bytes', 2*1024**3))
    return result
