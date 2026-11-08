"""Measured bounds and explicit horizontal support regions for reusable layouts.

An imported model's outer bounding box is never inferred to be a usable surface.
Bounds are geometric and conservative; they do not prove dynamic stability.
"""
import copy
import itertools
import math
import tempfile
from pathlib import Path
from .scene import SceneError
from .capture import finite

def vector(value,n=3):
    return isinstance(value,list) and len(value)==n and all(finite(v) for v in value)

def validate_surfaces(surfaces):
    if not isinstance(surfaces,dict) or not surfaces:raise ValueError('support_surfaces must name explicit local metre regions')
    for name,region in surfaces.items():
        if not isinstance(name,str) or not name or not isinstance(region,dict) or set(region)-{'min_xy','max_xy','z_m','exclude'}:raise ValueError('invalid support surface')
        if not vector(region.get('min_xy'),2) or not vector(region.get('max_xy'),2) or not all(a<b for a,b in zip(region['min_xy'],region['max_xy'])) or not finite(region.get('z_m')):raise ValueError('support requires min_xy, max_xy and z_m in normalized local metres')
        exclusions=region.get('exclude',[])
        if not isinstance(exclusions,list):raise ValueError('surface exclude must be rectangles')
        for rect in exclusions:
            if not isinstance(rect,dict) or set(rect)!={'min_xy','max_xy'} or not vector(rect['min_xy'],2) or not vector(rect['max_xy'],2) or not all(a<b for a,b in zip(rect['min_xy'],rect['max_xy'])):raise ValueError('invalid excluded support rectangle')

def rotate(q,v):
    w,x,y,z=q
    return [(1-2*y*y-2*z*z)*v[0]+(2*x*y-2*w*z)*v[1]+(2*x*z+2*w*y)*v[2],
            (2*x*y+2*w*z)*v[0]+(1-2*x*x-2*z*z)*v[1]+(2*y*z-2*w*x)*v[2],
            (2*x*z-2*w*y)*v[0]+(2*y*z+2*w*x)*v[1]+(1-2*x*x-2*y*y)*v[2]]

def bounds(obj,scene=None,name=None):
    if obj.get('rigid_attachment'):
        if scene is None:raise SceneError('attached asset bounds require the parent scene')
        from .attachments import world_object
        obj=world_object(scene,obj)
    kind=obj.get('kind');position=obj.get('position',[0,0,0]);q=obj.get('orientation_wxyz',[1,0,0,0])
    if kind in ('box','sphere'):
        half=[s/2 for s in obj.get('size',[1,1,1])]
        points=[[position[i]+r[i] for i in range(3)] for r in (rotate(q,v) for v in itertools.product(*[(-s,s) for s in half]))]
        return {'min':[min(p[i] for p in points) for i in range(3)],'max':[max(p[i] for p in points) for i in range(3)]}
    if kind not in ('asset','cylinder','capsule','compound'):raise SceneError('bounds require geometry or imported asset')
    # Reuse exactly the export's unit/up-axis conversion, selected variants and
    # authored transforms rather than guessing from filenames or source bbox.
    from .usd_export import export_scene
    from pxr import Usd,UsdGeom
    measured_name='measured';objects={measured_name:copy.deepcopy(obj)}
    if scene is not None and name is not None and obj.get('kind')=='compound':
        children={n:copy.deepcopy(o) for n,o in scene['objects'].items() if o.get('rigid_attachment',{}).get('body')==name}
        if children:measured_name=name;objects={name:copy.deepcopy(obj),**children}
    # This temporary stage contains only the rendered subject and its visuals.
    # Pair filters refer to IDs in the full physical scene and do not affect
    # render bounds. Drop them on these copies rather than importing unrelated
    # colliders or changing the source scene's collision relationships.
    for measured in objects.values():measured.pop('collision_exclusions',None)
    with tempfile.TemporaryDirectory(prefix='simscene-measure-') as directory:
        measured_scene={'revision':0,'objects':objects}
        # Prepared bodies are measured through the same exporter as playback.
        # Native articulations require this observation declaration even though
        # this temporary stage never starts a simulation or executes commands.
        if any('asset_binding' in value for value in objects.values()):
            measured_scene['observation']={'sample_interval_steps':1,'strict_start':True}
        export_scene(measured_scene,Path(directory)/'measure.usda')
        stage=Usd.Stage.Open(str(Path(directory)/'measure.usda'))
        box=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render]).ComputeWorldBound(stage.GetPrimAtPath('/World/'+measured_name.replace('-','_'))).ComputeAlignedRange()
        if box.IsEmpty():raise SceneError('imported asset has no measurable rendered bounds')
        return {'min':list(box.GetMin()),'max':list(box.GetMax())}

def measure(scene,ids,include_overlap_candidates=False):
    if not isinstance(ids,list) or not ids or any(i not in scene['objects'] for i in ids):raise SceneError('measure requires existing object IDs')
    if type(include_overlap_candidates) is not bool:raise SceneError('include_overlap_candidates must be boolean')
    result={}
    for name in ids:
        obj=scene['objects'][name];box=bounds(obj,scene,name)
        result[name]={'world_bounds_m':box,'dimensions_m':[b-a for a,b in zip(box['min'],box['max'])],
                      'bottom_center_m':[(box['min'][0]+box['max'][0])/2,(box['min'][1]+box['max'][1])/2,box['min'][2]],
                      'support_surfaces':copy.deepcopy(obj.get('support_surfaces',{})),
                      'orientation_wxyz':obj.get('orientation_wxyz',[1,0,0,0]),'source_asset_path':obj.get('asset_path')}
    report={'objects':result,'scope':'render bounds; explicit support regions; no dynamic stability certification'}
    if include_overlap_candidates:
        candidates=[]
        for i,first in enumerate(ids):
            a=scene['objects'][first]
            if a.get('rigid_attachment'):continue
            for second in ids[i+1:]:
                b=scene['objects'][second]
                if b.get('rigid_attachment'):continue
                ab=result[first]['world_bounds_m'];bb=result[second]['world_bounds_m']
                extent=[min(ab['max'][k],bb['max'][k])-max(ab['min'][k],bb['min'][k]) for k in range(3)]
                if min(extent)>1e-6:candidates.append({'ids':[first,second],'overlap_extent_m':extent,'intersection_volume_m3':math.prod(extent)})
        report['potential_render_bounds_overlaps']=candidates
        report['overlap_scope']='Authored rendered AABB intersections among selected objects, excluding attached visual children. Includes empty regions of compounds and deliberate contacts; inspect actual shape clearance and physical contacts. This is not a penetration or collision-free certificate.'
    return report

def surface(obj,name=None):
    if obj.get('rigid_attachment'):raise SceneError('attached visuals cannot be placement supports; use the physical parent')
    regions=obj.get('support_surfaces',{})
    if name is not None:
        if name not in regions:raise SceneError('unknown support surface')
        region=regions[name]
    elif obj.get('kind')=='box':
        size=obj.get('size',[1,1,1]);region={'min_xy':[-size[0]/2,-size[1]/2],'max_xy':[size[0]/2,size[1]/2],'z_m':size[2]/2}
    else:raise SceneError('imported support requires an explicit support_surface; outer bbox is not a usable surface')
    q=obj.get('orientation_wxyz',[1,0,0,0]);normal=rotate(q,[0,0,1])
    if abs(normal[0])+abs(normal[1])+abs(normal[2]-1)>1e-6:raise SceneError('support region must be horizontal; tilted placement needs a separate stability model')
    return region,q,obj.get('position',[0,0,0])

def intersects(a,b,margin=0):
    return all(a['max'][i]+margin>b['min'][i]+1e-7 and b['max'][i]+margin>a['min'][i]+1e-7 for i in range(3))

def check_clearance(scene,name,box,op):
    avoid=op.get('avoid_ids',[]);margin=op.get('clearance_m',0)
    if not isinstance(avoid,list) or not finite(margin) or margin<0:raise SceneError('invalid clearance configuration')
    for obstacle in avoid:
        if obstacle==name or obstacle not in scene['objects']:raise SceneError('avoid_ids require distinct existing objects')
        if intersects(box,bounds(scene['objects'][obstacle],scene,obstacle),margin):raise SceneError('placement violates clearance: '+obstacle)
    for region in op.get('keepout_bounds',[]):
        if not isinstance(region,dict) or not vector(region.get('min')) or not vector(region.get('max')) or any(a>=b for a,b in zip(region['min'],region['max'])):raise SceneError('invalid keepout bounds')
        if intersects(box,region,margin):raise SceneError('placement intrudes into a reserved activity region')

def place_on(scene,op):
    objects=scene['objects'];name=op.get('id');support_id=op.get('support')
    if name==support_id or name not in objects or support_id not in objects:raise SceneError('place_on requires two distinct existing objects')
    if any(objects[n].get('rigid_attachment') for n in (name,support_id)):raise SceneError('place attached visuals by explicit local pose; move their physical parent with place_on')
    item=objects[name];region,q,p=surface(objects[support_id],op.get('support_surface'))
    offset=op.get('offset_xy',[0,0]);gap=op.get('gap_m',0)
    if not vector(offset,2) or not finite(gap) or not 0<=gap<=1:raise SceneError('invalid placement offset or gap')
    if 'orientation_wxyz' in op:
        orientation=op['orientation_wxyz']
        if not vector(orientation,4) or abs(sum(v*v for v in orientation)-1)>1e-4:raise SceneError('invalid placement orientation')
        item['orientation_wxyz']=orientation
    box=bounds(item,scene,name);anchor=[(box['min'][0]+box['max'][0])/2,(box['min'][1]+box['max'][1])/2,box['min'][2]]
    local=[(region['min_xy'][i]+region['max_xy'][i])/2+offset[i] for i in range(2)]+[region['z_m']+gap]
    turned=rotate(q,local);target=[p[i]+turned[i] for i in range(3)];delta=[target[i]-anchor[i] for i in range(3)]
    candidate={k:[v[i]+delta[i] for i in range(3)] for k,v in box.items()}
    inverse=[q[0],-q[1],-q[2],-q[3]]
    corners=[rotate(inverse,[v[i]-p[i] for i in range(3)]) for v in itertools.product(*[(candidate['min'][i],candidate['max'][i]) for i in range(3)])]
    low=[min(v[i] for v in corners) for i in range(2)];high=[max(v[i] for v in corners) for i in range(2)]
    if any(low[i]<region['min_xy'][i]-1e-6 or high[i]>region['max_xy'][i]+1e-6 for i in range(2)):raise SceneError('object extends beyond support surface')
    for rect in region.get('exclude',[]):
        if all(high[i]>rect['min_xy'][i] and rect['max_xy'][i]>low[i] for i in range(2)):raise SceneError('object overlaps an excluded support region')
    check_clearance(scene,name,candidate,op)
    item['position']=[item.get('position',[0,0,0])[i]+delta[i] for i in range(3)]

def arrange_line(scene,op):
    ids=op.get('ids');origin=op.get('origin');axis=op.get('axis','x');spacing=op.get('spacing')
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or any(i not in scene['objects'] for i in ids) or not vector(origin) or axis not in ('x','y','z') or not finite(spacing) or spacing<=0:raise SceneError('invalid arrange_line configuration')
    if any(scene['objects'][n].get('rigid_attachment') for n in ids):raise SceneError('arrange physical parents; attached visuals use explicit local poses')
    dim=('x','y','z').index(axis);previous=None
    for index,name in enumerate(ids):
        obj=scene['objects'][name];box=bounds(obj,scene,name);center=[(a+b)/2 for a,b in zip(box['min'],box['max'])];target=list(origin);target[dim]+=index*spacing
        delta=[target[i]-center[i] for i in range(3)];candidate={k:[v[i]+delta[i] for i in range(3)] for k,v in box.items()}
        if previous and candidate['min'][dim]<previous['max'][dim]-1e-7:raise SceneError('line spacing would overlap objects')
        check_clearance(scene,name,candidate,op);obj['position']=[obj.get('position',[0,0,0])[i]+delta[i] for i in range(3)];previous=candidate

def apply_layout(scene,op):
    ids=op.get('ids')
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or any(i not in scene['objects'] for i in ids):raise SceneError('layout requires distinct existing IDs')
    if any(scene['objects'][n].get('rigid_attachment') for n in ids):raise SceneError('arrange physical parents; attached visuals use explicit local poses')
    if op['op']=='align':
        axis=op.get('axis','x');edge=op.get('edge','center');value=op.get('value_m')
        if axis not in ('x','y','z') or edge not in ('min','max','center') or not finite(value):raise SceneError('invalid alignment')
        dim=('x','y','z').index(axis)
        for name in ids:
            obj=scene['objects'][name];box=bounds(obj,scene,name);anchor=(box['min'][dim]+box['max'][dim])/2 if edge=='center' else box[edge][dim]
            obj['position']=list(obj.get('position',[0,0,0]));obj['position'][dim]+=value-anchor
        return
    columns=op.get('columns');gap=op.get('gap_m',.02)
    if type(columns) is not int or not 1<=columns<=len(ids) or not finite(gap) or gap<0:raise SceneError('grid needs columns and nonnegative gap_m')
    support_id=op.get('support')
    if support_id not in scene['objects']:raise SceneError('grid requires a support')
    region,q,p=surface(scene['objects'][support_id],op.get('support_surface'));inverse=[q[0],-q[1],-q[2],-q[3]];dimensions=[]
    for name in ids:
        box=bounds(scene['objects'][name],scene,name);points=[rotate(inverse,list(v)) for v in itertools.product(*[(box['min'][i],box['max'][i]) for i in range(3)])]
        dimensions.append([max(v[i] for v in points)-min(v[i] for v in points) for i in range(2)])
    rows=math.ceil(len(ids)/columns);widths=[max(dimensions[i][0] for i in range(c,len(ids),columns)) for c in range(columns)];heights=[max(v[1] for v in dimensions[r*columns:(r+1)*columns]) for r in range(rows)]
    total=[sum(widths)+(columns-1)*gap,sum(heights)+(rows-1)*gap]
    if any(total[i]>region['max_xy'][i]-region['min_xy'][i]+1e-6 for i in range(2)):raise SceneError('grid exceeds support surface')
    offset=op.get('offset_xy',[0,0])
    if not vector(offset,2):raise SceneError('invalid grid offset_xy')
    for index,name in enumerate(ids):
        row,col=divmod(index,columns)
        xy=[-total[0]/2+sum(widths[:col])+col*gap+widths[col]/2+offset[0],-total[1]/2+sum(heights[:row])+row*gap+heights[row]/2+offset[1]]
        place_on(scene,{**op,'id':name,'offset_xy':xy,'gap_m':op.get('vertical_gap_m',0)})
