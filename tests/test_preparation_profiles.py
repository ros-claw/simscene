import math
import unittest
from simscene.preparation.profiles import PreparationError,validate_parameters,preparation_key,source_identity


def rigid(**updates):
    return dict({'source_physics_policy':'reject_if_physics','mass_kg':.12,'mass_note':'experimental fixture mass',
                 'proxy_tolerance_m':.002},**updates)

class PreparationProfileTests(unittest.TestCase):
    def test_content_reuse_retains_source_attribution_and_ignores_job_location(self):
        acquired={'source_ref':{'source_id':'one','asset_id':'box','revision':'a'*40},
                  'manifest_sha256':'b'*64,'license':'CC-BY-4.0','provenance':{'author':'one'},'root':'/job/one/box.glb'}
        identity=source_identity(acquired,'c'*64)
        self.assertEqual(identity,source_identity(dict(acquired,root='/job/two/box.glb'),'c'*64))
        self.assertNotEqual(identity,source_identity(dict(acquired,license='CC0-1.0'),'c'*64))
        self.assertNotEqual(identity,source_identity(dict(acquired,provenance={'author':'two'}),'c'*64))
        self.assertNotEqual(identity,source_identity(dict(acquired,source_ref={'source_id':'two','asset_id':'box','revision':'a'*40}),'c'*64))

    def test_rigid_explicit_assumptions_and_defaults(self):
        p=validate_parameters('rigid_prop_v1',rigid())
        self.assertEqual(p['collision_method'],'convex_hull');self.assertTrue(p['ccd'])
        self.assertEqual(p['dynamic_friction'],.5)

    def test_finite_and_policy_admission(self):
        for field,value in [('mass_kg',-1),('mass_kg',True),('mass_kg',math.nan),('mass_kg',math.inf),
                            ('proxy_tolerance_m',0),('dynamic_friction',.9),('ccd',1),
                            ('mass_note',' '),('source_physics_policy','preserve_valid'),('collision_method','box_proxy')]:
            with self.subTest(field=field,value=value),self.assertRaises(PreparationError):
                validate_parameters('rigid_prop_v1',rigid(**{field:value}))
        for missing in ['mass_kg','mass_note','proxy_tolerance_m','source_physics_policy']:
            p=rigid();p.pop(missing)
            with self.assertRaises(PreparationError):validate_parameters('rigid_prop_v1',p)

    def test_fit_size_is_explicit_and_uniform(self):
        with self.assertRaises(PreparationError):validate_parameters('rigid_prop_v1',rigid(scale_mode='fit_longest'))
        with self.assertRaises(PreparationError):validate_parameters('rigid_prop_v1',rigid(target_longest_extent_m=.1))
        self.assertEqual(validate_parameters('rigid_prop_v1',rigid(scale_mode='fit_longest',target_longest_extent_m=.1))['target_longest_extent_m'],.1)
        with self.assertRaises(PreparationError):validate_parameters('rigid_prop_v1',rigid(scale=[1,2,1]))

    def test_static_requires_measured_surface_and_explicit_replacement(self):
        p={'source_physics_policy':'replace_visual_only','proxy_tolerance_m':.002,'collision_method':'box_proxy',
           'static_proxy':{'size_m':[1,.6,.04],'position_m':[0,0,.78],'orientation_wxyz':[1,0,0,0]},
           'support_surfaces':{'worktop':{'min_xy':[-.45,-.25],'max_xy':[.45,.25],'z_m':.8,'exclude':[]}}}
        self.assertEqual(validate_parameters('static_fixture_v1',p)['static_proxy']['size_m'],[1,.6,.04])
        p['source_physics_policy']='preserve_valid'
        with self.assertRaises(PreparationError):validate_parameters('static_fixture_v1',p)
        p['source_physics_policy']='replace_visual_only';p['static_proxy']['orientation_wxyz']=[2,0,0,0]
        with self.assertRaises(PreparationError):validate_parameters('static_fixture_v1',p)

    def test_recipe_hash_stable_across_defaults_and_changed_for_physics(self):
        target={'engine':'isaac','usd_version':'0.25.11'};converter={'backend':'sdk','version':'6.1.0'}
        first=preparation_key('a'*64,'rigid_prop_v1',rigid(),target,converter)
        self.assertEqual(first,preparation_key('a'*64,'rigid_prop_v1',validate_parameters('rigid_prop_v1',rigid()),target,converter))
        self.assertNotEqual(first,preparation_key('a'*64,'rigid_prop_v1',rigid(mass_kg=.2),target,converter))
        self.assertNotEqual(first,preparation_key('b'*64,'rigid_prop_v1',rigid(),target,converter))
        with self.assertRaises(PreparationError):preparation_key('bad','rigid_prop_v1',rigid(),target,converter)

if __name__=='__main__':unittest.main()
