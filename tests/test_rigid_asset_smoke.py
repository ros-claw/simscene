import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simscene.verification.rigid_asset_smoke import evaluate, verify_run
from simscene.evidence_integrity import seal


def fixture():
    motion = '/World/item/Asset/Body'
    binding = {'motion_body': motion, 'contact_bodies': [motion], 'visual_roots': [motion + '/Visual']}
    case = {'schema': 'simscene.rigid_asset_smoke.v1', 'schema_version': 1, 'objects': {'item': dict(binding, support_actors=['/World/support'], target_bounds={'min': [-.5, -.5, 0], 'max': [.5, .5, .5]}, initial_height_m=1., min_drop_m=.5)}}
    frames = []
    for step in range(61):
        t = step * .05
        z = max(.2, 1 - t * 1.6)
        frame = {'physics_steps': step * 3, 'simulation_time_s': t, 'positions': {motion: [0., 0., z], '/World/item': [0., 0., 1.]}, 'orientations_wxyz': {motion: [1., 0., 0., 0.]}, 'bounds': {'item': {'min': [-.1, -.1, z - .1], 'max': [.1, .1, z + .1]}}}
        if step == 10:
            frame['contact_pairs'] = [{'actor_paths': [motion, '/World/support'], 'collider_paths': [motion + '/Visual/Mesh0', '/World/support'], 'count': 1, 'first_callback_absolute_physics_step': 130, 'last_callback_absolute_physics_step': 130}]
        frames.append(frame)
    run = {'body_bindings': {'item': binding}, 'initial_observation': frames[0], 'samples': frames[1:], 'observation_interval_steps': 3, 'requested_physics_steps': 180, 'actual_physics_steps': 180, 'run_zero_absolute_physics_step': 100, 'simulation_time_s': 3., 'samples_truncated': False, 'contacts_truncated': False, 'contact_geometry_incomplete': False, 'partial': False, 'followers': {}}
    return run, case


class RigidAssetSmokeTests(unittest.TestCase):
    def test_required_baffle_contact_cannot_be_substituted_by_support_or_prefix(self):
        run,case=fixture();case['objects']['item']['required_contact_actors']=['/World/baffle']
        self.assertFalse(evaluate(run,case)['passed'])
        pair=copy.deepcopy(run['samples'][9]['contact_pairs'][0])
        pair['actor_paths'][1]='/World/baffle/Neighbor'
        run['samples'][9]['contact_pairs'].append(pair)
        self.assertFalse(evaluate(run,case)['passed'])
        pair['actor_paths'][1]='/World/baffle'
        self.assertTrue(evaluate(run,case)['passed'])

    def test_actual_nested_body_moves_static_wrapper_cannot_pass(self):
        run, case = fixture()
        self.assertTrue(evaluate(run, case)['passed'])
        wrong = copy.deepcopy(case)
        wrong['objects']['item']['motion_body'] = '/World/item'
        self.assertFalse(evaluate(run, wrong)['passed'])
        run['body_bindings']['item']['motion_body'] = '/World/item'
        self.assertFalse(evaluate(run, wrong)['passed'])

    def test_collider_negative_and_actor_prefix_cannot_substitute(self):
        run, case = fixture()
        for frame in run['samples']:
            frame['contact_pairs'] = []
        self.assertFalse(evaluate(run, case)['passed'])
        run['samples'][20]['contact_pairs'] = [{'actor_paths': ['/World/item/Asset/Body/Fake', '/World/support'], 'count': 1, 'first_callback_absolute_physics_step': 130, 'last_callback_absolute_physics_step': 130}]
        self.assertFalse(evaluate(run, case)['passed'])
        run['samples'][20]['contact_pairs'][0]['actor_paths'][0] = '/World/item/Asset/Body'
        self.assertTrue(evaluate(run, case)['passed'])

    def test_full_bounds_and_two_second_linear_angular_settling(self):
        for mutation in ('bounds', 'linear', 'angular'):
            run, case = fixture()
            if mutation == 'bounds':
                run['samples'][-1]['bounds']['item']['max'][0] = 1.
            elif mutation == 'linear':
                run['samples'][-1]['positions']['/World/item/Asset/Body'][0] = .1
            else:
                run['samples'][-1]['orientations_wxyz']['/World/item/Asset/Body'] = [.70710678, 0, 0, .70710678]
            with self.subTest(mutation=mutation):
                self.assertFalse(evaluate(run, case)['passed'])

    def test_partial_truncated_missing_samples_and_wrong_initial_height(self):
        for key in ('partial', 'contacts_truncated', 'contact_geometry_incomplete', 'samples_truncated'):
            run, case = fixture(); run[key] = True
            with self.subTest(key=key):
                self.assertFalse(evaluate(run, case)['passed'])
        run, case = fixture(); del run['samples'][30]
        self.assertFalse(evaluate(run, case)['passed'])
        run, case = fixture(); run['samples'] = run['samples'][8:]
        self.assertFalse(evaluate(run, case)['passed'])
        run, case = fixture(); run['actual_physics_steps'] -= 1
        self.assertFalse(evaluate(run, case)['passed'])
        run, case = fixture(); case['objects']['item']['initial_height_m'] = 2.
        self.assertFalse(evaluate(run, case)['passed'])
        run, case = fixture(); run['followers'] = {'robot': {'status': 'active'}}
        self.assertFalse(evaluate(run, case)['passed'])

    def test_four_independent_frozen_maps(self):
        run, case = fixture()
        template = copy.deepcopy(case['objects']['item'])
        original = '/World/item/Asset/Body'
        for name in ('two', 'three', 'four'):
            new = '/World/' + name + '/Asset/Body'
            entry = copy.deepcopy(template); entry.update(motion_body=new, contact_bodies=[new], visual_roots=[new + '/Visual'])
            case['objects'][name] = entry
            run['body_bindings'][name] = {k: entry[k] for k in ('motion_body', 'contact_bodies', 'visual_roots')}
            for frame in [run['initial_observation']] + run['samples']:
                frame['positions'][new] = list(frame['positions'][original])
                frame['orientations_wxyz'][new] = [1., 0., 0., 0.]
                frame['bounds'][name] = copy.deepcopy(frame['bounds']['item'])
            run['samples'][9]['contact_pairs'].append({'actor_paths': [new, '/World/support'], 'count': 1, 'first_callback_absolute_physics_step': 130, 'last_callback_absolute_physics_step': 130})
        self.assertTrue(evaluate(run, case)['passed'])
        del run['samples'][-1]['positions']['/World/four/Asset/Body']
        result = evaluate(run, case)
        self.assertFalse(result['passed'])
        self.assertFalse(result['objects']['four']['passed'])
        self.assertTrue(result['objects']['two']['passed'])

    def test_saved_evidence_and_input_integrity_gates(self):
        run, case = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'acceptance-case.json').write_text(json.dumps(case))
            (root / 'run-lock.json').write_text(json.dumps({'acceptance_case_file': 'acceptance-case.json', 'acceptance_case_sha256': hashlib.sha256((root / 'acceptance-case.json').read_bytes()).hexdigest(), 'body_bindings': run['body_bindings']}))
            (root / 'result.json').write_text(json.dumps(run)); seal(root)
            with patch('simscene.run_integrity.verify', return_value={'passed': True}):
                self.assertTrue(verify_run(root)['passed'])
                (root / 'result.json').write_text(json.dumps(dict(run, seed=2)))
                self.assertFalse(verify_run(root)['passed'])
            (root / 'result.json').write_text(json.dumps(run)); seal(root)
            with patch('simscene.run_integrity.verify', return_value={'passed': False}):
                self.assertFalse(verify_run(root)['passed'])
            (root / 'acceptance-case.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'case changed'):
                verify_run(root)

    def test_frozen_source_and_prepared_identity_are_enforced(self):
        run,case=fixture();case.update(prepared_manifest_sha256='a'*64,source_ref={'source_id':'fixture','asset_id':'selected','revision':'b'*40})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'acceptance-case.json').write_text(json.dumps(case))
            (root/'run-lock.json').write_text(json.dumps({'acceptance_case_file':'acceptance-case.json',
                'acceptance_case_sha256':hashlib.sha256((root/'acceptance-case.json').read_bytes()).hexdigest(),'body_bindings':run['body_bindings']}))
            (root/'result.json').write_text(json.dumps(run))
            (root/'spec.json').write_text(json.dumps({'objects':{'item':{'asset_path':'fixture.usda',
                'asset_binding':{'manifest_path':'fixture.json','manifest_sha256':'a'*64}}}}))
            seal(root)
            with patch('simscene.run_integrity.verify',return_value={'passed':True}),patch('simscene.physics_binding.validate_asset_binding',return_value={'source_ref':case['source_ref']}) as manifest:
                self.assertTrue(verify_run(root)['passed'])
                manifest.return_value={'source_ref':dict(case['source_ref'],asset_id='substitute')}
                self.assertFalse(verify_run(root)['passed'])


if __name__ == '__main__':
    unittest.main()
