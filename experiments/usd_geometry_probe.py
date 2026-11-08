"""Read-only CPU intersections with local USD polygon/box geometry.

Coordinates are stage-world axes scaled to metres; up-axis is reported, never
silently rotated. Native instance proxies retain their instance mesh paths.
Subdivision cages, unsupported shapes and ambiguous faces are not substituted
for rendered surfaces. Strict mode rejects connected displacement terminals;
explicit authored-base mode never establishes rendered-surface equivalence.
Provenance/content closure is a separate locked audit.

Primary schema references:
https://openusd.org/dev/api/class_usd_geom_mesh.html
https://openusd.org/dev/api/usd_geom_page_front.html
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdShade

SCHEMA = 'simscene.usd_geometry_probe.v2'
QUERY_SCOPES = ('strict', 'authored_base_geometry')


def require(value, message):
    if not value:
        raise ValueError(message)


def vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(type(x) in (float, int) and math.isfinite(x) for x in value)


def sub(a, b):return [x-y for x, y in zip(a, b)]
def dot(a, b):return sum(x*y for x, y in zip(a, b))
def cross(a, b):return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def length(a):return math.hypot(*a)


def segment_distance(point, first, last):
    edge = sub(last, first)
    fraction = max(0., min(1., dot(sub(point, first), edge)/dot(edge, edge)))
    return length(sub(point, [a+fraction*b for a, b in zip(first, edge)]))


def box_candidate(origin, direction, triangle, tolerance, limit):
    """Computational triangle culling only; never estimates an interior."""
    low, high = 0., limit if limit is not None else math.inf
    for axis in range(3):
        first = min(point[axis] for point in triangle)-tolerance
        last = max(point[axis] for point in triangle)+tolerance
        if direction[axis] == 0:
            if not first <= origin[axis] <= last:return False
        else:
            values = sorted(((first-origin[axis])/direction[axis], (last-origin[axis])/direction[axis]))
            low, high = max(low, values[0]), min(high, values[1])
            if low > high:return False
    return True


def local_layers(filename, maximum_layers=256):
    """Reject nonlocal composition before Stage.Open; never fetch/repair.

    Unsaved or stale process-wide Sdf caches are rejected, not overwritten.
    A large pre-existing cache requires a fresh CLI process rather than a
    potentially enormous text comparison. Shader resources are not loaded.
    """
    pending, seen = [Path(filename).expanduser().resolve()], set()
    while pending:
        path = pending.pop()
        require(path.is_file() and path.suffix.lower() in ('.usd', '.usda', '.usdc', '.sdf'), 'missing/unsupported local USD layer: '+str(path))
        if path in seen:continue
        seen.add(path);require(len(seen) <= maximum_layers, 'USD layer budget exceeded')
        try:fresh = Sdf.Layer.OpenAsAnonymous(str(path))
        except Tf.ErrorException as error:raise ValueError('cannot parse local USD layer: '+str(path)) from error
        require(fresh is not None, 'cannot read local USD layer: '+str(path))
        cached = Sdf.Layer.Find(str(path))
        if cached:
            require(not cached.dirty, 'unsaved USD cache edits; use a fresh read-only process')
            require(path.stat().st_size <= 1024*1024, 'large cached USD layer; use a fresh read-only process')
            require(cached.ExportToString() == fresh.ExportToString(), 'stale USD cache differs from file; use a fresh read-only process')
        for reference in set(fresh.GetExternalReferences()) | set(fresh.GetExternalAssetDependencies()):
            text = str(reference)
            require(text and '://' not in text and ':' not in text and '[' not in text and ']' not in text and '\\' not in text, 'nonlocal/package composition identifier is unsupported')
            dependency = Path(text)
            pending.append((dependency if dependency.is_absolute() else path.parent/dependency).resolve())
    return sorted(str(path) for path in seen)


def convex_triangles(points, tolerance):
    """Only planar, convex, non-self-intersecting ordered polygon boundaries."""
    require(len(points) >= 3, 'face has fewer than three vertices')
    edges = [sub(points[(i+1) % len(points)], p) for i, p in enumerate(points)]
    longest = max(map(length, edges))
    require(longest > tolerance and all(length(edge) > tolerance for edge in edges), 'degenerate face edge')
    require(all(length(sub(a, b)) > tolerance for i, a in enumerate(points) for b in points[i+1:]), 'repeated face vertex')
    origin = points[0]
    area = [sum(cross(sub(p, origin), sub(points[(i+1) % len(points)], origin))[axis] for i, p in enumerate(points)) for axis in range(3)]
    magnitude = length(area)
    require(magnitude > tolerance*longest, 'degenerate face area')
    normal = [x/magnitude for x in area]
    require(all(abs(dot(sub(point, origin), normal)) <= tolerance for point in points), 'nonplanar polygon is not a renderer-defined triangulation')
    # Every other vertex must be on the same side of each oriented edge;
    # local turning tests alone can incorrectly accept a self-intersecting star.
    require(all(dot(cross(edge, sub(point, points[i])), normal) >= -tolerance*length(edge) for i, edge in enumerate(edges) for point in points), 'concave or self-intersecting polygon is unsupported')
    result = []
    for index in range(1, len(points)-1):
        triangle = [points[0], points[index], points[index+1]]
        if length(cross(sub(triangle[1], triangle[0]), sub(triangle[2], triangle[0]))) > tolerance*longest:
            result.append((index-1, triangle))
    require(result, 'face has no nondegenerate triangles')
    return result


def intersection(origin, direction, triangle, tolerance):
    """Double-sided triangle hit; coplanar/ill-conditioned rays are explicit."""
    a, b, c = triangle;e1, e2 = sub(b, a), sub(c, a)
    normal = cross(e1, e2);area = length(normal);normal = [x/area for x in normal]
    offset, denominator = dot(sub(a, origin), normal), dot(direction, normal)
    if denominator == 0:
        return None, abs(offset) <= tolerance
    distance = offset/denominator
    if not math.isfinite(distance):return None, True
    if distance < -tolerance:return None, False
    point = [x+max(0., distance)*d for x, d in zip(origin, direction)]
    relative = sub(point, a)
    # Project on the largest normal component to avoid the Gram determinant's
    # cancellation for thin triangles.
    axis = max(range(3), key=lambda n: abs(normal[n]))
    first, second = [n for n in range(3) if n != axis]
    determinant = e1[first]*e2[second]-e1[second]*e2[first]
    u = (relative[first]*e2[second]-relative[second]*e2[first])/determinant
    v = (e1[first]*relative[second]-e1[second]*relative[first])/determinant
    barycentric = [1-u-v, u, v]
    heights = [area/length(sub(c, b)), area/length(sub(a, c)), area/length(sub(b, a))]
    if any(value*height < -tolerance for value, height in zip(barycentric, heights)):return None, False
    if min(barycentric) < 0 and min(segment_distance(point, first, last) for first, last in ((a,b),(b,c),(c,a))) > tolerance:return None, False
    return {'distance_m': max(0., distance), 'point_world_m': point, 'barycentric': barycentric,
            'boundary': any(value*height <= tolerance for value, height in zip(barycentric, heights)),
            'at_origin': abs(distance) <= tolerance, 'winding_normal_world': normal}, abs(denominator) < 1e-12


def _displacement_candidates(prim):
    """Record terminal connections, without evaluating any shader/material.

    GetBaseName() retains render contexts (e.g. mdl:displacement), so matching
    the final namespace component is essential. No material names are trusted.
    """
    candidates = []
    for target in [prim, *[child for child in prim.GetChildren() if child.IsA(UsdGeom.Subset)]]:
        material, _ = UsdShade.MaterialBindingAPI(target).ComputeBoundMaterial()
        if not material:continue
        for output in material.GetOutputs():
            name = str(output.GetFullName())
            connections = [str(path) for path in output.GetAttr().GetConnections()]
            if name.split(':')[-1] == 'displacement' and (connections or output.HasConnectedSource()):
                candidates.append({'geometry_path': str(prim.GetPath()), 'binding_prim_path': str(target.GetPath()),
                    'material_path': str(material.GetPath()), 'terminal': name, 'connections': connections,
                    'evaluation': 'not_evaluated'})
    return sorted(candidates,key=lambda item:(item['binding_prim_path'],item['material_path'],item['terminal']))


def _displacement_materials(prim):
    return sorted({item['material_path'] for item in _displacement_candidates(prim)})


def geometry(prim, cache, metres, tolerance, maximum_faces, scope='strict', _candidates=None):
    require(scope in QUERY_SCOPES, 'unknown geometry query scope')
    require(prim.IsA(UsdGeom.Mesh) or prim.IsA(UsdGeom.Cube), 'unsupported geometry type: '+prim.GetTypeName())
    ancestor = prim
    while ancestor and not ancestor.IsPseudoRoot():
        schemas = [str(name).lower() for name in ancestor.GetAppliedSchemas()]
        require(not any(any(word in name for word in ('skel','deformable','cloth')) for name in schemas) and not any(str(attr.GetName()).startswith(('skel:', 'primvars:skel:')) for attr in ancestor.GetAttributes()), 'skinning/deformation geometry is unsupported')
        ancestor = ancestor.GetParent()
    world = cache.GetLocalToWorldTransform(prim)
    require(all(math.isfinite(world[i][j]) for i in range(4) for j in range(4)), 'nonfinite transform')
    require(all(abs(world[i][3]) <= 1e-12 for i in range(3)) and abs(world[3][3]-1) <= 1e-12, 'projective transform is unsupported')
    determinant = dot(list(world[0])[:3], cross(list(world[1])[:3], list(world[2])[:3]))
    require(determinant != 0, 'singular transform is unsupported')
    gprim = UsdGeom.Gprim(prim)
    orientation = str(gprim.GetOrientationAttr().Get())
    require(orientation in ('rightHanded', 'leftHanded'), 'unsupported orientation')
    candidates = _displacement_candidates(prim) if _candidates is None else _candidates
    require(scope != 'strict' or not candidates, 'connected displacement material is unsupported: '+', '.join(sorted({item['material_path'] for item in candidates})))
    if prim.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(prim)
        require(mesh.GetSubdivisionSchemeAttr().Get() == UsdGeom.Tokens.none, 'subdivision cage is not the rendered limit surface')
        raw = mesh.GetPointsAttr().Get(cache.GetTime());counts = mesh.GetFaceVertexCountsAttr().Get(cache.GetTime());indices = mesh.GetFaceVertexIndicesAttr().Get(cache.GetTime())
        require(raw is not None and counts is not None and indices is not None and len(counts) > 0, 'missing/empty mesh points or topology')
        require(len(counts) <= maximum_faces and all(n >= 3 for n in counts) and sum(counts) == len(indices), 'invalid topology or face budget exceeded')
        require(all(0 <= index < len(raw) for index in indices), 'face point index out of range')
        holes = set(mesh.GetHoleIndicesAttr().Get(cache.GetTime()) or [])
        require(all(0 <= index < len(counts) for index in holes), 'hole face index out of range')
        faces, offset = [], 0
        for index, count in enumerate(counts):
            if index not in holes:faces.append((index, list(indices[offset:offset+count])))
            offset += count
        representation = 'polygon_mesh_none_verified_planar_convex_fan'
    elif prim.IsA(UsdGeom.Cube):
        size = UsdGeom.Cube(prim).GetSizeAttr().Get(cache.GetTime())
        require(type(size) in (int, float) and math.isfinite(size) and size > 0, 'invalid box size')
        half = size/2
        raw = [Gf.Vec3d(x*half, y*half, z*half) for x, y, z in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
        faces = list(enumerate([[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]))
        holes = set();representation = 'exact_authored_cube_box_faces'
    else:
        raise ValueError('unsupported geometry type: '+prim.GetTypeName())
    points = [[float(x)*metres for x in world.Transform(Gf.Vec3d(point))] for point in raw]
    require(all(vector(point) for point in points), 'nonfinite transformed point')
    triangles, rejected = [], []
    for face_index, face in faces:
        try:
            require(len(face) <= 1024, 'polygon vertex budget exceeded')
            face_points = [points[i] for i in face]
            edges = [(point, face_points[(i+1) % len(face_points)]) for i, point in enumerate(face_points)]
            for triangle_index, triangle in convex_triangles(face_points, tolerance):
                require(len(triangles) < maximum_faces, 'triangle budget exceeded')
                triangles.append({'face_index': face_index, 'triangle_index': triangle_index, 'points': triangle, 'face_edges': edges})
        except ValueError as error:
            rejected.append({'face_index': face_index, 'reason': str(error)})
    return triangles, {'mesh_path': str(prim.GetPath()), 'type': prim.GetTypeName(), 'representation': representation,
        'prototype_mesh_path': str(prim.GetPrimInPrototype().GetPath()) if prim.IsInstanceProxy() else None,
        'orientation': orientation, 'transform_handedness': -1 if determinant < 0 else 1,
        'double_sided': bool(gprim.GetDoubleSidedAttr().Get()), 'hole_face_count': len(holes), 'triangle_count': len(triangles), 'rejected_faces': rejected,
        'displacement_candidates': candidates, 'displacement_evaluation': 'not_evaluated', 'rendered_surface_equivalence': 'not_established',
        'prim_stack': [{'layer': spec.layer.realPath or spec.layer.identifier, 'path': str(spec.path)} for spec in prim.GetPrimStack()]}


def probe(filename, prim_path, rays, *, include_invisible=False, purposes=('default', 'render'), tolerance_m=1e-9, maximum_faces_per_prim=1000000, scope='strict'):
    require(scope in QUERY_SCOPES, 'unknown geometry query scope; authored mode requires explicit selection')
    require(type(tolerance_m) in (int, float) and math.isfinite(tolerance_m) and tolerance_m > 0, 'positive finite metre tolerance required')
    require(type(include_invisible) is bool and set(purposes) <= {'default', 'render', 'proxy', 'guide'} and purposes, 'invalid visibility/purpose selection')
    require(type(maximum_faces_per_prim) is int and maximum_faces_per_prim > 0, 'positive face budget required')
    require(isinstance(rays, list) and rays and len(rays) <= 10000, 'provide 1..10000 explicit world rays')
    filename = Path(filename).expanduser().resolve();layers = local_layers(filename)
    try:stage = Usd.Stage.Open(str(filename))
    except Tf.ErrorException as error:raise ValueError('cannot compose local USD stage') from error
    require(stage is not None, 'cannot open local USD stage')
    root = stage.GetPrimAtPath(prim_path)
    require(root and root.IsActive() and root.IsDefined() and root.IsLoaded(), 'selected prim is missing/inactive/undefined/unloaded')
    metres = UsdGeom.GetStageMetersPerUnit(stage)
    require(math.isfinite(metres) and metres > 0, 'invalid stage metres-per-unit')
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    surfaces, excluded, unsupported, meshes, candidates = [], [], [], [], []
    for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
        if not prim.IsActive() or not prim.IsDefined() or not prim.IsLoaded():continue
        imageable = UsdGeom.Imageable(prim)
        visible = not imageable or imageable.ComputeVisibility() != UsdGeom.Tokens.invisible
        purpose = str(imageable.ComputePurpose()) if imageable else 'default'
        if not include_invisible and not visible or purpose not in purposes:
            excluded.append({'path': str(prim.GetPath()), 'reason': 'visibility_or_purpose', 'visible': visible, 'purpose': purpose});continue
        if not prim.IsA(UsdGeom.Gprim) and not prim.IsA(UsdGeom.PointInstancer):continue
        prim_candidates = _displacement_candidates(prim)
        candidates.extend(prim_candidates)
        try:
            triangles, identity = geometry(prim, cache, metres, tolerance_m, maximum_faces_per_prim, scope, _candidates=prim_candidates)
            identity.update(visible=visible, purpose=purpose)
            meshes.append(identity)
            surfaces.extend((triangle, identity) for triangle in triangles)
            unsupported.extend({'path': identity['mesh_path'], **failure} for failure in identity['rejected_faces'])
        except ValueError as error:
            unsupported.append({'path': str(prim.GetPath()), 'type': prim.GetTypeName(), 'reason': str(error), 'displacement_candidates': prim_candidates})
    require(len(surfaces)*len(rays) <= 10000000, 'ray/triangle budget exceeded; use smaller explicit subtree or ray batches')
    results = []
    for index, ray in enumerate(rays):
        require(isinstance(ray, dict) and {'origin_world_m','direction_world'} <= set(ray) <= {'id','origin_world_m','direction_world','maximum_distance_m'}, 'invalid ray fields')
        require(vector(ray['origin_world_m']) and vector(ray['direction_world']) and math.isfinite(length(ray['direction_world'])) and length(ray['direction_world']) > 0, 'finite origin and nonzero finite-norm direction required')
        limit = ray.get('maximum_distance_m')
        require(limit is None or type(limit) in (int, float) and math.isfinite(limit) and limit > 0, 'invalid ray maximum distance')
        direction = [x/length(ray['direction_world']) for x in ray['direction_world']]
        hits, ambiguities = [], []
        for triangle, identity in surfaces:
            if not box_candidate(ray['origin_world_m'],direction,triangle['points'],tolerance_m,limit):continue
            hit, ambiguous = intersection(ray['origin_world_m'], direction, triangle['points'], tolerance_m)
            if ambiguous:
                ambiguities.append({'mesh_path': identity['mesh_path'], 'face_index': triangle['face_index'], 'reason': 'coplanar_or_ill_conditioned_ray'})
            if hit is None or limit is not None and hit['distance_m'] > limit+tolerance_m:continue
            sign = identity['transform_handedness']*(-1 if identity['orientation'] == 'leftHanded' else 1)
            normal = [sign*x for x in hit['winding_normal_world']]
            hit['triangle_boundary'] = hit['boundary']
            hit['boundary'] = any(segment_distance(hit['point_world_m'], first, last) <= tolerance_m for first, last in triangle['face_edges'])
            duplicate = next((old for old in hits if old['mesh_path'] == identity['mesh_path'] and old['face_index'] == triangle['face_index'] and abs(old['distance_m']-hit['distance_m']) <= tolerance_m), None)
            if duplicate:
                duplicate['triangle_indices'].append(triangle['triangle_index']);continue
            hits.append({**hit, 'normal_world': normal, 'front_facing': dot(normal,direction) < 0,
                'mesh_path': identity['mesh_path'], 'prototype_mesh_path': identity['prototype_mesh_path'], 'face_index': triangle['face_index'],
                'triangle_indices': [triangle['triangle_index']], 'representation': identity['representation']})
        hits.sort(key=lambda h: (h['distance_m'], h['mesh_path'], h['face_index']))
        results.append({'id': ray.get('id', index), 'origin_world_m': ray['origin_world_m'], 'direction_world_unit': direction, 'maximum_distance_m': limit,
                        'complete_for_supported_query': bool(surfaces) and not unsupported and not ambiguities and not stage.GetCompositionErrors(), 'hits': hits, 'ambiguities': ambiguities})
    complete = all(result['complete_for_supported_query'] for result in results)
    return {'schema': SCHEMA, 'query_scope': scope, 'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'usd_version': list(Usd.GetVersion()), 'stage': str(filename), 'prim_subtree': str(root.GetPath()), 'time_code': 'default',
        'units': {'metres_per_stage_unit': metres, 'metres_per_unit_authored': stage.HasAuthoredMetadata('metersPerUnit'), 'up_axis': str(UsdGeom.GetStageUpAxis(stage)), 'up_axis_authored': stage.HasAuthoredMetadata('upAxis'), 'coordinates': 'stage world axes scaled to metres; no up-axis remap'},
        'selection': {'include_invisible': include_invisible, 'purposes': list(purposes), 'maximum_faces_per_prim': maximum_faces_per_prim, 'maximum_ray_triangle_tests': 10000000},
        'tolerance_m': tolerance_m, 'local_composition_layers': layers, 'composition_errors': [str(error) for error in stage.GetCompositionErrors()],
        'meshes': meshes, 'excluded': excluded, 'unsupported': unsupported, 'rays': results,
        'complete': complete, 'geometry_query_complete': complete, 'completeness_scope': 'Only the explicitly selected source-geometry query; never renderer equivalence.',
        'displacement_candidates': candidates, 'displacement_evaluation': 'not_evaluated', 'rendered_surface_equivalence': 'not_established', 'rendered_surface_query_complete': False,
        'limits': ['Geometric evidence only; complete content provenance must be checked separately.', 'Both face sides are intersected; shading normals, normal maps, opacity/culling and renderer tessellation are not simulated.', 'normal_world follows Gprim orientation and transform handedness; winding_normal_world records triangle winding. Neither is an interpolated shading normal.', 'Strict scope rejects connected displacement candidates in every render context. Explicit authored_base_geometry scope reads unmodified positions and records unevaluated candidates; it never proves renderer equivalence.', 'Subdivision cages/skinning, concave/nonplanar/invalid faces, point instancers and unsupported primitives remain unsupported in both scopes.', 'Polygons must be planar/convex within tolerance; fan diagonals deduplicate per original face, distinct faces remain distinct.', 'Ray sets can form a sampled cross-section; no unprobed space or cup interior is inferred from an AABB.', 'No live PhysX cooked collider or rendered-pixel surface is read; authored polygon/Cube geometry only.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage');parser.add_argument('--prim', required=True);parser.add_argument('--rays', required=True)
    parser.add_argument('--output');parser.add_argument('--include-invisible', action='store_true');parser.add_argument('--purposes', default='default,render');parser.add_argument('--tolerance-m', type=float, default=1e-9)
    parser.add_argument('--scope',choices=QUERY_SCOPES,default='strict')
    args = parser.parse_args()
    result = probe(args.stage,args.prim,json.loads(Path(args.rays).read_text()),include_invisible=args.include_invisible,purposes=tuple(args.purposes.split(',')),tolerance_m=args.tolerance_m,scope=args.scope)
    if args.output:
        with Path(args.output).open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
        print(json.dumps({'complete':result['complete'],'query_scope':result['query_scope'],'geometry_query_complete':result['geometry_query_complete'],'rendered_surface_equivalence':result['rendered_surface_equivalence'],'rendered_surface_query_complete':result['rendered_surface_query_complete'],'output':args.output}))
    else:print(json.dumps(result,indent=2,allow_nan=False))
    return 0 if result['complete'] else 1


if __name__ == '__main__':raise SystemExit(main())
