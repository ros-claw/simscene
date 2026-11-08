"""Synthetic only: real unchanged ce05 evaluation and raw callback journals."""
import copy
import unittest
from unittest.mock import patch

from experiments import composed_event_mechanisms as c
from simscene.verification import mechanism as m, passive_network as p
from test_mechanism_check import body, spoon_fixture, wheel_fixture, make_strict, loaded_configuration


def fixture():
    sr, ss, sc = spoon_fixture();wr, ws, wc = wheel_fixture()
    spec = copy.deepcopy(ss);spec['objects'].update(copy.deepcopy(ws['objects']))
    spec['objects'].update({n: body([-.5, 0, .5]) for n in ('tile_input', 'wheel_input')})
    run = copy.deepcopy(sr)
    for sample in run['samples']:
        other = wr['samples'][min(sample['physics_steps'], len(wr['samples']))-1]
        for field in ('positions', 'orientations_wxyz', 'joints'):
            sample[field].update(copy.deepcopy(other[field]))
        for name in ('tile_input', 'wheel_input'):
            sample['positions'][m.path(name)] = [-.5+(0.02 if sample['physics_steps'] >= 15 else 0), 0, .5]
            sample['orientations_wxyz'][m.path(name)] = [1, 0, 0, 0]
        sample['contact_pairs'] = []
    run['initial_joint_states'].update(copy.deepcopy(wr['initial_joint_states']))
    run['contact_counts'].update(wr['contact_counts'])
    for name in ('trigger|/World/tile|', 'trigger|/World/wheel|'):
        run['contact_counts'].pop(name)
    run['mechanism_configuration'] = loaded_configuration(spec)
    make_strict(run, spec)
    spec['observation']['record_contact_pairs'] = True
    for case in (sc, wc): case['require_strict_initial_state'] = True
    def event(name): return {'conditions': [{'kind': 'body_displacement', 'body_id': name, 'minimum_m': .001}]}
    case = {'require_strict_initial_state': True, 'trigger_id': 'trigger', 'release_step': 10,
            'contact_window_tolerance_steps': 5,
            'terminal': {'body_id': 'sugar', 'receiver_id': 'cup', 'interior_local': {'min': [-.1]*3, 'max': [.1]*3}, 'hold_steps': 20, 'maximum_motion_m': .002, 'maximum_rotation_degrees': 2},
            'events': {n: event(b) for n, b in [('tile_in', 'tile_input'), ('wheel_in', 'wheel_input'), ('tile_out', 'tile'), ('wheel_out', 'wheel')]},
            'handoffs': []}
    for name, source, target, bodies in [('tile_up', 'trigger_release', 'tile_in', ['trigger', 'tile_input']), ('wheel_up', 'trigger_release', 'wheel_in', ['trigger', 'wheel_input']),
        ('tile_edge', 'tile_in', 'tile_out', ['tile_input', 'tile']), ('wheel_edge', 'wheel_in', 'wheel_out', ['wheel_input', 'wheel']),
        ('tile_end', 'tile_out', 'terminal_entered', ['tile', 'sugar']), ('wheel_end', 'wheel_out', 'terminal_entered', ['wheel', 'sugar'])]:
        case['handoffs'].append({'id': name, 'source_event': source, 'target_event': target, 'body_path': bodies, 'links': [{'kind': 'contact'}], 'maximum_lag_steps': 100})
    decl = {'spoon': {'mechanism_case': sc, 'incoming_handoff_id': 'tile_edge', 'local_input_body_id': 'tile_input'},
            'wheel': {'mechanism_case': wc, 'incoming_handoff_id': 'wheel_edge', 'local_input_body_id': 'wheel_input'}}
    stock = {'passed': True, 'events': {n: {'onset_step': v} for n, v in [('tile_in', 15), ('wheel_in', 15), ('tile_out', 20), ('wheel_out', 20)]},
             'handoffs': {n: {'passed': True} for n in ('tile_edge', 'wheel_edge')}}
    for a, b, step in [('tile_input', 'tile', 19), ('wheel_input', 'wheel', 19), ('tile', 'stopper', 24), ('stopper', 'spoon', 24), ('spoon', 'sugar', 39),
                        ('wheel', 'latch', 24), ('latch', 'door', 29), ('door', 'seat', 40), ('pin', 'door', 58)]:
        sample = run['samples'][step-1]
        sample['contact_pairs'].append({'actor_paths': [m.path(a), m.path(b)], 'collider_paths': [m.path(a), m.path(b)], 'body_ids': [a, b], 'count': 1,
                                       'first_callback_absolute_physics_step': 3+step-1, 'last_callback_absolute_physics_step': 3+step-1})
    return run, spec, case, decl, stock


def evaluate(f): return c.evaluate(*f, 1/60)


class CompositionTests(unittest.TestCase):
    def test_real_complete_p1_reports_preserved_and_only_local_input_composes(self):
        f = fixture();original = copy.deepcopy(f);result = evaluate(f)
        self.assertTrue(result['passed'], result)
        self.assertEqual(f, original)
        for name, value in result['mechanisms'].items():
            raw = value['raw_p1_report']
            self.assertEqual(raw, m.evaluate_event_mechanism(f[0], f[1], f[3][name]['mechanism_case'], 1/60))
            self.assertFalse(raw['passed']);self.assertFalse(value['raw_p1_pilot_passed'])
            self.assertEqual([k for k, v in raw['checks'].items() if not v], [c.AGGREGATE])
            self.assertFalse(raw['contacts'][value['replaced_contact_key']]['passed'])
            self.assertEqual(len(c.BASE_CHECKS), 43)

    def test_actual_original_argument_identity_no_sliced_telemetry(self):
        f = fixture();real = m.evaluate_event_mechanism
        with patch.object(m, 'evaluate_event_mechanism', wraps=real) as spy:
            self.assertTrue(evaluate(f)['passed'])
        for call in spy.call_args_list:
            self.assertIs(call.args[0], f[0]);self.assertIs(call.args[1], f[1]);self.assertEqual(call.args[2]['trigger_id'], 'trigger');self.assertEqual(call.args[2]['release_step'], 10)

    def test_each_other_raw_check_and_contact_remains_mandatory(self):
        f = fixture()
        for name in ('spoon', 'wheel'):
            nested = f[3][name]['mechanism_case'];raw = m.evaluate_event_mechanism(f[0], f[1], nested, 1/60)
            for key in set(raw['checks'])-{c.AGGREGATE}:
                bad = copy.deepcopy(raw);bad['checks'][key] = False;bad['passed'] = False
                with self.subTest(name=name, check=key): self.assertFalse(all(c.inspect_raw(bad, nested).values()))
            for key in set(raw['contacts'])-{c.INCOMING[nested['mechanism']][0]}:
                bad = copy.deepcopy(raw);bad['contacts'][key]['passed'] = False
                with self.subTest(name=name, contact=key): self.assertFalse(c.inspect_raw(bad, nested)['every_nonincoming_raw_contact_passes'])

    def test_missing_extra_nonboolean_checks_or_changed_aggregators_fail(self):
        f = fixture();nested = f[3]['spoon']['mechanism_case'];raw = m.evaluate_event_mechanism(f[0], f[1], nested, 1/60)
        for kind in ('missing', 'extra', 'integer', 'aggregate', 'passed', 'activity', 'missing_contact', 'extra_contact', 'wrong_pair'):
            bad = copy.deepcopy(raw)
            if kind == 'missing': bad['checks'].pop('complete_run')
            elif kind == 'extra': bad['checks']['unknown_new_rule'] = True
            elif kind == 'integer': bad['checks']['complete_run'] = 1
            elif kind == 'aggregate': bad['checks'][c.AGGREGATE] = True
            elif kind == 'passed': bad['passed'] = True
            elif kind == 'activity': bad['activity'] = {'passed': False}
            elif kind == 'missing_contact': bad['contacts'].pop('spoon_to_sugar')
            elif kind == 'extra_contact': bad['contacts']['unknown'] = {'passed': True}
            else: bad['contacts']['spoon_to_sugar']['body_ids'].reverse()
            with self.subTest(kind=kind): self.assertFalse(all(c.inspect_raw(bad, nested).values()))

    def test_local_binding_not_arbitrary_eventual_summary_or_unrelated_dag(self):
        for kind in ('wrong_source', 'global_alias', 'role_alias', 'wrong_edge', 'constraint', 'multi_hop', 'event_body', 'disconnected', 'spawn', 'local_activity', 'rebind_release', 'rebind_trigger', 'extra_definition', 'unsafe_t0'):
            f = fixture();run, spec, case, decl, stock = f;value = decl['spoon'];edge = next(h for h in case['handoffs'] if h['id'] == 'tile_edge')
            if kind == 'wrong_source': value['local_input_body_id'] = 'wheel_input'
            elif kind == 'global_alias': value['local_input_body_id'] = 'trigger'
            elif kind == 'role_alias': value['local_input_body_id'] = 'spoon';edge['body_path'][0] = 'spoon';case['events']['tile_in']['conditions'][0]['body_id'] = 'spoon'
            elif kind == 'wrong_edge': value['incoming_handoff_id'] = 'wheel_edge'
            elif kind == 'constraint': edge['links'] = [{'kind': 'constraint'}]
            elif kind == 'multi_hop': edge['body_path'].insert(1, 'spoon')
            elif kind == 'event_body': case['events']['tile_out']['conditions'][0]['body_id'] = 'wheel'
            elif kind == 'disconnected': case['handoffs'] = [h for h in case['handoffs'] if h['id'] != 'tile_end']
            elif kind == 'spawn': spec['objects']['tile_input']['spawn_step'] = 11
            elif kind == 'local_activity': value['mechanism_case']['activity'] = {}
            elif kind == 'rebind_release': value['mechanism_case']['release_step'] = 15
            elif kind == 'rebind_trigger': value['mechanism_case']['trigger_id'] = 'tile_input'
            elif kind == 'extra_definition': decl['other'] = copy.deepcopy(value)
            else: value['mechanism_case']['require_strict_initial_state'] = False
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError)): evaluate(f)

    def test_original_callbacks_and_global_handoff_both_required_in_activation_window(self):
        for kind in ('no_callback', 'summary_only', 'late', 'before_source', 'wrong_actor', 'bad_raw_boundary', 'handoff_fail', 'stock_fail', 'source_after_activation', 'raw_physics_fail', 'nonincoming_callback_missing', 'missing_step'):
            f = fixture();run, spec, case, decl, stock = f
            pair = run['samples'][18]['contact_pairs'][0]
            if kind in ('no_callback', 'summary_only'): run['samples'][18]['contact_pairs'] = []
            if kind == 'summary_only': run['contact_counts']['tile_input|/World/tile|'] = {'count': 1, 'first_physics_step': 19, 'last_physics_step': 19}
            elif kind in ('late', 'before_source'):
                run['samples'][18]['contact_pairs'] = [];step = 70 if kind == 'late' else 3
                pair.update(first_callback_absolute_physics_step=3+step-1, last_callback_absolute_physics_step=3+step-1)
                run['samples'][step-1]['contact_pairs'].append(pair)
            elif kind == 'wrong_actor': pair['actor_paths'][0] = m.path('wheel_input')
            elif kind == 'bad_raw_boundary': pair['first_callback_absolute_physics_step'] = 999
            elif kind == 'handoff_fail': stock['handoffs']['tile_edge']['passed'] = False
            elif kind == 'stock_fail': stock['passed'] = False
            elif kind == 'source_after_activation': stock['events']['tile_in']['onset_step'] = 21
            elif kind == 'raw_physics_fail': run['samples'][24]['positions'][m.path('stopper')][0] += .02
            elif kind == 'nonincoming_callback_missing': run['samples'][38]['contact_pairs'] = []
            elif kind == 'missing_step': run['samples'].pop(0)
            with self.subTest(kind=kind): self.assertFalse(evaluate(f)['passed'])


if __name__ == '__main__': unittest.main()
