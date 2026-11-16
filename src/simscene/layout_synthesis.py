"""Propose source-preserving placements using an optional isolated backend.

The backend sees measured box proxies, not the original USD. Every proposed
placement is independently checked using SimScene's existing support logic.
"""
import copy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .placement import bounds, place_on, rotate, surface, vector
from .scene import SceneError, validate


def _local_box(box, orientation, position):
    inverse = [orientation[0], *[-value for value in orientation[1:]]]
    corners = [rotate(inverse, [point[i] - position[i] for i in range(3)])
               for point in itertools.product(*[(box['min'][i], box['max'][i]) for i in range(3)])]
    return {'min': [min(point[i] for point in corners) for i in range(3)],
            'max': [max(point[i] for point in corners) for i in range(3)]}


def _finite_number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise SceneError(f'{name} must be finite and between {low} and {high}')
    return float(value)


def _bounded_process(command, payload, *, timeout=60, limit=1024 * 1024):
    """Bound each output stream while a fixed worker is running, not afterward."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               bufsize=0, start_new_session=True)
    deadline = time.monotonic() + timeout
    exceeded = threading.Event()
    streams = [bytearray(), bytearray()]

    def kill_group():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def read(pipe, output):
        try:
            while True:
                chunk = os.read(pipe.fileno(), 8192)
                if not chunk:
                    break
                remaining = limit - len(output)
                output.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
                    kill_group()
                    break
        finally:
            pipe.close()

    def write():
        try:
            remaining = memoryview(payload)
            while remaining:
                remaining = remaining[os.write(process.stdin.fileno(), remaining):]
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    threads = [threading.Thread(target=read, args=(process.stdout, streams[0]), daemon=True),
               threading.Thread(target=read, args=(process.stderr, streams[1]), daemon=True),
               threading.Thread(target=write, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=max(0, deadline - time.monotonic()))
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise subprocess.TimeoutExpired(command, timeout)
    except subprocess.TimeoutExpired:
        kill_group()
        process.wait()
        for thread in threads:
            thread.join(timeout=2)
        raise
    if exceeded.is_set():
        raise SceneError('scene_synthesizer backend output exceeds limit')
    return process.returncode, bytes(streams[0]), bytes(streams[1])


def _run_backend(request):
    """Run a fixed local worker, not caller-provided code, in the chosen Python."""
    executable = os.environ.get('SIMSCENE_LAYOUT_PYTHON') or sys.executable
    worker = Path(__file__).with_name('layout_synthesis_worker.py').resolve()
    payload = json.dumps(request, allow_nan=False).encode()
    if len(payload) > 1024 * 1024:
        raise SceneError('scene_synthesizer request exceeds limit')
    try:
        code, stdout, stderr = _bounded_process([executable, '-I', str(worker)], payload)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SceneError('scene_synthesizer backend unavailable or timed out; configure '
                         'SIMSCENE_LAYOUT_PYTHON for an isolated 1.15.0 environment') from error
    if code:
        diagnostic = stderr.decode(errors='replace')[-1500:].strip()
        raise SceneError('scene_synthesizer backend failed; configure SIMSCENE_LAYOUT_PYTHON '
                         'for an isolated 1.15.0 environment: ' + diagnostic)
    try:
        return json.loads(stdout)
    except (ValueError, UnicodeError) as error:
        raise SceneError('scene_synthesizer backend returned invalid JSON') from error


def plan_layout(scene, ids, support, *, support_surface=None, seed=0, clearance_m=.01,
                gap_m=0., avoid_ids=None, keepout_bounds=None):
    """Return ordinary checked ``place_on`` edits without modifying *scene*.

    Support and object positions use metres and Z-up. The optional backend
    samples conservative render-AABB proxies; this is not a PhysX collision
    or dynamic-stability certificate.
    """
    if not isinstance(scene, dict) or not isinstance(scene.get('objects'), dict):
        raise SceneError('layout requires a scene with objects')
    revision = scene.get('revision')
    if type(revision) is not int or revision < 0:
        raise SceneError('layout requires a nonnegative scene revision')
    world = scene.get('world', {})
    if not isinstance(world, dict) or world.get('units', 'm') != 'm' or world.get('up_axis', 'Z') != 'Z':
        raise SceneError('layout requires a metre Z-up scene')
    objects = scene['objects']
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 8 or
            not all(isinstance(name, str) and name in objects for name in ids) or len(ids) != len(set(ids))):
        raise SceneError('layout requires 1..8 distinct existing object IDs')
    if not isinstance(support, str) or support not in objects or support in ids:
        raise SceneError('layout requires a distinct existing support')
    if not isinstance(objects[support], dict) or any(not isinstance(objects[name], dict) for name in ids):
        raise SceneError('layout objects must be scene object mappings')
    if objects[support].get('dynamic') is True:
        raise SceneError('layout support must be static')
    if support_surface is not None and (not isinstance(support_surface, str) or not support_surface):
        raise SceneError('support_surface must name an explicit support region')
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise SceneError('seed must be an integer in [0, 2**32)')
    clearance = _finite_number(clearance_m, 'clearance_m', 0, .5)
    gap = _finite_number(gap_m, 'gap_m', 0, .1)
    avoid = [] if avoid_ids is None else avoid_ids
    if (not isinstance(avoid, list) or len(avoid) > 32 or
            any(not isinstance(name, str) or name not in objects or name in ids or name == support for name in avoid) or
            len(set(avoid)) != len(avoid)):
        raise SceneError('avoid_ids must name distinct existing obstacles outside the placement and support')
    keepouts = [] if keepout_bounds is None else keepout_bounds
    if not isinstance(keepouts, list) or len(keepouts) > 32:
        raise SceneError('keepout_bounds must contain at most 32 world-space bounds')
    for box in keepouts:
        if (not isinstance(box, dict) or set(box) != {'min', 'max'} or
                not vector(box.get('min')) or not vector(box.get('max')) or
                any(a >= b for a, b in zip(box['min'], box['max']))):
            raise SceneError('invalid keepout bounds')
    related = [support, *ids, *avoid]
    for child in objects.values():
        if isinstance(child, dict) and isinstance(child.get('rigid_attachment'), dict) and child['rigid_attachment'].get('body') in related:
            raise SceneError('layout of compounds with attached visuals is not supported; prepare a verified asset instead')
    from .physics_binding import validate_asset_binding
    source_pins = []
    manifests = {}
    for name in related:
        obj = objects[name]
        if not isinstance(obj, dict):
            raise SceneError('layout objects must be scene object mappings')
        if obj.get('kind') != 'asset':
            continue
        if not obj.get('asset_binding'):
            raise SceneError('layout imported assets require a verified prepared binding: ' + name)
        try:
            manifest = validate_asset_binding(obj['asset_binding'], require_dynamic=obj.get('dynamic') is True,
                                              asset_path=obj.get('asset_path'))
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise SceneError('layout prepared asset ' + name + ': ' + str(error)) from error
        manifests[name] = manifest
        source_pins.append({'id': name, 'status': 'verified_prepared',
                            'manifest_sha256': obj['asset_binding']['manifest_sha256'],
                            'profile_id': manifest.get('profile_id')})
    support_obj = objects[support]
    dynamic_ids = [name for name in ids if objects[name].get('dynamic') is True]

    def primitive_has_collider(obj):
        if obj.get('collision', obj.get('dynamic', False)) is not True:
            return False
        if obj.get('kind') == 'compound':
            parts = obj.get('parts', [])
            return isinstance(parts, list) and any(isinstance(part, dict) and part.get('collision', True) is True for part in parts)
        return obj.get('kind') in ('box', 'sphere', 'cylinder', 'capsule')

    if support_obj.get('kind') == 'asset':
        manifest = manifests[support]
        if (manifest.get('profile_id') not in ('static_fixture_v1', 'container_v1') or
                not any(entry.get('collider_relative_prim_paths') for entry in manifest.get('body_map', {}).values())):
            raise SceneError('imported support requires a prepared static collision fixture')
        # The manifest hash alone does not establish static physics. The common
        # exporter opens the actual USD and checks authored units, actual
        # colliders, dynamic schemas, executable graphs and dependency closure.
        bounds(support_obj, scene, support)
        # The generic exporter does not traverse instance proxies when checking
        # static assets. Reject instances here until that whole graph is admitted.
        from pxr import Usd
        stage = Usd.Stage.Open(str(Path(support_obj['asset_path']).expanduser().resolve()))
        if not stage or any(prim.IsInstance() or prim.IsInstanceable() for prim in stage.TraverseAll()):
            raise SceneError('instanced imported support is not supported by the layout planner')
    elif dynamic_ids and not primitive_has_collider(support_obj):
        raise SceneError('dynamic layout objects require an enabled collision support')
    for name in dynamic_ids:
        obj = objects[name]
        if obj.get('kind') != 'asset' and not primitive_has_collider(obj):
            raise SceneError('dynamic layout object requires an enabled collision shape: ' + name)
        item_exclusions, support_exclusions = obj.get('collision_exclusions', []), support_obj.get('collision_exclusions', [])
        if not isinstance(item_exclusions, list) or not isinstance(support_exclusions, list):
            raise SceneError('collision exclusions must be lists')
        if support in item_exclusions or name in support_exclusions:
            raise SceneError('layout support and dynamic object have collision exclusions: ' + name)
    region, orientation, position = surface(objects[support], support_surface)
    if any(objects[name].get('rigid_attachment') for name in ids):
        raise SceneError('arrange physical parents rather than attached visuals')
    center = [(region['min_xy'][i] + region['max_xy'][i]) / 2 for i in range(2)]
    items = []
    for name in ids:
        box = _local_box(bounds(objects[name], scene, name), orientation, position)
        size = [box['max'][i] - box['min'][i] for i in range(3)]
        if any(not math.isfinite(value) or value <= 0 for value in size):
            raise SceneError('layout object requires finite positive measured bounds: ' + name)
        items.append({'id': name, 'size_m': size})
    reserved = [dict(copy.deepcopy(rect), kind='excluded_support') for rect in region.get('exclude', [])]
    for name in avoid:
        if not isinstance(objects[name], dict):
            raise SceneError('obstacle must be a scene object mapping')
        local = _local_box(bounds(objects[name], scene, name), orientation, position)
        reserved.append({'min_xy': local['min'][:2], 'max_xy': local['max'][:2], 'kind': 'obstacle'})
    for box in keepouts:
        local = _local_box(box, orientation, position)
        reserved.append({'min_xy': local['min'][:2], 'max_xy': local['max'][:2], 'kind': 'keepout'})
    request = {'schema': 'simscene.scene_synthesizer.request.v1', 'seed': seed,
               'support': {'min_xy': list(region['min_xy']), 'max_xy': list(region['max_xy'])},
               'items': items, 'reserved_xy': reserved, 'clearance_m': clearance}
    result = _run_backend(request)
    backend = result.get('backend') if isinstance(result, dict) else None
    dependencies = backend.get('dependency_versions') if isinstance(backend, dict) else None
    native = backend.get('native_versions') if isinstance(backend, dict) else None
    version_string = lambda value: isinstance(value, str) and 0 < len(value) <= 128
    if (not isinstance(result, dict) or result.get('schema') != 'simscene.scene_synthesizer.placements.v1' or
            type(result.get('seed')) is not int or result['seed'] != seed or
            not isinstance(backend, dict) or backend.get('name') != 'scene_synthesizer' or
            backend.get('version') != '1.15.0' or not version_string(backend.get('python')) or
            not version_string(backend.get('platform')) or not version_string(backend.get('geometry')) or
            not isinstance(dependencies, dict) or not 7 <= len(dependencies) <= 512 or
            not {'numpy', 'trimesh', 'python-fcl', 'shapely', 'rtree', 'scipy', 'networkx'} <= set(dependencies) or
            not all(version_string(key) and version_string(value) for key, value in dependencies.items()) or
            not isinstance(native, dict) or not version_string(native.get('geos')) or
            not isinstance(result.get('placements'), list)):
        raise SceneError('scene_synthesizer returned an invalid response or unexpected version')
    selected = result['placements']
    if (len(selected) != len(ids) or any(not isinstance(row, dict) or set(row) != {'id', 'offset_xy'} for row in selected) or
            [row.get('id') for row in selected] != ids or any(not vector(row.get('offset_xy'), 2) for row in selected)):
        raise SceneError('scene_synthesizer returned missing, duplicate or invalid placements')
    probe = copy.deepcopy(scene)
    operations, placements = [], []
    footprints = []
    for row, item_spec in zip(selected, items):
        name = row['id']
        xy = [center[i] + row['offset_xy'][i] for i in range(2)]
        low = [xy[i] - item_spec['size_m'][i] / 2 for i in range(2)]
        high = [xy[i] + item_spec['size_m'][i] / 2 for i in range(2)]
        if any(low[i] < region['min_xy'][i] + clearance - 1e-7 or
               high[i] > region['max_xy'][i] - clearance + 1e-7 for i in range(2)):
            raise SceneError('placement exceeds support bounds or edge clearance')
        for other in [*reserved, *footprints]:
            if all(high[i] + clearance > other['min_xy'][i] + 1e-7 and
                   other['max_xy'][i] + clearance > low[i] + 1e-7 for i in range(2)):
                reason = 'reserved area' if other.get('kind') in {'excluded_support', 'keepout'} else 'clearance'
                raise SceneError('placement violates ' + reason)
        footprints.append({'min_xy': low, 'max_xy': high, 'kind': 'placed'})
        op = {'op': 'place_on', 'id': name, 'support': support, 'offset_xy': list(row['offset_xy']),
              'gap_m': gap, 'clearance_m': clearance, 'avoid_ids': [*avoid, *(item['id'] for item in placements)],
              'keepout_bounds': copy.deepcopy(keepouts)}
        if support_surface is not None:
            op['support_surface'] = support_surface
        # Re-evaluate real scene render bounds rather than trusting the worker.
        place_on(probe, op)
        item = probe['objects'][name]
        placements.append({'id': name, 'position_m': copy.deepcopy(item['position']),
                           'orientation_wxyz': copy.deepcopy(item.get('orientation_wxyz', [1, 0, 0, 0])),
                           'support_id': support, 'support_surface': support_surface})
        operations.append(op)
    problems = validate(probe)
    if problems:
        raise SceneError('proposed layout would not form a valid scene: ' + str(problems[:5]))
    # A matching set of box dimensions is not a matching scene. Bind the plan
    # to the actual objects, support, world, proposal and backend versions so a
    # change to a source, physical property, support pose or gap is visible.
    context = {'scene_id': scene.get('scene_id'), 'base_revision': revision, 'world': world, 'support_id': support,
               'support_surface': support_surface, 'gap_m': gap,
               'objects': {name: objects[name] for name in [support, *ids, *avoid]},
               'keepout_bounds': keepouts, 'request': request, 'backend': result['backend'],
               'placements': selected}
    identity = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode()).hexdigest()
    return {'schema': 'simscene.layout_plan.v1', 'base_revision': revision, 'seed': seed,
            'plan_sha256': identity, 'backend': result['backend'], 'placements': placements,
            'operations': operations, 'source_pins': source_pins, 'physics_tested': False,
            'scope': ('Conservative rendered-AABB proxies, explicit support/obstacles and unchanged object orientations. '
                      'Source USD and physics are not modified; actual colliders, unlisted obstacles, door sweep '
                      'and dynamic stability require separate checks. Obstacles and keepouts are projected in XY '
                      'regardless of height. Prepared packages were checked at planning time; recheck '
                      'their integrity and the actual physics when applying and running.')}
