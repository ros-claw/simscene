"""Additive clock-v3 presentation reader; no new physics or activity credit."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from experiments.plot_passive_activity import bounded_prefix as old_prefix
from experiments.plot_passive_activity_v3 import bounded_prefix
_fixture_spec = importlib.util.spec_from_file_location(
    'old_bounded_activity_plot_fixture', Path(__file__).with_name('test_bounded_activity_plot.py'))
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
fixture = _fixture_module.fixture


class BoundedActivityPlotV3Test(unittest.TestCase):
    def test_only_the_explicit_schema_admission_differs_from_frozen_plot_v2(self):
        root = Path(__file__).resolve().parents[1]
        old = (root / 'experiments/plot_passive_activity.py').read_bytes()
        new = (root / 'experiments/plot_passive_activity_v3.py').read_bytes()
        self.assertEqual(hashlib.sha256(old).hexdigest(), '79b90a8b878e46c04d5c335ec73285cb888119a92f7fdc2b5d1cab0d5d9ef586')
        before = b"('simscene.bounded_entry_clock.v1', 'simscene.bounded_entry_clock.v2')"
        after = b"('simscene.bounded_entry_clock.v1', 'simscene.bounded_entry_clock.v2', 'simscene.bounded_entry_clock.v3')"
        self.assertEqual(old.count(before), 1)
        self.assertEqual(new, old.replace(before, after))

    def test_v3_selects_exactly_the_same_original_rows_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, lock, certificate, flags, metrics, value, _ = fixture(Path(tmp))
            original = old_prefix(flags, metrics, report, lock, 1/60, certificate)
            value['schema'] = 'simscene.bounded_entry_clock.v3'
            certificate.write_text(json.dumps(value))
            selected, measured, provenance = bounded_prefix(flags, metrics, report, lock, 1/60, certificate)
            self.assertEqual(original[:2], (selected, measured))
            self.assertTrue(all(a is b for a, b in zip(flags, selected)))
            self.assertNotIn('passed', provenance)
            with self.assertRaises(ValueError):
                old_prefix(flags, metrics, report, lock, 1/60, certificate)

    def test_v3_keeps_all_original_custody_completion_and_clock_guards(self):
        mutations = ('unknown_schema', 'foreign_report', 'foreign_lock', 'unverified',
                     'incomplete', 'no_physical_entry', 'failed_timing', 'escape',
                     'noncollapsed', 'mask_hash', 'window', 'metrics', 'source_changed',
                     'missing_step', 'false_prefix')
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                report, lock, certificate, flags, metrics, value, _ = fixture(Path(tmp))
                value['schema'] = 'simscene.bounded_entry_clock.v3'
                if mutation == 'unknown_schema': value['schema'] = 'simscene.bounded_entry_clock.unknown'
                if mutation == 'foreign_report': value['provenance']['independently_retained_full_report_sha256'] = '0'*64
                if mutation == 'foreign_lock': value['provenance']['original_files_sha256']['run-lock.json'] = '0'*64
                if mutation == 'unverified': value['file_integrity_verified'] = False
                if mutation == 'incomplete': value['supplemental_complete'] = False
                if mutation == 'no_physical_entry': value['physical_entry_no_escape_complete'] = False
                if mutation == 'failed_timing': value['bounded_timing_floors_passed'] = False
                if mutation == 'escape': value['inner_no_escape'] = False
                if mutation == 'noncollapsed': value['actual_first_entry_observed_step_bounds_inclusive'][1] += 1
                if mutation == 'mask_hash': value['every_possible_original_prefix']['original_full_masks_sha256'] = '0'*64
                if mutation == 'window': value['every_possible_original_prefix']['original_full_window'][1] -= 1
                if mutation == 'metrics': value['every_possible_original_prefix']['prefixes'][0]['metrics']['net_effective_action_s'] += 1/60
                if mutation == 'source_changed': value['every_possible_original_prefix']['source_flags_unchanged'] = False
                if mutation == 'missing_step': flags.pop(20)
                if mutation == 'false_prefix': value['every_possible_original_prefix']['prefixes'][0]['passed'] = False
                certificate.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    bounded_prefix(flags, metrics, report, lock, 1/60, certificate)
