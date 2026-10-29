import tempfile
import unittest
from pathlib import Path
from pxr import Usd,UsdGeom,UsdPhysics
from simscene.verification.overlap_audit import evaluate


class OverlapAuditTest(unittest.TestCase):
    def test_coverage_and_forbidden_overlap_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stage.usda';stage=Usd.Stage.CreateNew(str(path))
            body=UsdGeom.Xform.Define(stage,'/World/arm/Asset/finger').GetPrim();UsdPhysics.RigidBodyAPI.Apply(body)
            shape=UsdGeom.Cube.Define(stage,'/World/arm/Asset/finger/shape').GetPrim();UsdPhysics.CollisionAPI.Apply(shape)
            table=UsdGeom.Cube.Define(stage,'/World/table').GetPrim();UsdPhysics.CollisionAPI.Apply(table);stage.GetRootLayer().Save()
            shape_path=str(shape.GetPath());body_path=str(body.GetPath())
            spec={'objects':{'arm':{'pose_follower':{'self_collision_exclusions':[],'diagnose_overlaps':True}},'item':{'dynamic':True,'spawn_step':1}}}
            case={'objects':[{'robot_id':'arm','part_id':'item','part_path':'/World/item','tracking_phase':1,'release_phase':2}],
                  'collision_policy':{'mechanical_pairs':{'arm':[]},'allowed_mechanical_contacts':{'arm':[]},'grasp_bodies':{'arm':['finger']}}}
            shapes=[{'path':shape_path,'body':body_path},{'path':'/World/table','body':'/World/table'},{'path':'/World/item','body':'/World/item'}]
            run={'actual_physics_steps':3,'spawn_events':[{'id':'item','physics_step':1}],'archived_objects':{},
                 'overlap_diagnostics':{'shapes':shapes,'shape_samples':{shape_path:4,'/World/table':4,'/World/item':2},'sampled_steps':4,'last_physics_step':3,'step_gaps':0,'error_count':0,'missing_self_hits':{},'truncated':False},
                 'self_collision_settings':{'arm':{'authored':True,'runtime':True,'excluded_body_pairs':[]}},
                 'monitored_robot_ids':['arm'],'contacts_truncated':False,'contact_geometry_incomplete':False,
                 'followers':{'arm':{'transitions':[]}},'overlap_counts':{},'robot_contacts':{}}
            self.assertTrue(evaluate(run,spec,case,path)['passed'])
            run['overlap_counts'][shape_path+'|/World/table']={'first_physics_step':1,'last_physics_step':2,'count':2}
            self.assertFalse(evaluate(run,spec,case,path)['checks']['no_unexpected_overlaps_or_contacts'])
            run['overlap_counts'].clear();run['overlap_diagnostics']['shape_samples']['/World/table']=3
            self.assertFalse(evaluate(run,spec,case,path)['checks']['collision_shapes_covered'])
            run['overlap_diagnostics']['shape_samples']['/World/table']=4
            run['followers']['arm']['transitions']=[{'index':1,'physics_step':1},{'index':4,'physics_step':3}]
            run['overlap_counts'][shape_path+'|/World/item']={'first_physics_step':1,'last_physics_step':3,'count':2}
            self.assertTrue(evaluate(run,spec,case,path)['checks']['no_unexpected_overlaps_or_contacts'])
            run['overlap_counts'][shape_path+'|/World/item']['first_physics_step']=0
            self.assertFalse(evaluate(run,spec,case,path)['checks']['no_unexpected_overlaps_or_contacts'])
            run['overlap_counts'].clear()
            run['robot_contacts'][body_path+'|/World/table|arm:0']={'first_physics_step':1,'last_physics_step':2,'minimum_separation_m':.01}
            self.assertTrue(evaluate(run,spec,case,path)['checks']['no_unexpected_overlaps_or_contacts'])
            run['robot_contacts'][body_path+'|/World/table|arm:0']['minimum_separation_m']=-.001
            self.assertFalse(evaluate(run,spec,case,path)['checks']['no_unexpected_overlaps_or_contacts'])
