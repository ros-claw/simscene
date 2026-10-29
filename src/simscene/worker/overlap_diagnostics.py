"""Bounded PhysX scene-query observations, not a signed penetration audit."""
class OverlapDiagnostics:
    def __init__(self, shapes, query, encode, max_pairs=100000, robot_prefixes=None):
        self.shapes=list(shapes);self.history=list(shapes);self.query=query;self.encode=encode;self.max_pairs=max_pairs
        self.robot_prefixes=robot_prefixes
        self.counts={};self.steps=0;self.last_step=None;self.gaps=0
        self.shape_samples={shape['path']:0 for shape in shapes}
        self.missing_self={};self.errors=[];self.error_count=0;self.truncated=False
        if not shapes:raise ValueError('no robot collision shapes found for overlap diagnostics')
        if len(shapes)>512:raise ValueError('overlap diagnostics supports at most 512 robot shapes')

    def add(self, shape):
        if len(self.shapes)>=512:raise ValueError('overlap diagnostics supports at most 512 active shapes')
        if any(x['path']==shape['path'] for x in self.shapes):raise ValueError('duplicate diagnostic shape')
        if shape['path'] in self.shape_samples:raise ValueError('diagnostic shape paths cannot be reused')
        self.shape_samples[shape['path']]=0
        self.shapes.append(shape);self.history.append(shape)

    def remove(self, path):
        self.shapes=[x for x in self.shapes if x['path']!=path]

    def sample(self, step):
        if self.last_step is not None and step != self.last_step+1:self.gaps+=1
        self.last_step=step;self.steps+=1
        for shape in self.shapes:
            path,body=shape['path'],shape['body'];own=[False]
            self.shape_samples[path]+=1
            def report(hit):
                other_body=str(hit.rigid_body);other_shape=str(hit.collision)
                if other_body==body:
                    if other_shape==path:own[0]=True
                    return True
                if self.robot_prefixes is not None and not any(path==p or path.startswith(p+'/') or other_shape==p or other_shape.startswith(p+'/') for p in self.robot_prefixes):
                    return True
                pair='|'.join(sorted((path,other_shape)))
                if pair not in self.counts and len(self.counts)>=self.max_pairs:
                    self.truncated=True
                else:
                    record=self.counts.setdefault(pair,{'count':0,'first_physics_step':step,'last_physics_step':step})
                    record['count']+=1;record['last_physics_step']=step
                return True
            try:
                code=self.encode(path);self.query.overlap_shape(code[0],code[1],report,False)
            except Exception as error:
                self.error_count+=1
                if len(self.errors)<20:self.errors.append({'shape':path,'step':step,'error':str(error)})
            if not own[0]:self.missing_self[path]=self.missing_self.get(path,0)+1

    def summary(self):
        return {'shapes':self.history,'shape_samples':self.shape_samples,'active_shape_count':len(self.shapes),'sampled_steps':self.steps,'last_physics_step':self.last_step,
                'step_gaps':self.gaps,'missing_self_hits':self.missing_self,'error_count':self.error_count,'errors':self.errors,'truncated':self.truncated,
                'scope':'Discrete PhysX scene queries; meshes use convex-hull query approximations. Counts are query hits, not unique time steps. Same-body overlaps are omitted; other expected mechanical and grasp overlaps are included. This does not measure penetration depth or certify continuous collision safety.'}
