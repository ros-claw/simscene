import copy,math,tempfile,unittest
from pathlib import Path
from simscene.scene import validate,SceneStore
from simscene.usd_export import export_scene

class PassiveMechanismTests(unittest.TestCase):
 def scene(self):
  return {'revision':0,'objects':{'slider':{'kind':'compound','dynamic':True,'mass_kg':.2,'parts':[{'kind':'box','size':[.4,.2,.02]}]},'slide':{'kind':'joint','joint':{'type':'prismatic','body1':'slider','axis':'X','lower_limit':0,'upper_limit':.3}}}}
 def test_export_metric_frames_and_passive_coordinates(self):
  from pxr import Usd,UsdPhysics,UsdGeom,Gf
  from simscene.worker.joint_observation import sample
  s=self.scene();s['objects']['slider']['physics']={'linear_damping':.2,'static_friction':.3,'contact_offset_m':.001,'enable_ccd':True}
  s['objects']['link']={'kind':'capsule','size':[.01,.01,.04],'dynamic':True}
  s['objects']['hinge']={'kind':'joint','joint':{'type':'revolute','body1':'link','axis':'Z'}}
  self.assertEqual(validate(s),[])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'scene.usda';export_scene(s,path);stage=Usd.Stage.Open(str(path))
   self.assertAlmostEqual(UsdPhysics.PrismaticJoint(stage.GetPrimAtPath('/World/slide')).GetUpperLimitAttr().Get(),.3)
   self.assertAlmostEqual(stage.GetPrimAtPath('/World/slider').GetAttribute('physxRigidBody:linearDamping').Get(),.2)
   self.assertFalse(any('DriveAPI' in x for p in stage.Traverse() for x in p.GetAppliedSchemas()))
   UsdGeom.Xformable(stage.GetPrimAtPath('/World/slider')).GetOrderedXformOps()[0].Set(Gf.Vec3d(.17,0,0))
   orient=UsdGeom.Xformable(stage.GetPrimAtPath('/World/link')).GetOrderedXformOps()[1]
   orient.Set(Gf.Quatf(math.cos(math.radians(85)),Gf.Vec3f(0,0,math.sin(math.radians(85)))))
   first=sample(stage,s['objects']);self.assertAlmostEqual(first['slide']['position_m'],.17);self.assertAlmostEqual(first['hinge']['angle_degrees'],170,places=4)
   orient.Set(Gf.Quatf(math.cos(math.radians(95)),Gf.Vec3f(0,0,math.sin(math.radians(95)))))
   self.assertAlmostEqual(sample(stage,s['objects'],first)['hinge']['angle_degrees'],190,places=4)
 def test_reject_injecting_drives_missing_bodies_bad_shapes_or_scaled_frames(self):
  mutations=[lambda s:s['objects']['slide']['joint'].update(drive={'target':1}),lambda s:s['objects']['slide']['joint'].update(body1='missing'),lambda s:s['objects']['slider'].update(spawn_step=60),lambda s:s['objects']['slider'].update(kind='box',size=[.4,.2,.02]),lambda s:s['objects']['slider']['parts'][0].update(kind='capsule',size=[.1,.2,.05]),lambda s:s['objects']['slide']['joint'].update(lower_limit=1,upper_limit=0)]
  for mutate in mutations:
   with self.subTest(mutate=mutate):
    scene=self.scene();mutate(scene);self.assertTrue(validate(scene))
 def test_compound_bounds_and_observation_transaction(self):
  from simscene.placement import bounds
  scene=self.scene();box=bounds(scene['objects']['slider']);self.assertAlmostEqual(box['max'][0],.2)
  with tempfile.TemporaryDirectory() as d:
   store=SceneStore(d);store.open('test');store.apply('test',0,'observe',[{'op':'set_observation','observation':{'sample_interval_steps':1}}]);self.assertEqual(store.get('test')['observation']['sample_interval_steps'],1)
   with self.assertRaises(ValueError):store.apply('test',1,'bad',[{'op':'set_observation','observation':{'sample_interval_steps':0}}])
 def test_rope_links_have_real_mass_coincident_frames_and_no_drive(self):
  from pxr import Usd
  from simscene.mechanisms import segmented_rope
  from simscene.worker.joint_observation import sample
  plan=segmented_rope('cord',[[0,0,1],[.1,0,.9],[.2,0,1]])
  scene={'revision':0,'objects':{op['id']:op['object'] for op in plan['operations']}}
  self.assertEqual(validate(scene),[])
  self.assertGreater(len(plan['rope']['link_ids']),4)
  self.assertAlmostEqual(sum(o['mass_kg'] for o in scene['objects'].values() if o.get('dynamic')),plan['rope']['mass_kg'])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'rope.usda';export_scene(scene,path);stage=Usd.Stage.Open(str(path));observed=sample(stage,scene['objects'])
   self.assertTrue(all(j['anchor_error_m']<1e-6 and not j['drive_present'] for j in observed.values()))

if __name__=='__main__':unittest.main()
