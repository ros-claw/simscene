"""File-level paired-asset proof, never an in-memory spec exemption."""
import copy
import hashlib
import json

from ..snapshot_integrity import PIN_FIELDS, comparison_identity


def paired_reference(current, reference):
    """Return only a reference asset_path remap after both sealed reads pass.

    Inputs are private _read_locked results, not caller-supplied telemetry.
    Every other spec field is left for the original isolated-difference check.
    Legacy/external assets retain exact-path comparison and get no exemption.
    """
    result = {'passed': False, 'mappings': {}, 'errors': [],
              'scope': 'Verified acquired snapshot identity only; all nonpath scene fields remain exact.'}
    original = reference['spec']
    mapped = copy.deepcopy(original)
    if not current['passed'] or not reference['passed']:
        result['errors'].append('Both sealed input/output proofs must pass before asset comparison.')
        return original, result
    objects = current['spec'].get('objects', {})
    other = original.get('objects', {})
    names = {n for n, o in objects.items() if o.get('kind') == 'asset'}
    ref_names = {n for n, o in other.items() if o.get('kind') == 'asset'}
    if names != ref_names:
        result['errors'].append('Paired asset object IDs differ.')
        return original, result
    locks = [json.loads((item['root']/'asset-lock.json').read_text()) for item in (current, reference)]
    for name in sorted(names):
        try:
            records = [lock[name] for lock in locks]
            different_path = objects[name].get('asset_path') != other[name].get('asset_path')
            # Partial pins are invalid at input verification. Old exact paths
            # remain strict; missing proof never permits a relocated path.
            pinned = all(PIN_FIELDS <= set(record) and record.get('kind') == 'snapshot' for record in records)
            if not pinned:
                if different_path:
                    raise ValueError('relocated asset lacks new acquired-snapshot proof on both sides')
                continue
            identities = [comparison_identity(item['root'], obj, record, item['lock']['runtime_python'])
                          for item, obj, record in zip((current, reference), (objects[name], other[name]), records)]
            if identities[0] != identities[1]:
                raise ValueError('asset source, selected root, complete closure or runtime MDL hashes differ')
            digest = hashlib.sha256(json.dumps(identities[0], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            result['mappings'][name] = {'identity_sha256': digest, 'reference_asset_path': other[name]['asset_path'],
                                        'current_asset_path': objects[name]['asset_path'], 'relocated': different_path}
            mapped['objects'][name]['asset_path'] = objects[name]['asset_path']
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
            result['errors'].append(name+': '+str(error))
    result['passed'] = not result['errors']
    return (mapped if result['passed'] else original), result
