"""Plan ordinary operations for a colliding articulated rope, without actuating."""
import math
from .passive import vector,finite

def segmented_rope(prefix,points,radius_m=.005,max_segment_m=.025,linear_density_kg_m=.06,attachments=None,physics=None,self_collision=True):
    from .scene import _id,SceneError
    _id(prefix)
    if type(self_collision) is not bool:raise SceneError('self_collision must be boolean')
    if not isinstance(points,list) or not 2<=len(points)<=200 or not all(vector(p) for p in points):raise SceneError('rope path needs 2..200 finite metric points')
    if not all(finite(v) and v>0 for v in (radius_m,max_segment_m,linear_density_kg_m)) or max_segment_m<4*radius_m:raise SceneError('rope segment length must be at least four radii; density must be positive')
    nodes=[list(points[0])]
    for a,b in zip(points,points[1:]):
        length=math.dist(a,b)
        if length<1e-6:raise SceneError('rope path has coincident points')
        count=math.ceil(length/max_segment_m)
        nodes.extend([[a[j]+(b[j]-a[j])*i/count for j in range(3)] for i in range(1,count+1)])
    if len(nodes)>513:raise SceneError('rope exceeds 512 link budget')
    operations=[];ids=[];joints=[];lengths=[]
    settings={'static_friction':.6,'dynamic_friction':.5,'restitution':0,'linear_damping':.1,'angular_damping':.1,'solver_position_iterations':64,'solver_velocity_iterations':8,'contact_offset_m':radius_m*.3,'rest_offset_m':0,**(physics or {})}
    for i,(a,b) in enumerate(zip(nodes,nodes[1:])):
        name=prefix+'_link_'+str(i).zfill(3);_id(name);ids.append(name);length=math.dist(a,b);lengths.append(length);direction=[(b[j]-a[j])/length for j in range(3)]
        if direction[2]<-.999999:rotation=[0,1,0,0]
        else:
            rotation=[1+direction[2],-direction[1],direction[0],0];norm=math.sqrt(sum(v*v for v in rotation));rotation=[v/norm for v in rotation]
        operations.append({'op':'add','id':name,'object':{'kind':'capsule','size':[2*radius_m,2*radius_m,length+2*radius_m],'position':[(a[j]+b[j])/2 for j in range(3)],'orientation_wxyz':rotation,'dynamic':True,'collision':True,'mass_kg':linear_density_kg_m*length,'color':[.8,.035,.025],'physics':settings}})
        if not self_collision:operations[-1]['object']['collision_exclusions']=list(ids[:-1])
        if i:
            joint=prefix+'_joint_'+str(i).zfill(3);joints.append(joint);operations.append({'op':'add','id':joint,'object':{'kind':'joint','joint':{'type':'spherical','body0':ids[i-1],'body1':name,'local_pos0':[0,0,lengths[i-1]/2],'local_pos1':[0,0,-length/2]}}})
    attached={}
    for side,index,sign in [('start',0,-1),('end',len(ids)-1,1)]:
        if side not in (attachments or {}):continue
        item=attachments[side]
        if not isinstance(item,dict) or set(item)!={'body','local_position_m'} or not isinstance(item['body'],str) or not vector(item['local_position_m']):raise SceneError('rope attachment requires body ID and metric local_position_m')
        joint=prefix+'_'+side+'_attachment';attached[side]=joint
        operations.append({'op':'add','id':joint,'object':{'kind':'joint','joint':{'type':'spherical','body0':ids[index],'body1':item['body'],'local_pos0':[0,0,sign*lengths[index]/2],'local_pos1':item['local_position_m']}}})
    return {'operations':operations,'rope':{'model':'colliding_capsules_with_passive_spherical_joints','self_collision_enabled':self_collision,'link_ids':ids,'joint_ids':joints,'attachment_ids':attached,'initial_nodes_world_m':nodes,'anchor_path_length_m':sum(lengths),'radius_m':radius_m,'mass_kg':linear_density_kg_m*sum(lengths),'scope':'Physical links are generated; pulley routing, tension transfer and stability require actual simulation and paired interventions.'}}
