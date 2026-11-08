"""Schema integration counterexamples; all inputs are synthetic CPU fixtures."""
import copy
import unittest

from simscene.verification import passive_network as p
from test_passive_network import fixture
from test_structural_loads import gravity_pad_fixture


def typed_network():
    _, spec, case, _ = fixture()
    load = gravity_pad_fixture(False)
    objects = spec['objects']
    objects['drawer'] = copy.deepcopy(load['spec']['objects']['tray'])
    objects['drawer']['class_label'] = 'drawer'
    objects['pad'] = copy.deepcopy(load['spec']['objects']['pad'])
    objects['pad_slide'] = copy.deepcopy(load['spec']['objects']['pad_slide'])
    case['schema'] = p.SCHEMA_V2
    case['structural_loads'] = copy.deepcopy(load['declarations'])
    case['structural_loads']['pad'].update(support_body_id='drawer', support_motion_event='drawer_opens')
    case['quiet_limits']['pad'] = copy.deepcopy(load['quiet_limits']['pad'])
    case['quiet_limits']['drawer'] = copy.deepcopy(load['quiet_limits']['tray'])
    case['controls']['no_trigger']['downstream_body_ids'].append('pad')
    case['initial_hold_steps'] = 4  # two seating plus two proven support steps
    return spec, case


class TypedNetworkBindingTest(unittest.TestCase):
    def test_explicit_v2_admits_only_typed_structure_without_task_credit(self):
        spec, case = typed_network()
        before = copy.deepcopy((spec, case))
        p.validate_case(case)
        bound = p.bind_case(case, spec)
        self.assertIn('pad', bound['structural_components'])
        self.assertEqual(bound['typed_structural_loads']['body_ids'], ['pad'])
        self.assertNotIn('pad', bound['path_bodies'])
        self.assertEqual((spec, case), before)
        extra = copy.deepcopy(spec)
        extra['objects']['orphan'] = copy.deepcopy(spec['objects']['pad'])
        other_case = copy.deepcopy(case)
        other_case['quiet_limits']['orphan'] = copy.deepcopy(case['quiet_limits']['pad'])
        with self.assertRaisesRegex(ValueError, 'unconnected dynamic'):
            p.bind_case(other_case, extra)

    def test_legacy_schema_does_not_silently_gain_the_new_admission(self):
        spec, case = typed_network()
        case['schema'] = p.SCHEMA
        with self.assertRaisesRegex(ValueError, 'unknown network case fields'):
            p.validate_case(case)
        del case['structural_loads']
        with self.assertRaisesRegex(ValueError, 'unconnected dynamic'):
            p.bind_case(case, spec)

    def test_no_activity_or_household_identity_from_a_load_pad(self):
        spec, case = typed_network()
        case['activity']['stages'][0]['bodies'].append({'id': 'pad', 'minimum_speed_m_s': .01})
        with self.assertRaisesRegex(ValueError, 'cannot supply task activity'):
            p.bind_case(case, spec)
        spec, case = typed_network()
        spec['objects']['pad']['class_label'] = 'brake_weight'
        case['household_categories']['brake'] = {
            'description': 'Attempted extra category from stationary structure',
            'body_ids': ['pad'], 'class_labels': ['brake_weight'], 'activation_events': ['drawer_opens']}
        with self.assertRaisesRegex(ValueError, 'real labeled transmitting'):
            p.bind_case(case, spec)

    def test_retirement_event_must_measure_exactly_the_real_support(self):
        spec, case = typed_network()
        case['structural_loads']['pad']['support_motion_event'] = 'book_moves'
        with self.assertRaisesRegex(ValueError, 'actual support body motion event'):
            p.bind_case(case, spec)

    def test_seating_cannot_consume_the_initial_hold_evidence(self):
        _, case = typed_network()
        case['structural_loads']['pad']['thresholds']['seating_steps'] = 3
        with self.assertRaisesRegex(ValueError, 'leave two supported steps'):
            p.validate_case(case)
        for declarations in (None, {}, []):
            with self.subTest(declarations=declarations):
                _, case = typed_network()
                case['structural_loads'] = declarations
                with self.assertRaises(ValueError):
                    p.validate_case(case)

