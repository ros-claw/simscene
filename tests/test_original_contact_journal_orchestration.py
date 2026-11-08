"""Real callback reader with deliberately mocked custody/stock plumbing only."""
import ast
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import whole_home_fidelity_v7 as f, whole_home_fidelity_v6 as old
from test_composed_event_mechanisms import fixture


def stock_summary(journal):
    return {'passed': journal['passed'], 'record_count': len(journal['records']),
            'errors': journal['errors'], 'scope': journal['scope']}


class OriginalJournalTests(unittest.TestCase):
    def test_one_real_reader_exact_summary_projection_and_original_argument_identity(self):
        run, spec, *_ = fixture();before = copy.deepcopy((run, spec))
        actual = f.p.contact_journal(run, spec);summary = stock_summary(actual)
        self.assertNotIn('records', summary)
        with patch.object(f.p, 'contact_journal', wraps=f.p.contact_journal) as spy:
            journal = f.reconstruct_contact_journal(run, spec, summary)
        spy.assert_called_once();self.assertIs(spy.call_args.args[0], run);self.assertIs(spy.call_args.args[1], spec)
        self.assertEqual(journal, actual);self.assertEqual((run, spec), before)

    def test_every_summary_field_missing_unknown_or_changed_rejects(self):
        run, spec, *_ = fixture();summary = stock_summary(f.p.contact_journal(run, spec))
        for key in summary:
            for operation in ('missing', 'changed'):
                altered = copy.deepcopy(summary)
                if operation == 'missing': altered.pop(key)
                else: altered[key] = {'passed': False, 'record_count': summary['record_count']+1, 'errors': ['new'], 'scope': 'different'}[key]
                with self.subTest(key=key, operation=operation), self.assertRaises(ValueError): f.reconstruct_contact_journal(run, spec, altered)
        for value in (None, {}, {**summary, 'records': []}):
            with self.subTest(value=value), self.assertRaises(ValueError): f.reconstruct_contact_journal(run, spec, value)
        for value in ({**summary, 'passed': 1}, {**summary, 'record_count': float(summary['record_count'])}):
            with self.subTest(value=value), self.assertRaises(ValueError): f.reconstruct_contact_journal(run, spec, value)
        run['samples'][0].pop('contact_pairs')
        with self.assertRaises(ValueError): f.reconstruct_contact_journal(run, spec, summary)
        failed = f.p.contact_journal(run, spec)
        with self.assertRaises(ValueError): f.reconstruct_contact_journal(run, spec, stock_summary(failed))

    def test_positive_file_orchestration_uses_original_full_journal_once_not_stock_summary(self):
        run, spec, case, decl, stock = fixture()
        for step in range(101, 241):
            sample = copy.deepcopy(run['samples'][-1]);sample.update(physics_steps=step, simulation_time_s=step/60,
                absolute_physics_step=3+step, absolute_simulation_time_s=.05+step/60, contact_pairs=[])
            run['samples'].append(sample)
        run.update(requested_physics_steps=240, actual_physics_steps=240, simulation_time_s=4.)
        real_journal = f.p.contact_journal(run, spec)
        stock['contact_journal'] = stock_summary(real_journal)
        stock['terminal'] = {'stable_onset_step': 50, 'stable_confirmation_step': 171}
        stock['events'].update(start={'onset_step': 40}, end={'onset_step': 60})
        original_stock = copy.deepcopy(stock)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('run-lock.json', 'evidence-lock.json'):
                (root/name).write_text(json.dumps({'artifacts': {'result.json': {'sha256': 'e'*64}}}))
            nominal = f.canonical_sha(f.canonical_spec(spec, {}))
            review = {'passed': True, 'scope': 'nominal_static_preflight', 'reviewer_role': 'independent_examiner',
                'nominal_configuration_sha256': nominal, 'network_case_sha256': 'c'*64,
                'role_asset_proxy_review_passed': True, 'energy_force_catalog_passed': True,
                'non_contact_auxiliary_review_passed': True, 'non_contact_auxiliary_body_ids': []}
            rp = root/'review.json';rp.write_text(json.dumps(review))
            contract = {'static_review_sha256': f.sha(rp), 'network_case_sha256': 'c'*64,
                'nominal_configuration_sha256': nominal, 'composed_mechanisms': decl,
                'non_contact_auxiliary_body_ids': [], 'cart': {}, 'cable': {}, 'activity_groups': {},
                'bridge': {'composed_mechanism_key': 'wheel', 'phase': {'start_event': 'start', 'end_event': 'end'}, 'minimum_support_callback_updates': 1}}
            cp = root/'contract.json';cp.write_text(json.dumps(contract))
            data = {'passed': True, 'root': root, 'run': run, 'spec': spec, 'case': case,
                'lock': {'physics_dt_s': 1/60}, 'integrity': {'case_sha256': 'c'*64}}
            reconstructed = [];received = []
            real_reader = f.p.contact_journal
            def reader(r, s):
                self.assertIs(r, run);self.assertIs(s, spec)
                value = real_reader(r, s);reconstructed.append(value);return value
            def simpler(*args, **kwargs):
                received.append(kwargs['_journal']);return {'passed': True}
            real_compose, real_bridge = f.composed.evaluate, f.bridge_support
            def compose(*args, **kwargs):
                received.append(kwargs['_journal']);return real_compose(*args, **kwargs)
            def bridge(*args, **kwargs):
                received.append(kwargs['_journal']);return real_bridge(*args, **kwargs)
            with ExitStack() as stack:
                for module, name, replacement in [(f.p, 'verify_run', lambda *a, **k: stock), (f.p, '_read_locked', lambda *a, **k: data),
                    (f, 'validate_contract', lambda *a: True), (f, 'sealed_identities', lambda *a: {}),
                    (f, 'static_stage_catalog', lambda *a: {'passed': True}), (f, 'mass_catalog', lambda *a: {'passed': True}),
                    (f, 'cable_no_bypass', lambda *a: {'passed': True}), (f, 'activity_breakdown', lambda *a: {}),
                    (f, 'non_contact_auxiliary_bodies', simpler), (f, 'cart_rolling', simpler),
                    (f.composed, 'evaluate', compose), (f, 'bridge_support', bridge), (f.p, 'contact_journal', reader)]:
                    stack.enter_context(patch.object(module, name, new=replacement))
                result = f.verify_one(root, cp, rp)
                self.assertTrue(result['passed'], result)
                self.assertEqual(len(reconstructed), 1);self.assertEqual(len(received), 4)
                self.assertTrue(all(value is reconstructed[0] for value in received))
                self.assertIs(result['stock'], stock);self.assertEqual(stock, original_stock)
                self.assertFalse(result['composed_mechanisms']['mechanisms']['wheel']['raw_p1_report']['passed'])
                # Missing early stock summary stays a durable failure; no
                # manufacture, later helper invocation or callback read.
                reconstructed.clear();received.clear();stock.pop('contact_journal')
                result = f.verify_one(root, cp, rp)
                self.assertFalse(result['passed']);self.assertFalse(result['original_contact_journal_reconstruction']['passed'])
                self.assertEqual(reconstructed, []);self.assertEqual(received, [])
                stock['contact_journal'] = stock_summary(real_journal);stock['contact_journal']['record_count'] += 1
                result = f.verify_one(root, cp, rp)
                self.assertFalse(result['passed']);self.assertEqual(len(reconstructed), 1);self.assertEqual(received, [])

    def test_only_file_orchestration_changed_not_existing_physical_functions(self):
        def functions(path):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(Path(path).read_text()).body if isinstance(n, ast.FunctionDef)}
        before, after = functions(old.__file__), functions(f.__file__)
        for name in before:
            if name != 'verify_one': self.assertEqual(before[name], after[name], name)


if __name__ == '__main__': unittest.main()
