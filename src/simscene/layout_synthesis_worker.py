"""Private single-request scene_synthesizer process; uses box proxies only."""
import contextlib
from importlib.metadata import distributions, version
import itertools
import json
import math
import platform
import sys


def _run(request):
    # Imports stay inside the selected environment; Isaac and base MCP do not
    # need this optional stack.  Redirect third-party chatter away from JSON.
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        import scene_synthesizer as synth
        import shapely
        from scene_synthesizer import assets

        actual_version = version('scene-synthesizer')
        if actual_version != '1.15.0':
            raise ValueError('scene_synthesizer 1.15.0 is required; found ' + actual_version)
        if not isinstance(request, dict) or request.get('schema') != 'simscene.scene_synthesizer.request.v1':
            raise ValueError('unsupported layout request')
        seed = request['seed']
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('invalid seed')
        support = request['support']
        low, high = support['min_xy'], support['max_xy']
        center = [(low[i] + high[i]) / 2 for i in range(2)]
        dimensions = [high[i] - low[i] for i in range(2)]
        if any(not math.isfinite(value) or value <= 0 for value in dimensions):
            raise ValueError('invalid support dimensions')
        items, reserved, clearance = request['items'], request['reserved_xy'], request['clearance_m']
        if not isinstance(items, list) or not 1 <= len(items) <= 8 or not isinstance(reserved, list):
            raise ValueError('invalid layout items or reserved regions')

        # Upstream 1.15.0's polygon sampler also uses numpy.random's global
        # generator. This process handles exactly one request, so seeding both
        # generators does not perturb the MCP server or another user's job.
        np.random.seed(seed)
        scene = synth.Scene(seed=seed)
        scene.add_object(assets.BoxAsset(extents=[*dimensions, .05]), obj_id='worktop',
                         translation=[*center, -.025])
        surfaces = scene.label_support('surface', obj_ids='worktop', erosion_distance=0, min_area=0)
        if len(surfaces) != 1:
            raise ValueError('proxy support could not be resolved to one surface')
        occupied = list(reserved)
        placements = []
        for index, item in enumerate(items):
            name, size = item['id'], item['size_m']
            if not isinstance(name, str) or len(size) != 3 or any(not math.isfinite(v) or v <= 0 for v in size):
                raise ValueError('invalid object proxy')
            asset = assets.BoxAsset(extents=size, origin=('center', 'center', 'bottom'))

            def valid(_asset, _support, transform):
                if not np.allclose(transform[:3, :3], np.eye(3), atol=1e-8):
                    return False
                xy = transform[:2, 3]
                left = [xy[i] - size[i] / 2 for i in range(2)]
                right = [xy[i] + size[i] / 2 for i in range(2)]
                if any(left[i] < low[i] + clearance or right[i] > high[i] - clearance for i in range(2)):
                    return False
                return not any(all(right[i] + clearance > other['min_xy'][i] and
                                   other['max_xy'][i] + clearance > left[i] for i in range(2))
                               for other in occupied)

            proxy_id = f'simscene_item_{index:02d}'
            succeeded = scene.place_object(proxy_id, asset, support_id='surface',
                obj_orientation_iterator=itertools.repeat(np.eye(4)), max_iter=500,
                distance_above_support=.002, valid_placement_fn=valid)
            transforms = scene.get_object_transforms()
            if not succeeded or proxy_id not in transforms:
                raise ValueError('no valid proxy placement found for ' + name)
            transform = transforms[proxy_id]
            if not np.allclose(transform[:3, :3], np.eye(3), atol=1e-8):
                raise ValueError('unexpected proxy orientation for ' + name)
            xy = [float(transform[i, 3]) for i in range(2)]
            occupied.append({'min_xy': [xy[i] - size[i] / 2 for i in range(2)],
                             'max_xy': [xy[i] + size[i] / 2 for i in range(2)]})
            placements.append({'id': name, 'offset_xy': [xy[i] - center[i] for i in range(2)]})
        versions = {}
        for dist in distributions():
            name = dist.metadata.get('Name', '').lower().replace('_', '-')
            if not name or name in versions and versions[name] != dist.version:
                raise ValueError('invalid or conflicting backend distribution identity')
            versions[name] = dist.version
        if len(versions) > 512:
            raise ValueError('layout environment has too many distributions; use an isolated environment')
    return {'schema': 'simscene.scene_synthesizer.placements.v1', 'seed': seed,
            'backend': {'name': 'scene_synthesizer', 'version': actual_version,
                        'dependency_versions': versions, 'python': platform.python_version(),
                        'platform': platform.platform(), 'native_versions': {'geos': shapely.geos_version_string},
                        'geometry': 'render-bounds box proxies; original USD not imported'},
            'placements': placements}


if __name__ == '__main__':
    try:
        data = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError('layout request exceeds size limit')
        result = _run(json.loads(data))
        print(json.dumps(result, separators=(',', ':'), allow_nan=False))
    except (ValueError, TypeError, KeyError, ImportError, OSError, RuntimeError) as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        sys.exit(2)
