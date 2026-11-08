"""Read-only continuous triangle/OBB surface query of local authored USD.

This is not an inside/cavity/containment test. A box wholly outside a cup and a
box wholly within its cavity can both have no surface intersections. Source
content provenance is independently locked; no GPU, renderer or PhysX is used.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import usd_geometry_probe as g
from pxr import Tf, Usd, UsdGeom

SCHEMA = 'simscene.usd_box_surface_probe.v1'
GEOMETRY_HELPER_SHA256 = '572671cb3d8baab09f01d85e583c127e660566596751e144e1dc423386d438f7'
EXPANSION_M = Fraction(1, 1_000_000_000)
AXIS_VALIDITY_TOLERANCE = Fraction(1, 1_000_000_000_000)
MAXIMUM_TRIANGLES = 100_000


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _rational(vector):return [Fraction(value) for value in vector]
def _dot(a, b):return sum(x*y for x, y in zip(a, b) if x and y)
def _sub(a, b):return [x-y for x, y in zip(a, b)]
def _cross(a, b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def _json_safe(value):
    if isinstance(value, dict):return {str(k):_json_safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):return [_json_safe(v) for v in value]
    if type(value) is float and not math.isfinite(value):return {'invalid_nonfinite_float':repr(value)}
    if value is None or type(value) in (str,int,float,bool):return value
    return {'invalid_value_type':type(value).__name__,'repr':repr(value)}


def _axis_bounds(axis, box):
    widths = [abs(_dot(axis,edge)) for edge in box['axes']]
    radius = sum(half*width for half,width in zip(box['half'],widths))
    return radius,radius+EXPANSION_M*sum(widths)


def _box(value):
    g.require(isinstance(value, dict) and set(value) == {'center_world_m', 'axes_world', 'half_size_m'}, 'provide exact center_world_m/axes_world/half_size_m box fields')
    g.require(g.vector(value['center_world_m']) and g.vector(value['half_size_m']) and min(value['half_size_m']) > 0, 'box center/positive half sizes must be finite three-vectors')
    axes = value['axes_world']
    g.require(isinstance(axes, list) and len(axes) == 3 and all(g.vector(axis) for axis in axes), 'provide three finite unit orthogonal axes')
    rational = [_rational(axis) for axis in axes]
    g.require(all(abs(_dot(first, second)-(1 if i == j else 0)) <= AXIS_VALIDITY_TOLERANCE for i, first in enumerate(rational) for j, second in enumerate(rational)), 'box axes must be unit and orthogonal within 1e-12, without normalization')
    result = {'center':_rational(value['center_world_m']), 'axes':rational, 'half':_rational(value['half_size_m'])}
    result['face_axes'] = []
    for i in range(3):
        axis = _cross(rational[(i+1) % 3],rational[(i+2) % 3])
        result['face_axes'].append((f'box_face_{i}',axis,*_axis_bounds(axis,result)))
    return result


def triangle_box(triangle, box):
    """Exact rational SAT on the represented finite inputs, not sampled corners.

    Accepted axes are used unchanged: the represented box is precisely
    center + sum(t_i*axis_i), abs(t_i)<=half_i. Face normals use cross products
    rather than assuming finite-precision axes are perfectly orthogonal.
    """
    g.require(isinstance(triangle, list) and len(triangle) == 3 and all(g.vector(point) for point in triangle), 'triangle needs three finite world points')
    points = [_sub(_rational(point), box['center']) for point in triangle]
    edges = [_sub(points[(i+1) % 3], points[i]) for i in range(3)]
    normal = _cross(edges[0], edges[1])
    if not any(normal):
        return {'classification':'ambiguous', 'reason':'degenerate_represented_triangle', 'axis_checks':0}
    def axes():
        yield from box['face_axes']
        yield ('triangle_normal',normal,*_axis_bounds(normal,box))
        for i,edge in enumerate(edges):
            for j,box_edge in enumerate(box['axes']):
                axis = _cross(edge,box_edge)
                if any(axis):yield (f'edge_{i}_cross_box_{j}',axis,*_axis_bounds(axis,box))
    original_separations, boundaries, checks = [], [], 0
    for name,axis,radius,expanded_radius in axes():
        if not any(axis):continue  # Exactly zero redundant axis only.
        checks += 1
        projections = [_dot(point,axis) for point in points]
        low,high = min(projections),max(projections)
        if low > expanded_radius or high < -expanded_radius:
            return {'classification':'separated', 'separating_axis':name, 'axis_checks':checks}
        if low > radius or high < -radius:original_separations.append(name)
        if low == radius or high == -radius:boundaries.append(name)
    if original_separations:
        return {'classification':'ambiguous','reason':'only_expanded_box_overlaps',
                'original_separating_axes':original_separations,'axis_checks':checks}
    return {'classification':'touching' if boundaries else 'intersecting',
            'exact_boundary_axes':boundaries,'axis_checks':checks}


def _normals(points, identity):
    edges = [_sub(_rational(points[i]),_rational(points[0])) for i in (1,2)]
    normal = _cross(*edges)
    scale = max(map(abs,normal))
    g.require(scale > 0, 'degenerate represented triangle normal')
    scaled = [float(value/scale) for value in normal]
    winding = [value/math.hypot(*scaled) for value in scaled]
    sign = identity['transform_handedness']*(-1 if identity['orientation'] == 'leftHanded' else 1)
    return {'winding_normal_world':winding,'normal_world':[sign*value for value in winding]}


def probe(filename, prim_path, box, *, scope='strict', include_invisible=False,
          purposes=('default','render'), maximum_faces_per_prim=50_000, maximum_triangles=50_000,
          maximum_prims=10_000):
    result = {'schema':SCHEMA,'helper_sha256':_sha(__file__),'geometry_helper_sha256':_sha(g.__file__),
        'stage':str(filename),'prim_subtree':prim_path,'query_scope':scope,'box':box,
        'fixed_half_size_expansion_m':float(EXPANSION_M),'axis_orthonormality_validity_bound':float(AXIS_VALIDITY_TOLERANCE),
        'arithmetic':'Exact Fraction SAT on the finite binary inputs produced by the pinned geometry reader; no floating projection or axis normalization.',
        'box_interpretation':'center + sum(t_i*axes_world[i]), abs(t_i)<=half_size_m[i], with axes used unchanged.',
        'completeness_scope':'Only the selected authored query on represented transformed finite vertices and original input axes; not symbolic transform accuracy, renderer equivalence, physical clearance or containment.',
        'time_code':'default','meshes':[],'excluded':[],'unsupported':[],'resource_failures':[],
        'input_errors':[],'composition_errors':[],'intersecting_faces':[],'touching_faces':[],
        'ambiguous_faces':[],'displacement_candidates':[],'triangles_examined':0,'separated_triangles':0,'sat_axis_checks':0,
        'prims_visited':0,'supported_authored_faces_read':0,'supported_triangles_read':0,'traversal_completed':False,
        'selection':{'include_invisible':include_invisible,'purposes':_json_safe(purposes),'maximum_faces_per_prim':maximum_faces_per_prim,'maximum_triangles':maximum_triangles,
            'maximum_prims':maximum_prims,'maximum_sat_axes_per_triangle':13,
            'maximum_total_sat_axis_checks':13*maximum_triangles if type(maximum_triangles) is int else None},
        'complete':False,'geometry_query_complete':False,'surface_disjointness_established':False,
        'containment_established':False,'cavity_membership':'not_assessed',
        'rendered_surface_equivalence':'not_established','rendered_surface_query_complete':False,'displacement_evaluation':'not_evaluated',
        'limits':['Surface intersections only: disjointness never implies inside a cup or any cavity, or containment.',
            'All valid selected triangles are tested continuously by SAT; this is not vertex/ray sampling.',
            'Fixed 1nm expands half sizes only; near-boundary cases are ambiguous/incomplete, never clear.',
            'Exact arithmetic starts from the geometry reader\'s represented transformed finite vertices, not symbolic USD transforms or a renderer.',
            'Visibility/purpose selection is explicit; normals do not simulate shading, opacity or backface culling.',
            'Subdivision/deformation/unsupported or rejected faces, composition errors and budget failures make the whole query incomplete.',
            'No renderer, PhysX cooked collider, continuous curved limit surface or provenance proof is read.',
            'A future cavity decision also requires independent mouth/interior-side/center witnesses; this tool never supplies that decision.']}
    try:
        g.require(result['geometry_helper_sha256'] == GEOMETRY_HELPER_SHA256, 'frozen geometry-probe-v2 bytes changed')
        g.require(scope in g.QUERY_SCOPES, 'unknown query scope')
        prepared = _box(box)
        g.require(type(include_invisible) is bool and purposes and set(purposes) <= {'default','render','proxy','guide'}, 'invalid visibility/purpose selection')
        for value in (maximum_faces_per_prim,maximum_triangles):
            g.require(type(value) is int and 0 < value <= MAXIMUM_TRIANGLES, 'face/triangle budgets must be integers in 1..100000')
        g.require(type(maximum_prims) is int and 0 < maximum_prims <= 10_000, 'prim budget must be an integer in 1..10000')
        filename = Path(filename).expanduser().resolve()
        result['stage'] = str(filename)
        result['local_composition_layers'] = g.local_layers(filename)
        stage = Usd.Stage.Open(str(filename))
        g.require(stage is not None, 'cannot open local USD stage')
        root = stage.GetPrimAtPath(prim_path)
        g.require(root and root.IsActive() and root.IsDefined() and root.IsLoaded(), 'selected prim missing/inactive/undefined/unloaded')
        metres = UsdGeom.GetStageMetersPerUnit(stage)
        g.require(math.isfinite(metres) and metres > 0, 'invalid stage metres-per-unit')
        result['units'] = {'metres_per_stage_unit':metres,'metres_per_unit_authored':stage.HasAuthoredMetadata('metersPerUnit'),
                           'up_axis':str(UsdGeom.GetStageUpAxis(stage)),'up_axis_authored':stage.HasAuthoredMetadata('upAxis'),
                           'coordinates':'stage world axes scaled to metres; no up-axis remap'}
        result['usd_version'] = list(Usd.GetVersion())
        result['composition_errors'] = [str(error) for error in stage.GetCompositionErrors()]
        cache = UsdGeom.XformCache(Usd.TimeCode.Default())
        for prim in Usd.PrimRange(root,Usd.TraverseInstanceProxies()):
            if result['prims_visited'] >= maximum_prims:
                result['resource_failures'].append({'reason':'prim traversal budget exceeded','next_prim':str(prim.GetPath()),'traversal_terminated_before_completion':True});break
            result['prims_visited']+=1
            if not prim.IsActive() or not prim.IsDefined() or not prim.IsLoaded():continue
            imageable = UsdGeom.Imageable(prim)
            visible = not imageable or imageable.ComputeVisibility() != UsdGeom.Tokens.invisible
            purpose = str(imageable.ComputePurpose()) if imageable else 'default'
            if not include_invisible and not visible or purpose not in purposes:
                result['excluded'].append({'path':str(prim.GetPath()),'reason':'visibility_or_purpose','visible':visible,'purpose':purpose});continue
            if not prim.IsA(UsdGeom.Gprim) and not prim.IsA(UsdGeom.PointInstancer):continue
            candidates = g._displacement_candidates(prim)
            result['displacement_candidates'].extend(candidates)
            try:
                triangles,identity = g.geometry(prim,cache,metres,float(EXPANSION_M),maximum_faces_per_prim,scope,_candidates=candidates)
            except ValueError as error:
                result['unsupported'].append({'path':str(prim.GetPath()),'type':prim.GetTypeName(),'reason':str(error),'displacement_candidates':candidates});continue
            identity.update(visible=visible,purpose=purpose,triangles_examined=0,
                authored_face_count=len(UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get()) if prim.IsA(UsdGeom.Mesh) else 6,
                valid_triangulated_face_count=len({t['face_index'] for t in triangles}))
            result['meshes'].append(identity)
            result['supported_authored_faces_read']+=identity['authored_face_count']
            result['supported_triangles_read']+=len(triangles)
            result['unsupported'].extend({'path':identity['mesh_path'],**failure} for failure in identity['rejected_faces'])
            if result['triangles_examined']+len(triangles)>maximum_triangles:
                result['resource_failures'].append({'reason':'total triangle budget exceeded','mesh_path':identity['mesh_path'],
                    'unprocessed_triangles_in_this_mesh':len(triangles),'traversal_terminated_before_completion':True})
                break
            for triangle in triangles:
                relation = triangle_box(triangle['points'],prepared)
                result['triangles_examined']+=1;identity['triangles_examined']+=1
                result['sat_axis_checks']+=relation['axis_checks']
                if relation['classification']=='separated':
                    result['separated_triangles']+=1;continue
                face = {**relation,'mesh_path':identity['mesh_path'],'prototype_mesh_path':identity['prototype_mesh_path'],
                    'face_index':triangle['face_index'],'triangle_index':triangle['triangle_index'],
                    'triangle_points_world_m':triangle['points'],'representation':identity['representation']}
                if relation.get('reason') != 'degenerate_represented_triangle':face.update(_normals(triangle['points'],identity))
                result[{'intersecting':'intersecting_faces','touching':'touching_faces','ambiguous':'ambiguous_faces'}[relation['classification']]].append(face)
        else:
            result['traversal_completed'] = True
        complete = result['traversal_completed'] and bool(result['triangles_examined']) and not any(result[key] for key in ('unsupported','resource_failures','ambiguous_faces','composition_errors'))
        result.update(complete=complete,geometry_query_complete=complete,
            surface_disjointness_established=complete and not result['intersecting_faces'] and not result['touching_faces'])
    except (ValueError,TypeError,Tf.ErrorException,ArithmeticError,MemoryError) as error:
        result['input_errors'].append({'type':type(error).__name__,'reason':str(error)})
        result['box'] = _json_safe(box)
        result['selection'] = _json_safe(result['selection'])
        result['prim_subtree'] = _json_safe(prim_path)
        result['query_scope'] = _json_safe(scope)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage');parser.add_argument('--prim',required=True);parser.add_argument('--box',required=True)
    parser.add_argument('--scope',choices=g.QUERY_SCOPES,default='strict');parser.add_argument('--output',required=True)
    parser.add_argument('--include-invisible',action='store_true');parser.add_argument('--purposes',default='default,render')
    parser.add_argument('--maximum-faces-per-prim',type=int,default=50_000);parser.add_argument('--maximum-triangles',type=int,default=50_000)
    parser.add_argument('--maximum-prims',type=int,default=10_000)
    args=parser.parse_args()
    try:
        box=json.loads(Path(args.box).read_text());box_error=None
    except (OSError,ValueError) as error:
        box=None;box_error=str(error)
    result=probe(args.stage,args.prim,box,scope=args.scope,
        include_invisible=args.include_invisible,purposes=tuple(args.purposes.split(',')),
        maximum_faces_per_prim=args.maximum_faces_per_prim,maximum_triangles=args.maximum_triangles,maximum_prims=args.maximum_prims)
    if box_error is not None:result['input_errors'].append({'type':'box_file_error','reason':box_error})
    with Path(args.output).open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('complete','geometry_query_complete','surface_disjointness_established','containment_established','rendered_surface_equivalence')}))
    return 0 if result['complete'] else 1


if __name__=='__main__':raise SystemExit(main())
