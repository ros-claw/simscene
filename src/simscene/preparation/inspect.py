"""Measured USD facts and bounded, disclosed collision surface sampling."""
import math
from .profiles import PreparationError


def reject_executable_graphs(stage):
    # These profiles support data-only geometry and explicitly declared physics.
    # Never carry an upstream action/Python graph into the playing Kit stage.
    for prim in stage.Traverse():
        if prim.GetTypeName().lower().startswith(('omnigraph','pythonscript','scriptnode')):
            raise PreparationError('physics_profile_unsupported','executable USD graph logic is outside the supported asset profiles')
        for name in ('node:type','omni:graph:node:type'):
            value=prim.GetAttribute(name).Get() if prim.HasAttribute(name) else None
            if isinstance(value,str) and any(token in value.lower() for token in ('scriptnode','pythonnode','python_script')):
                raise PreparationError('physics_profile_unsupported','upstream Python graph nodes cannot be prepared as passive assets')


def inspect_stage(stage, root=None):
    from pxr import Usd,UsdGeom,UsdPhysics,UsdShade
    root=root or stage.GetDefaultPrim()
    if not root:
        raise PreparationError('verification_failed','USD defaultPrim is required')
    reject_executable_graphs(stage)
    units=UsdGeom.GetStageMetersPerUnit(stage)
    if not math.isfinite(units) or units<=0:
        raise PreparationError('verification_failed','invalid USD metersPerUnit')
    cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render,UsdGeom.Tokens.proxy])
    box=cache.ComputeWorldBound(root).ComputeAlignedRange()
    low=list(box.GetMin());high=list(box.GetMax());dims=list(box.GetSize())
    if not all(math.isfinite(v) for v in low+high+dims) or any(v<=0 for v in dims):
        raise PreparationError('verification_failed','empty/nonfinite/degenerate geometry bounds')
    facts={'default_prim':str(root.GetPath()),'meters_per_unit':units,'up_axis':str(UsdGeom.GetStageUpAxis(stage)),
           'bounds':{'min':low,'max':high,'dimensions':dims},'meshes':[],'rigid_bodies':[],'colliders':[],'joints':[],
           'motion_attributes':[],'materials':[],'articulations':[]}
    for prim in Usd.PrimRange(root):
        path=str(prim.GetPath())
        if prim.IsA(UsdGeom.Mesh):
            mesh=UsdGeom.Mesh(prim);points=mesh.GetPointsAttr().Get()
            if not points or not all(math.isfinite(v) for pt in points for v in pt):
                raise PreparationError('verification_failed',f'invalid mesh points: {path}')
            matrix=UsdGeom.XformCache().GetLocalToWorldTransform(prim)
            if not all(math.isfinite(matrix[i][j]) for i in range(4) for j in range(4)):
                raise PreparationError('verification_failed',f'nonfinite mesh transform: {path}')
            facts['meshes'].append({'path':path,'points':len(points),'material':str(UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0].GetPath())})
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):facts['rigid_bodies'].append(path)
        if prim.HasAPI(UsdPhysics.CollisionAPI):facts['colliders'].append(path)
        if prim.IsA(UsdPhysics.Joint):facts['joints'].append(path)
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):facts['articulations'].append(path)
        if prim.IsA(UsdShade.Material):facts['materials'].append(path)
        for attr in prim.GetAttributes():
            if attr.GetNumTimeSamples() and (attr.GetName().startswith('xformOp:') or attr.GetName() in {'points','velocities','angularVelocities'}):
                facts['motion_attributes'].append(str(attr.GetPath()))
    if not facts['meshes']:
        raise PreparationError('verification_failed','no mesh geometry')
    return facts


def world_triangles(stage, root=None, *, max_triangles=200000, collision_only=False):
    from pxr import Usd,UsdGeom,UsdPhysics
    import numpy as np
    triangles=[];root=root or stage.GetDefaultPrim();cache=UsdGeom.XformCache()
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):continue
        if collision_only and not prim.HasAPI(UsdPhysics.CollisionAPI):continue
        mesh=UsdGeom.Mesh(prim);points=mesh.GetPointsAttr().Get();counts=mesh.GetFaceVertexCountsAttr().Get();indices=mesh.GetFaceVertexIndicesAttr().Get()
        if not points or not counts or not indices:continue
        if sum(counts)!=len(indices):raise PreparationError('verification_failed','mesh index count mismatch')
        matrix=cache.GetLocalToWorldTransform(prim);vertices=[list(matrix.Transform(p)) for p in points];offset=0
        for count in counts:
            face=indices[offset:offset+count];offset+=count
            if count<3 or any(i<0 or i>=len(vertices) for i in face):
                raise PreparationError('verification_failed','invalid mesh face indices')
            for i in range(1,count-1):
                triangles.append([vertices[face[0]],vertices[face[i]],vertices[face[i+1]]])
                if len(triangles)>max_triangles:
                    raise PreparationError('physics_profile_unsupported','surface measurement triangle budget exceeded')
    if not triangles:raise PreparationError('verification_failed','empty mesh surface')
    array=np.asarray(triangles,dtype=float)
    cross=np.cross(array[:,1]-array[:,0],array[:,2]-array[:,0]);valid=np.linalg.norm(cross,axis=1)>1e-14
    if not valid.any():raise PreparationError('verification_failed','all surface triangles are degenerate')
    return array[valid]


def _samples(triangles, count=384):
    import numpy as np
    # Deterministic area-weighted triangle samples, plus all extrema; bounded, not a proof.
    areas=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)
    rng=np.random.default_rng(0);choice=rng.choice(len(triangles),size=count,p=areas/areas.sum())
    uv=rng.random((count,2));uv[uv.sum(axis=1)>1]=1-uv[uv.sum(axis=1)>1]
    selected=triangles[choice];samples=selected[:,0]+uv[:,0,None]*(selected[:,1]-selected[:,0])+uv[:,1,None]*(selected[:,2]-selected[:,0])
    points=triangles.reshape(-1,3);extra=[]
    for axis in range(3):extra.extend([points[points[:,axis].argmin()],points[points[:,axis].argmax()]])
    return np.vstack([samples,extra])


def _surface_distances(points, triangles):
    import numpy as np
    a,b,c=triangles[:,0],triangles[:,1],triangles[:,2];ab=b-a;ac=c-a
    normals=np.cross(ab,ac);norm2=(normals*normals).sum(axis=1)
    result=[]
    for point in points:
        ap=point-a;plane=(ap*normals).sum(axis=1)/norm2;projection=point-plane[:,None]*normals
        v=projection-a;d00=(ab*ab).sum(axis=1);d01=(ab*ac).sum(axis=1);d11=(ac*ac).sum(axis=1);den=d00*d11-d01*d01
        u=(d11*(v*ab).sum(axis=1)-d01*(v*ac).sum(axis=1))/den
        w=(d00*(v*ac).sum(axis=1)-d01*(v*ab).sum(axis=1))/den
        inside=(u>=0)&(w>=0)&(u+w<=1)
        distances=np.where(inside,plane*plane*norm2,np.inf)
        for start,end in [(a,b),(b,c),(c,a)]:
            edge=end-start;t=np.clip(((point-start)*edge).sum(axis=1)/(edge*edge).sum(axis=1),0,1)
            edge_distance=((point-start-t[:,None]*edge)**2).sum(axis=1)
            distances=np.minimum(distances,edge_distance)
        result.append(float(np.sqrt(distances.min())))
    return result


def hull_fidelity(stage, tolerance_m, root=None):
    import numpy as np
    try:
        from scipy.spatial import ConvexHull
    except ImportError as error:
        raise PreparationError('dependency_missing','SDK scipy required for measured convex hull fidelity') from error
    source=world_triangles(stage,root);vertices=np.unique(source.reshape(-1,3),axis=0)
    if len(vertices)>100000:raise PreparationError('physics_profile_unsupported','hull vertex measurement budget exceeded')
    try:hull=ConvexHull(vertices)
    except Exception as error:raise PreparationError('physics_profile_unsupported','mesh cannot form a solid convex hull') from error
    hull_triangles=vertices[hull.simplices]
    forward=_surface_distances(_samples(source),hull_triangles);backward=_surface_distances(_samples(hull_triangles),source)
    distances=forward+backward;longest=float(np.ptp(vertices,axis=0).max())
    p95=float(np.percentile(distances,95));maximum=max(distances)
    p95_limit=min(float(tolerance_m),.002,longest*.02);maximum_limit=min(float(tolerance_m)*2.5,.005,longest*.05)
    report={'method':'deterministic_area_weighted_bidirectional_point_triangle_surface_distance','seed':0,
            'samples_per_direction':len(forward),'source_triangles':len(source),'hull_triangles':len(hull_triangles),
            'source_vertices':len(vertices),'p95_m':p95,'max_m':maximum,'bottom_height_error_m':0.0,
            'p95_limit_m':p95_limit,'max_limit_m':maximum_limit,
            'coverage_limit':'bounded surface sampling is not a geometric proof; no runtime collision cooking measured',
            'accepted':p95<=p95_limit and maximum<=maximum_limit}
    if not report['accepted']:
        error=PreparationError('physics_profile_unsupported',f'convex hull fills unsupported shape: p95={p95:g}m max={maximum:g}m; choose another model/recipe')
        error.measurement=report;raise error
    return report


def validate_support(stage, surfaces, tolerance_m, root=None, *, collision_only=False):
    """Probe each declared usable rectangle against actual horizontal triangles."""
    import numpy as np
    triangles=world_triangles(stage,root,collision_only=collision_only);a=triangles[:,0];ab=triangles[:,1]-a;ac=triangles[:,2]-a
    normal=np.cross(ab,ac);normal/=np.linalg.norm(normal,axis=1)[:,None]
    horizontal=np.abs(normal[:,2])>.9999
    measured=[]
    for name,region in surfaces.items():
        for x in np.linspace(region['min_xy'][0],region['max_xy'][0],5):
            for y in np.linspace(region['min_xy'][1],region['max_xy'][1],5):
                if any(r['min_xy'][0]<=x<=r['max_xy'][0] and r['min_xy'][1]<=y<=r['max_xy'][1] for r in region.get('exclude',[])):continue
                ap=np.asarray([x,y,region['z_m']])-a;den=ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0]
                with np.errstate(divide='ignore',invalid='ignore'):
                    u=(ap[:,0]*ac[:,1]-ap[:,1]*ac[:,0])/den;v=(ab[:,0]*ap[:,1]-ab[:,1]*ap[:,0])/den
                candidates=horizontal&(u>=-1e-6)&(v>=-1e-6)&(u+v<=1+1e-6)
                heights=a[:,2]+u*ab[:,2]+v*ac[:,2]
                error=float(np.min(np.abs(heights[candidates]-region['z_m']))) if candidates.any() else float('inf')
                if error>tolerance_m:
                    raise PreparationError('physics_profile_unsupported',f'support {name} lacks measured horizontal mesh coverage at ({x:g},{y:g})')
                measured.append(error)
    if not measured:raise PreparationError('physics_profile_unsupported','support excludes every measurement point')
    return {'method':'5x5 horizontal triangle coverage probes per named region','max_height_error_m':max(measured),'probes':len(measured),
            'coverage_limit':'sampled coverage does not certify continuous surface or dynamic stability'}
