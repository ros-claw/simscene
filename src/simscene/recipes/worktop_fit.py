"""Filter observed gravity-drop footprints for a measured rectangular worktop."""
import json
import math
from decimal import Decimal
from importlib.resources import files


SUPPORT_KIND = 'horizontal_static_primitive_box'


def _positive_length(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def filter_observations(observations, *, width_m, depth_m, edge_clearance_m):
    """Use observed XY envelopes in the tested pose and clearance on both edges."""
    if not _positive_length(width_m) or not _positive_length(depth_m):
        raise ValueError('worktop width and depth must be positive finite metres')
    if (type(edge_clearance_m) not in (int, float) or not math.isfinite(edge_clearance_m)
            or edge_clearance_m < 0):
        raise ValueError('edge clearance must be nonnegative finite metres')

    matches, excluded = [], []
    dimensions = [width_m, depth_m]
    rectangle = [Decimal(str(size)) for size in dimensions]
    clearance = Decimal(str(edge_clearance_m))
    for observation in observations:
        ref = observation['source_ref']
        support = observation.get('support', {})
        extent = observation.get('footprint', {}).get('centered_xy_envelope_m')
        if (observation.get('physics_passed') is not True or support.get('kind') != SUPPORT_KIND
                or support.get('direct_worktop_contact') is not True or support.get('settled') is not True
                or not isinstance(extent, list) or len(extent) != 2
                or not all(_positive_length(span) for span in extent)):
            excluded.append({'source_ref': ref, 'reason': 'no_verified_support_result'})
            continue
        # Compare the published decimal lengths at exact-fit boundaries.
        spans = [Decimal(str(span)) for span in extent]
        margins = [(size - span) / 2 for size, span in zip(rectangle, spans)]
        available = [float(margin) for margin in margins]
        if any(margin < clearance for margin in margins):
            excluded.append({'source_ref': ref, 'reason': 'insufficient_worktop_xy',
                             'available_edge_margins_xy_m': available})
            continue
        matches.append({
            **observation,
            'minimum_worktop_xy_m': [float(span + 2 * clearance) for span in spans],
            'available_edge_margins_xy_m': available,
        })
    return {
        'schema': 'simscene.worktop_fit.v1',
        'support_kind': SUPPORT_KIND,
        'worktop_xy_m': dimensions,
        'edge_clearance_m': edge_clearance_m,
        'matches': matches,
        'excluded': excluded,
        'scope': 'Geometry prefilter for a flat static collision-enabled rectangle in the tested XY axes. '
                 'Apply the recorded pose and offset from the usable rectangle center. Contact and settling refer to '
                 'the recorded worktop only. Verify a new run on the selected support.',
    }


def worktop_fit(width_m, depth_m, edge_clearance_m):
    path = files('simscene.recipes').joinpath('data/worktop-support.json')
    evidence = json.loads(path.read_text(encoding='utf8'))
    return {
        **filter_observations(evidence['observations'], width_m=width_m, depth_m=depth_m,
                              edge_clearance_m=edge_clearance_m),
        'evidence': evidence['test_context'],
    }
