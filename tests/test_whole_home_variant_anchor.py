"""Synthetic variant/frame counterexamples; no scene/run observations."""
import copy
import math
import unittest

from experiments import whole_home_suite as suite


def fixture(joint_type='revolute'):
    body = {'kind':'compound','dynamic':True,'collision':True,'mass_kg':1,
            'position':[1.,2.,3.], 'orientation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)],
            'parts':[{'kind':'box','size':[.2,.1,.05]}]}
    joint={'type':joint_type,'body0':None,'body1':'module','enabled':True,
           'local_pos0':[.8,2.1,3.3],'local_pos1':[.1,.2,.3],
           'local_rot0_wxyz':[1,0,0,0],'local_rot1_wxyz':[1,0,0,0],
           'collision_enabled':False}
    if joint_type in ('revolute','prismatic'):
        joint.update(axis='Y',lower_limit=-1,upper_limit=1)
    base={'objects':{'cup':{'kind':'compound','collision':True,'position':[0,0,0]},
                     'shelf':{'kind':'box','collision':True,'size':[1,1,.1]},
                     'module':body,'hinge':{'kind':'joint','joint':joint}}}
    other=copy.deepcopy(base)
    other['objects']['cup']['position']=[.2,0,0]
    other['objects']['shelf']['size'][0]=1.2
    shift=[.03,-.04,.02]
    other['objects']['module']['position']=[a+b for a,b in zip(body['position'],shift)]
    other['objects']['hinge']['joint']['local_pos0']=[a+b for a,b in zip(joint['local_pos0'],shift)]
    paths=[['objects','shelf','size',0],['objects','module','position'],['objects','hinge','joint','local_pos0']]
    def at(document,path):
        for key in path:document=document[key]
        return document
    declaration={'cup_body_id':'cup','cup_delta_world_m':[.2,0,0],
                 'additional_spec_changes':[{'path':p,'before':copy.deepcopy(at(base,p)),
                                             'after':copy.deepcopy(at(other,p))} for p in paths],
                 'case_geometry_changes':[]}
    case={'terminal':{'receiver_id':'cup'},'activity':{'limits':{'minimum_net_effective_action_s':45}}}
    return base,other,case,declaration


def compare(data):
    base,other,case,declaration=data
    return suite.compare_variant(base,other,case,case,declaration)


class SynchronizedWorldAnchorTest(unittest.TestCase):
    def test_all_supported_passive_types_and_patch_orders(self):
        for kind in ('fixed','revolute','prismatic','spherical'):
            for reversed_order in (False,True):
                with self.subTest(kind=kind,reversed_order=reversed_order):
                    data=fixture(kind)
                    if reversed_order:data[3]['additional_spec_changes'].reverse()
                    before=copy.deepcopy(data)
                    report=compare(data)
                    self.assertTrue(report['passed'])
                    self.assertEqual(report['synchronized_world_anchor_edits'][0]['body1_id'],'module')
                    self.assertEqual(data,before)

    def test_roundoff_only_not_physical_preload_tolerance(self):
        data=fixture();changes=data[3]['additional_spec_changes']
        for spec in data[:2]:spec['objects']['hinge']['joint']['local_pos1'][1]=.9
        data[0]['objects']['hinge']['joint']['local_pos0'][0]=.1
        data[1]['objects']['hinge']['joint']['local_pos0'][0]=.13
        changes[2]['before'][0]=.1;changes[2]['after'][0]=.13
        anchor=[a-b for a,b in zip(changes[2]['after'],changes[2]['before'])]
        body=[a-b for a,b in zip(changes[1]['after'],changes[1]['before'])]
        self.assertNotEqual(anchor,body)  # Different subtraction rounding.
        self.assertTrue(compare(data)['passed'])
        changes[2]['after'][1]+=1e-10
        data[1]['objects']['hinge']['joint']['local_pos0']=copy.deepcopy(changes[2]['after'])
        with self.assertRaisesRegex(ValueError,'delta'):compare(data)

    def test_inconsistent_reversed_or_preloaded_anchor_fails(self):
        for error in ('reverse','missing_axis','preload'):
            with self.subTest(error=error):
                data=fixture();patch=data[3]['additional_spec_changes'][2]
                if error=='reverse':patch['after']=[2*a-b for a,b in zip(patch['before'],patch['after'])]
                if error=='missing_axis':patch['after'][2]=patch['before'][2]
                if error=='preload':patch['after'][0]+=.001
                data[1]['objects']['hinge']['joint']['local_pos0']=copy.deepcopy(patch['after'])
                with self.assertRaisesRegex(ValueError,'delta'):compare(data)

    def test_body_translation_must_be_explicit_whole_vector_and_nonzero(self):
        for mode in ('undeclared','component_only','zero'):
            with self.subTest(mode=mode):
                data=fixture();changes=data[3]['additional_spec_changes'];body_patch=changes.pop(1)
                if mode=='component_only':
                    changes.extend({'path':body_patch['path']+[i],'before':body_patch['before'][i],
                                    'after':body_patch['after'][i]} for i in range(3))
                if mode=='zero':
                    body_patch['after']=copy.deepcopy(body_patch['before']);changes.append(body_patch)
                    data[1]['objects']['module']['position']=copy.deepcopy(body_patch['before'])
                with self.assertRaises(ValueError):compare(data)

    def test_changed_body_orientation_fails_even_if_declared(self):
        data=fixture()
        data[1]['objects']['module']['orientation_wxyz']=[1,0,0,0]
        self.assertFalse(compare(data)['passed'])  # Undeclared field stays exact.
        data[3]['additional_spec_changes'].append({'path':['objects','module','orientation_wxyz'],
            'before':data[0]['objects']['module']['orientation_wxyz'],'after':[1,0,0,0]})
        with self.assertRaisesRegex(ValueError,'orientation'):compare(data)

    def test_other_joint_fields_and_full_joint_replacement_stay_forbidden(self):
        values={'axis':'Z','lower_limit':-2,'upper_limit':2,'enabled':False,
                'body0':'module','body1':'shelf','collision_enabled':True,
                'local_pos1':[0,0,0],'local_rot0_wxyz':[0,1,0,0],
                'local_rot1_wxyz':[0,1,0,0],'type':'fixed','drive':{'target':1}}
        for key,after in values.items():
            with self.subTest(field=key):
                data=fixture();old=data[0]['objects']['hinge']['joint']
                data[3]['additional_spec_changes'].append({'path':['objects','hinge','joint',key],
                    'before':copy.deepcopy(old.get(key)),'after':after})
                with self.assertRaises(ValueError):compare(data)
        data=fixture();old=data[0]['objects']['hinge']['joint'];new=data[1]['objects']['hinge']['joint']
        data[3]['additional_spec_changes'][2]={'path':['objects','hinge','joint'],'before':old,'after':new}
        with self.assertRaises(ValueError):compare(data)

    def test_anchor_components_duplicates_and_overlaps_are_forbidden(self):
        for mode in ('anchor_components','duplicate_anchor','overlap_body'):
            with self.subTest(mode=mode):
                data=fixture();changes=data[3]['additional_spec_changes']
                if mode=='anchor_components':
                    patch=changes.pop(2)
                    changes.extend({'path':patch['path']+[i],'before':patch['before'][i],
                                    'after':patch['after'][i]} for i in range(3))
                if mode=='duplicate_anchor':changes.append(copy.deepcopy(changes[2]))
                if mode=='overlap_body':changes.append({'path':['objects','module','position',0],
                    'before':changes[1]['after'][0],'after':changes[1]['after'][0]+.1})
                with self.assertRaises(ValueError):compare(data)

    def test_nonfinite_or_nonvector_anchor_and_position_fail(self):
        invalid=([0,0],[0,0,0,0],[0,True,0],[0,'0',0],[0,float('nan'),0],
                 [0,float('inf'),0],None,{'x':0,'y':0,'z':0})
        for index in (1,2):
            for value in invalid:
                with self.subTest(patch=index,value=value):
                    data=fixture();patch=data[3]['additional_spec_changes'][index]
                    patch['after']=copy.deepcopy(value)
                    if index==1:data[1]['objects']['module']['position']=copy.deepcopy(value)
                    else:data[1]['objects']['hinge']['joint']['local_pos0']=copy.deepcopy(value)
                    with self.assertRaises(ValueError):compare(data)

    def test_original_world_joint_must_be_enabled_supported_and_passive(self):
        for mutation in ({'enabled':False},{'type':'distance'},{'drive':{}},{'target_position':0},
                         {'body0':'module'},{'body0':'shelf'}):
            with self.subTest(mutation=mutation):
                data=fixture()
                for spec in data[:2]:spec['objects']['hinge']['joint'].update(mutation)
                with self.assertRaises(ValueError):compare(data)
        data=fixture()
        for spec in data[:2]:
            spec['objects']['other_body']=copy.deepcopy(spec['objects']['module'])
            spec['objects']['hinge']['joint']['body0']='other_body'
        with self.assertRaisesRegex(ValueError,'world/body1'):compare(data)

    def test_endpoint_must_be_existing_dynamic_collision_geometry(self):
        mutations=({'dynamic':False},{'dynamic':1},{'collision':False,'parts':[{'kind':'box','collision':False}]},
                   {'kind':'asset'},{'kind':'camera'},{'spawn_step':60},{'parts':[]})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data=fixture()
                for spec in data[:2]:spec['objects']['module'].update(copy.deepcopy(mutation))
                with self.assertRaises(ValueError):compare(data)
        data=fixture()
        for spec in data[:2]:spec['objects']['hinge']['joint']['body1']='missing'
        with self.assertRaises(ValueError):compare(data)
        data=fixture();data[1]['objects']['module']['parts'][0]['collision']=False
        data[3]['additional_spec_changes'].append({'path':['objects','module','parts',0,'collision'],
            'before':True,'after':False})
        for spec in data[:1]:spec['objects']['module']['parts'][0]['collision']=True
        with self.assertRaisesRegex(ValueError,'colliding'):compare(data)

    def test_real_primitive_collision_body_and_multiple_world_joints(self):
        data=fixture()
        for spec in data[:2]:
            spec['objects']['module'].update(kind='sphere',size=[.1,.1,.1])
            del spec['objects']['module']['parts']
        self.assertTrue(compare(data)['passed'])
        for spec in data[:2]:spec['objects']['second_hinge']=copy.deepcopy(spec['objects']['hinge'])
        patch=copy.deepcopy(data[3]['additional_spec_changes'][2]);patch['path'][1]='second_hinge'
        data[3]['additional_spec_changes'].append(patch)
        self.assertEqual(len(compare(data)['synchronized_world_anchor_edits']),2)
        for spec in data[:2]:spec['objects']['module']['collision']=False
        with self.assertRaises(ValueError):compare(data)

    def test_frame_edit_alone_gets_no_independent_layout_credit(self):
        data=fixture();data[3]['additional_spec_changes']=[data[3]['additional_spec_changes'][2]]
        with self.assertRaisesRegex(ValueError,'independent'):compare(data)

    def test_existing_joint_and_anchor_field_required(self):
        for mode in ('missing_joint','missing_anchor','not_joint'):
            with self.subTest(mode=mode):
                data=fixture()
                if mode=='missing_joint':data[3]['additional_spec_changes'][2]['path'][1]='absent'
                if mode=='missing_anchor':del data[0]['objects']['hinge']['joint']['local_pos0']
                if mode=='not_joint':data[0]['objects']['hinge']['kind']='box'
                with self.assertRaises(ValueError):compare(data)

    def test_delta_overflow_fails_even_with_finite_endpoints(self):
        data=fixture()
        for index,name,key in ((1,'module','position'),(2,'hinge','local_pos0')):
            patch=data[3]['additional_spec_changes'][index]
            patch['before']=[-1e308,0,0];patch['after']=[1e308,0,0]
            for spec,value in ((data[0],patch['before']),(data[1],patch['after'])):
                target=spec['objects'][name] if name=='module' else spec['objects'][name]['joint']
                target[key]=copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError,'delta'):compare(data)

    def test_undeclared_changes_and_original_nonanchor_predicates_stay_exact(self):
        data=fixture();data[1]['objects']['module']['mass_kg']=2
        self.assertFalse(compare(data)['passed'])
        data=fixture();data[3]['additional_spec_changes'].pop(2)
        data[1]['objects']['hinge']=copy.deepcopy(data[0]['objects']['hinge'])
        body_patch=data[3]['additional_spec_changes'].pop(1)
        data[3]['additional_spec_changes'].extend({'path':body_patch['path']+[i],
            'before':body_patch['before'][i],'after':body_patch['after'][i]} for i in range(3))
        self.assertTrue(compare(data)['passed'])  # Original v2 local geometry rule.
        self.assertEqual(compare(data)['synchronized_world_anchor_edits'],[])


if __name__=='__main__':unittest.main()
