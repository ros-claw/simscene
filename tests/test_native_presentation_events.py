"""Pure CPU camera-event proposals; no runtime or model execution."""
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from simscene.presentation_native import proposed_events,frozen_events
from simscene.presentation import events
from test_preparation_articulation import smoke_fixture
from test_handoff_chain import fixture as handoff_fixture


class NativePresentationTests(unittest.TestCase):
    def test_commands_actual_motion_and_tolerance_waypoints_are_distinct_evidence(self):
        run,case=smoke_fixture();before=copy.deepcopy(run);proposals=proposed_events(run,case)
        commands=[p for p in proposals if p['kind']=='declared_joint_command']
        motion=[p for p in proposals if p['kind']=='joint_motion_started']
        waypoints=[p for p in proposals if p['kind']=='waypoint_observed']
        self.assertEqual(len(commands),2);self.assertEqual([p['endpoint'] for p in commands],['first','last'])
        self.assertEqual(commands[0]['declared_command_count'],2)
        self.assertEqual(len(motion),1);self.assertEqual(motion[0]['physics_step'],1)
        self.assertEqual(len(waypoints),2)
        self.assertTrue(all(abs(p['actual_position']-p['target_position'])<=p['tolerance'] for p in waypoints))
        self.assertNotEqual(waypoints[0]['physics_step'],commands[0]['physics_step'])
        for proposal in proposals:
            self.assertTrue(proposal['evidence_ref'].startswith('result.json#/'))
            self.assertTrue(proposal['case_ref'].startswith('acceptance-case.json#/objects/valve/'))
            self.assertIn('no runtime action',proposal['scope'])
        self.assertEqual(run,before)

    def test_recorded_targets_cannot_fabricate_actual_motion(self):
        run,case=smoke_fixture()
        for frame in [run['initial_observation']]+run['samples']:
            frame['mechanisms']['valve']['joints']['main']['position']=999.
        self.assertEqual(proposed_events(run,case),[])
        run,case=smoke_fixture()
        for frame in [run['initial_observation']]+run['samples']:
            frame['mechanisms']['valve']['joints']['main']['measurement_source']='declared_target'
        self.assertEqual(proposed_events(run,case),[])

    def test_241_commands_emit_only_first_last_and_counts(self):
        run,case=smoke_fixture();item=case['objects']['valve'];points=[];commands=[]
        # Frozen closing endpoints remain distinct; first large target then tiny
        # scheduled decrements, all merely declared camera landmarks here.
        for i in range(241):
            target=1.-i/240
            points.append({'command_step':i,'target_position':target,'by_step':i+1,'tolerance':.03})
            commands.append({'joint_id':'main','physics_step':i,'target_position':target,'position_unit':'rad',
                'cause':'declared_at_step_schedule','trigger':{'type':'at_step','physics_step':i},'drive_readback':{'fixture':True}})
        item['waypoints']=points
        run['samples'][-1]['mechanisms']['valve']['command_events']=commands
        result=proposed_events(run,case)
        declared=[e for e in result if e['kind']=='declared_joint_command']
        self.assertEqual(len(declared),2);self.assertEqual({e['declared_command_count'] for e in declared},{241})
        self.assertEqual({e['recorded_matching_command_count'] for e in declared},{241})
        self.assertLessEqual(sum(e['kind']=='waypoint_observed' for e in result),2)
        self.assertLessEqual(len(result),5)

    def test_handoff_only_declared_exact_pairs_and_no_future_or_invalid_callbacks(self):
        run,case=handoff_fixture();result=proposed_events(run,case)
        self.assertEqual(len(result),6);self.assertTrue(all(e['kind']=='contact_observed' for e in result))
        self.assertEqual(result[0]['physics_step'],8);self.assertAlmostEqual(result[0]['sim_time_s'],8/60)
        self.assertIn('necessary causality untested',result[0]['interpretation'])
        for mutation in ('future','prefix','zero','incomplete'):
            bad=copy.deepcopy(run)
            if mutation=='future':
                pair=bad['samples'][7]['contact_pairs'][0];pair['first_callback_absolute_physics_step']=pair['last_callback_absolute_physics_step']=109
            elif mutation=='prefix':bad['samples'][7]['contact_pairs'][0]['actor_paths'][0]+='/Other'
            elif mutation=='zero':bad['run_zero_absolute_physics_step']=None
            else:bad['contact_geometry_incomplete']=True
            events=proposed_events(bad,case)
            with self.subTest(mutation=mutation):self.assertFalse(any(e['actor_paths'][0]==case['source_body'] for e in events))
        run['samples'][10]['contact_pairs'].append({'actor_paths':['/World/unrelated','/World/other'],'count':1,
            'first_callback_absolute_physics_step':111,'last_callback_absolute_physics_step':111})
        self.assertEqual(len(proposed_events(run,case)),6)

    def test_missing_full_timeline_returns_no_native_proposals(self):
        run,case=smoke_fixture()
        for mutation in ('partial','truncated','missing','clock'):
            bad=copy.deepcopy(run)
            if mutation=='partial':bad['partial']=True
            elif mutation=='truncated':bad['samples_truncated']=True
            elif mutation=='missing':del bad['samples'][3]
            else:bad['samples'][3]['simulation_time_s']=99
            with self.subTest(mutation=mutation):self.assertEqual(proposed_events(bad,case),[])

    def test_gallery_bound_includes_honest_truncation_summary_and_component_pointers(self):
        run,case=handoff_fixture()
        gallery={'schema':'simscene.asset_gallery.v1','schema_version':1,
            'components':[{'id':'unit-'+str(i),'case':copy.deepcopy(case)} for i in range(16)]}
        result=proposed_events(run,gallery)
        self.assertEqual(len(result),64);summary=result[-1]
        self.assertEqual(summary['kind'],'native_event_truncation')
        self.assertEqual(summary['total_candidate_event_count'],96);self.assertEqual(summary['omitted_event_count'],33)
        self.assertTrue(all(e['case_ref'].startswith('acceptance-case.json#/components/') for e in result[:-1]))
        self.assertEqual(len(proposed_events(run,gallery,max_events=5)),5)

    def test_frozen_case_required_and_legacy_events_unchanged(self):
        run,case=handoff_fixture()
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'result.json').write_text(json.dumps(run));(root/'spec.json').write_text('{"objects":{}}')
            self.assertEqual(events(root),[])
            (root/'run-lock.json').write_text(json.dumps({'acceptance_case_file':'acceptance-case.json','acceptance_case_sha256':'legacy'}))
            self.assertEqual(events(root),[])
            frozen=root/'acceptance-case.json';frozen.write_text(json.dumps(case))
            (root/'run-lock.json').write_text(json.dumps({'acceptance_case_file':frozen.name,
                'acceptance_case_sha256':hashlib.sha256(frozen.read_bytes()).hexdigest()}))
            self.assertEqual(len(events(root)),6)
            frozen.write_text(json.dumps(dict(case,steps=181)))
            with self.assertRaisesRegex(ValueError,'hash changed'):frozen_events(root,run)


if __name__=='__main__':unittest.main()
