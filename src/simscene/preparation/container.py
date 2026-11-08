"""Explicit measured open-box proxy; no automatic container inference."""
import math
from .profiles import PreparationError, number, vector


def validate_container(value):
    if not isinstance(value, dict) or set(value) != {'interior_bounds','wall_thickness_m','floor_thickness_m','opening_axis','test_object_size_m','geometry_note'}:
        raise PreparationError('physics_profile_unsupported','container_proxy requires measured interior_bounds, wall/floor thickness, +Z opening, test_object_size_m and geometry_note')
    bounds=value['interior_bounds']
    if not isinstance(bounds,dict) or set(bounds)!={'min','max'}:
        raise PreparationError('physics_profile_unsupported','container interior requires min/max')
    low=vector(bounds['min'],3,'container interior min');high=vector(bounds['max'],3,'container interior max')
    size=vector(value['test_object_size_m'],3,'container test object',positive=True)
    if any(a>=b or s>=b-a for a,b,s in zip(low,high,size)):
        raise PreparationError('physics_profile_unsupported','container probe must fit strictly inside measured cavity/opening')
    if value['opening_axis']!='+Z':
        raise PreparationError('physics_profile_unsupported','M2 explicit container supports upward +Z opening only')
    number(value['wall_thickness_m'],'container wall thickness',positive=True)
    number(value['floor_thickness_m'],'container floor thickness',positive=True)
    if not isinstance(value['geometry_note'],str) or len(value['geometry_note'].strip())<8:
        raise PreparationError('physics_profile_unsupported','container requires an explicit measured geometry_note')
    return value


def wall_boxes(value):
    """Five disjoint axis-aligned walls; nothing closes the opening."""
    validate_container(value)
    lo=value['interior_bounds']['min'];hi=value['interior_bounds']['max']
    width,depth,height=[b-a for a,b in zip(lo,hi)];x,y,z=[(a+b)/2 for a,b in zip(lo,hi)]
    t=value['wall_thickness_m'];f=value['floor_thickness_m']
    return {'floor':{'size_m':[width+2*t,depth+2*t,f],'position_m':[x,y,lo[2]-f/2]},
            'left':{'size_m':[t,depth+2*t,height],'position_m':[lo[0]-t/2,y,z]},
            'right':{'size_m':[t,depth+2*t,height],'position_m':[hi[0]+t/2,y,z]},
            'front':{'size_m':[width,t,height],'position_m':[x,lo[1]-t/2,z]},
            'back':{'size_m':[width,t,height],'position_m':[x,hi[1]+t/2,z]}}


def check_geometry(stage,value,tolerance):
    """Bounded surface evidence plus conservative empty-cavity admission.

    The cavity test rejects triangle bounding boxes entering the interior. It
    can reject some valid diagonal designs; it cannot certify arbitrary shapes.
    """
    import numpy as np
    from .inspect import world_triangles, _surface_distances
    validate_container(value);triangles=world_triangles(stage)
    lo=np.asarray(value['interior_bounds']['min']);hi=np.asarray(value['interior_bounds']['max'])
    margin=min(tolerance*.1, float(np.min(hi-lo))*.001)
    crossing=np.all(triangles.max(axis=1)>lo+margin,axis=1)&np.all(triangles.min(axis=1)<hi-margin,axis=1)
    opening_blocked=(np.all(triangles.max(axis=1)[:,:2]>lo[:2]+margin,axis=1)
        &np.all(triangles.min(axis=1)[:,:2]<hi[:2]-margin,axis=1)
        &(triangles.max(axis=1)[:,2]>hi[2]-margin)
        &(triangles.min(axis=1)[:,2]<hi[2]+value['test_object_size_m'][2]+margin))
    if crossing.any() or opening_blocked.any():
        raise PreparationError('physics_profile_unsupported','declared container cavity/opening is obstructed by source geometry')
    points=[]
    # Inside-facing surfaces: exact grid on floor and all four walls.
    for axis,planes in [(0,[lo[0],hi[0]]),(1,[lo[1],hi[1]]),(2,[lo[2]])]:
        others=[i for i in range(3) if i!=axis]
        for plane in planes:
            for a in (.1,.5,.9):
                for b in (.1,.5,.9):
                    point=(lo+hi)/2;point[axis]=plane
                    point[others[0]]=lo[others[0]]+a*(hi[others[0]]-lo[others[0]])
                    point[others[1]]=lo[others[1]]+b*(hi[others[1]]-lo[others[1]])
                    points.append(point)
    distances=_surface_distances(np.asarray(points),triangles)
    if max(distances)>tolerance:
        raise PreparationError('physics_profile_unsupported','container wall/floor proxy lacks measured source-surface agreement')
    return {'method':'45_inside_surface_grid_points_to_source_triangles_and_conservative_triangle_AABB_empty_cavity',
            'max_surface_error_m':max(distances),'proxy_tolerance_m':tolerance,'opening_axis':'+Z',
            'interior_bounds':value['interior_bounds'],'test_object_size_m':value['test_object_size_m'],
            'coverage_limit':'explicit axis-aligned cavity only; bounded surface sampling, not automatic container understanding',
            'runtime_validation':'not_run'}


def author_walls(stage,value,parameters):
    from pxr import UsdGeom,UsdPhysics,Gf
    from .usd_layers import _material
    paths=[]
    for name,box in wall_boxes(value).items():
        path='/Asset/Container/'+name
        cube=UsdGeom.Cube.Define(stage,path);cube.CreateSizeAttr(1)
        cube.AddTranslateOp().Set(Gf.Vec3d(*box['position_m']));cube.AddScaleOp().Set(Gf.Vec3f(*box['size_m']))
        cube.CreateVisibilityAttr('invisible');UsdPhysics.CollisionAPI.Apply(cube.GetPrim()).CreateCollisionEnabledAttr(True)
        _material(stage,cube.GetPrim(),parameters);paths.append(path.removeprefix('/Asset/'))
    return {'main':{'relative_prim_path':'Container','role':'static','visual_relative_prim_paths':['Visual'],
                    'collider_relative_prim_paths':paths}}
