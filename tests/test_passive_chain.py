import copy
import math
import unittest
from experiments.passive_chain_check import evaluate, validate_case


def fixture():
    case={'schema':'simscene.passive_chain.v1','trigger_id':'start','bodies':{'start':{'kind':'sphere'},'tile':{'kind':'tile'},'end':{'kind':'sphere'}},'edges':[['start','tile'],['tile','end']],'receiver':{'body_id':'end','collider_ids':['pan'],'min':[.8,-.2,0],'max':[1.2,.2,.2]}}
    objects={'start':{'kind':'sphere','dynamic':True,'position':[-.5,0,.5],'size':[.06]*3,'spawn_step':60},'tile':{'kind':'box','dynamic':True,'position':[0,0,.12],'size':[.025,.1,.24]},'end':{'kind':'sphere','dynamic':True,'position':[.3,0,.04],'size':[.08]*3},'pan':{'kind':'box','collision':True,'position':[1,0,-.025],'size':[.5,.5,.05]}}
    samples=[]
    for step in range(5,241,5):
        positions={};orientations={}
        for n,o in objects.items():
            if not o.get('dynamic') or n=='start' and step<=60:continue
            positions['/World/'+n]=copy.deepcopy(o['position']);orientations['/World/'+n]=[1,0,0,0]
        if step>=90:orientations['/World/tile']=[math.sqrt(.5),0,math.sqrt(.5),0]
        if step>=110:positions['/World/end']=[1,0,.04]
        samples.append({'physics_steps':step,'positions':positions,'orientations_wxyz':orientations})
    contacts={'start|/World/tile|':{'count':3,'first_physics_step':85},'tile|/World/end|':{'count':2,'first_physics_step':105},'end|/World/pan|':{'count':20,'first_physics_step':115}}
    run={'actual_physics_steps':240,'requested_physics_steps':240,'samples':samples,'contact_counts':contacts,'contacts_truncated':False,'spawn_events':[{'id':'start','physics_step':60}]}
    return run,{'objects':objects},case


class PassiveChainTest(unittest.TestCase):
    def test_translation_can_transfer_contact_before_visible_tipping(self):
        r,s,c=fixture()
        for frame in r['samples']:
            if frame['physics_steps']>=90:frame['positions']['/World/tile']=[.03,0,.12]
            if frame['physics_steps']<180:frame['orientations_wxyz']['/World/tile']=[1,0,0,0]
        self.assertTrue(evaluate(r,s,c)['passed'])

    def test_ordered_passive_transfer_and_stability(self):
        r,s,c=fixture();self.assertTrue(evaluate(r,s,c)['passed'])

    def test_fallen_tiles_without_actual_contact_fail(self):
        r,s,c=fixture();del r['contact_counts']['tile|/World/end|']
        self.assertFalse(evaluate(r,s,c)['checks']['every_handoff_ordered'])

    def test_preexisting_contact_is_not_a_trigger(self):
        r,s,c=fixture();r['contact_counts']['tile|/World/end|']['first_physics_step']=15
        self.assertFalse(evaluate(r,s,c)['passed'])

    def test_downstream_motion_before_upstream_contact_fails(self):
        r,s,c=fixture()
        for frame in r['samples']:
            if frame['physics_steps']>=30:frame['positions']['/World/end']=[1,0,.04]
        self.assertFalse(evaluate(r,s,c)['passed'])

    def test_delayed_downstream_spawn_and_hidden_drive_fail(self):
        for behavior in ({'spawn_step':80},{'conveyor':{'speed_m_s':1}}):
            r,s,c=fixture();s['objects']['end'].update(behavior)
            self.assertFalse(evaluate(r,s,c)['passed'])

    def test_no_trigger_control_requires_downstream_to_stay_still(self):
        r,s,c=fixture();del s['objects']['start'];r['spawn_events']=[]
        for frame in r['samples']:
            frame['positions'].pop('/World/start',None);frame['orientations_wxyz'].pop('/World/start',None)
            frame['positions']['/World/end']=[.3,0,.04];frame['orientations_wxyz']['/World/tile']=[1,0,0,0]
        r['contact_counts']={}
        self.assertTrue(evaluate(r,s,c,'no_trigger')['passed'])
        r['samples'][20]['orientations_wxyz']['/World/tile']=[math.sqrt(.5),0,math.sqrt(.5),0]
        self.assertFalse(evaluate(r,s,c,'no_trigger')['passed'])

    def test_nonfinite_missing_and_shuffled_telemetry_fail(self):
        for change in ('nan','missing','time'):
            r,s,c=fixture()
            if change=='nan':r['samples'][-1]['positions']['/World/end'][0]=float('nan')
            elif change=='missing':
                for frame in r['samples']:frame['positions'].pop('/World/end')
            else:r['samples'].reverse()
            self.assertFalse(evaluate(r,s,c)['passed'])

    def test_terminal_box_inclusion_does_not_mean_sphere_fits(self):
        r,s,c=fixture()
        for frame in r['samples']:
            if frame['physics_steps']>=110:frame['positions']['/World/end']=[1.19,0,.04]
        self.assertFalse(evaluate(r,s,c)['checks']['terminal_received_and_settled'])

    def test_cycles_unreachable_nodes_and_empty_network_rejected(self):
        for edges in ([],[['start','tile']],[['start','tile'],['tile','end'],['end','tile']]):
            r,s,c=fixture();c['edges']=edges
            with self.assertRaises(ValueError):validate_case(c)
