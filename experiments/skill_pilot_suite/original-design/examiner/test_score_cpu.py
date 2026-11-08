"""Synthetic numerical examiner tests. Never native physics or pilot evidence.

Fixtures intentionally describe abstract measurements, not editable scene recipes.
"""
import copy
from pathlib import Path
import math
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import score

ROOT=Path(__file__).resolve().parents[1]


def case(task):
    return score.read(ROOT/'public'/task/'public-case.json')


def contact(step,a,b):
    return {'observation_step':step,'body_ids':[a,b]}


def fixture(task,mode='positive'):
    c=case(task);samples=[];records=[]
    initial={'positions':{'/World/payload':[0,0,0.05]},'orientations_wxyz':{'/World/payload':[1,0,0,0]}}
    if task=='P1':
        initial['positions']['/World/lever']=[0,0,0]
        initial['orientations_wxyz']['/World/lever']=[1,0,0,0]
        initial['positions']['/World/payload']=[0.5,0,0.05]
    for step in range(1,721):
        s={'physics_steps':step,'positions':copy.deepcopy(initial['positions']),'orientations_wxyz':copy.deepcopy(initial['orientations_wxyz'])}
        if step>60:
            if task=='P1':s['positions']['/World/driver']=[-0.5,0,0.5-min(step-61,20)*0.01]
            else:
                s['positions']['/World/driver']=[min(step-61,30)*0.01,0,0.3-min(step-61,20)*0.005]
                spin=math.radians(min(step-61,30)*3)/2
                s['orientations_wxyz']['/World/driver']=[math.cos(spin),0,math.sin(spin),0]
        if task=='P1':
            a=0 if mode=='negative' or step<85 else min(step-84,20)*0.7
            q=[math.cos(math.radians(a)/2),0,-math.sin(math.radians(a)/2),0]
            s['orientations_wxyz']['/World/lever']=q
            s['positions']['/World/payload']=score.rotate(q,initial['positions']['/World/payload'])
            s['orientations_wxyz']['/World/payload']=q
            records.append(contact(step,'payload','lever'))
            if step==85:records.append(contact(step,'driver','lever'))
        else:
            if mode=='positive' and step>=90:s['positions']['/World/payload'][0]=min(step-89,20)*0.01
            records.append(contact(step,'payload','deck'))
            if 65<=step<=85:records.append(contact(step,'driver','ramp'))
            if mode=='positive' and step==90:records.append(contact(step,'driver','payload'))
        samples.append(s)
    spec={'objects':{'deck':{'position':[0,0,-0.05],'size':[2,2,0.10]},'payload':{'size':[0.1]*3}}}
    return {'run':{'samples':samples,'initial_observation':initial},'spec':spec,'journal':{'records':records}}


class TaskPredicates(unittest.TestCase):
    def test_both_abstract_positive_predicates(self):
        for task in ('P1','P2'):
            with self.subTest(task=task):
                report=score.task_predicates(fixture(task),case(task),'positive')
                self.assertTrue(report['passed'],report)

    def test_both_abstract_negative_predicates(self):
        for task in ('P1','P2'):
            with self.subTest(task=task):
                report=score.task_predicates(fixture(task,'negative'),case(task),'negative')
                self.assertTrue(report['passed'],report)

    def test_silent_upstream_cannot_pass_either_negative(self):
        for task in ('P1','P2'):
            d=fixture(task,'negative')
            for s in d['run']['samples']:
                if '/World/driver' in s['positions']:s['positions']['/World/driver']=[0,0,0.3]
            self.assertFalse(score.task_predicates(d,case(task),'negative')['passed'])

    def test_ballistic_lift_without_carrier_contact_fails(self):
        d=fixture('P1');d['journal']['records']=[r for r in d['journal']['records'] if r['observation_step']<85 or set(r['body_ids'])!={'payload','lever'}]
        self.assertFalse(score.task_predicates(d,case('P1'),'positive')['passed'])

    def test_free_payload_cannot_self_start_before_collision(self):
        d=fixture('P2')
        d['run']['samples'][75]['positions']['/World/payload'][0]=0.03
        self.assertFalse(score.task_predicates(d,case('P2'),'positive')['passed'])

    def test_puck_fall_cannot_masquerade_as_slide(self):
        d=fixture('P2')
        for s in d['run']['samples'][100:]:s['positions']['/World/payload'][2]-=0.2
        self.assertFalse(score.task_predicates(d,case('P2'),'positive')['passed'])

    def test_puck_outside_deck_fails(self):
        d=fixture('P2');d['spec']['objects']['deck']['size'][0]=0.3
        self.assertFalse(score.task_predicates(d,case('P2'),'positive')['passed'])

    def test_nonrotating_driver_is_not_a_rolling_success(self):
        d=fixture('P2')
        for s in d['run']['samples']:
            if '/World/driver' in s['positions']:s['orientations_wxyz']['/World/driver']=[1,0,0,0]
        self.assertFalse(score.task_predicates(d,case('P2'),'positive')['passed'])

    def test_negative_with_remaining_contact_fails(self):
        d=fixture('P2','negative');d['journal']['records'].append(contact(90,'driver','payload'))
        self.assertFalse(score.task_predicates(d,case('P2'),'negative')['passed'])


class SceneIsolation(unittest.TestCase):
    def specimen(self,task):
        objects={'driver':{'kind':'sphere','collision_exclusions':[]},'payload':{'kind':'box'}}
        if task=='P1':objects.update(lever={'kind':'compound'},hinge={'kind':'joint','joint':{'type':'revolute','body0':None,'body1':'lever','axis':'Y','lower_limit':-30,'upper_limit':30}})
        spec={'objects':objects,'observation':case(task)['observation'],'scene_id':'one','revision':1,'requests':{}}
        lock={k:1 for k in (*score.PAIRED_FIELDS,'seed','requested_physics_steps')}
        a={'spec':spec,'root':Path('/anonymous/one'),'lock':dict(lock,run_id='one')}
        b=copy.deepcopy(a);b['root']=Path('/anonymous/two');b['lock']['run_id']='two';b['spec']['scene_id']='two';b['spec']['revision']=9
        if task=='P1':b['spec']['objects']['hinge']['joint'].update(lower_limit=0,upper_limit=0)
        else:b['spec']['objects']['driver']['collision_exclusions'].append('payload')
        return a,b

    def test_only_prescribed_intervention_is_accepted(self):
        for task in ('P1','P2'):
            a,b=self.specimen(task)
            self.assertTrue(score.isolated_intervention(a,b,case(task))['passed'])
            b['spec']['objects']['payload']['mass_kg']=1
            self.assertFalse(score.isolated_intervention(a,b,case(task))['passed'])

    def test_presentation_or_observation_change_fails(self):
        for task in ('P1','P2'):
            a,b=self.specimen(task);b['spec']['observation']['sample_interval_steps']=2
            self.assertFalse(score.isolated_intervention(a,b,case(task))['passed'])

    def test_same_saved_run_cannot_be_two_runs(self):
        a,b=self.specimen('P2');b['root']=a['root']
        self.assertFalse(score.isolated_intervention(a,b,case('P2'))['passed'])

    def test_locking_noninitial_angle_fails(self):
        a,b=self.specimen('P1');b['spec']['objects']['hinge']['joint'].update(lower_limit=3,upper_limit=3)
        self.assertFalse(score.isolated_intervention(a,b,case('P1'))['passed'])

    def test_approved_runtime_is_required(self):
        checks=score.runtime_identity({'runtime_python':'invented'},{'approved_manifest_fields':{}})
        self.assertFalse(all(checks.values()))


class SmokeSource(unittest.TestCase):
    def test_generic_smoke_ops_apply_in_memory_store_without_isaac(self):
        sys.path.insert(0,str(ROOT/'smoke-source'))
        from generic_smoke_ops import ops
        from simscene.scene import SceneStore
        with tempfile.TemporaryDirectory(prefix='pilot-smoke-schema-') as folder:
            store=SceneStore(folder);store.open('unrelated_smoke');result=store.apply('unrelated_smoke',0,'source_only_check',ops)
            self.assertEqual(result['revision'],1)
            self.assertFalse(set(store.get('unrelated_smoke')['objects']) & {'driver','payload','lever','hinge','ramp','deck'})


if __name__=='__main__':unittest.main()
