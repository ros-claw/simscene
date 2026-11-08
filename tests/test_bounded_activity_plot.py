"""Synthetic presentation authority/interval checks; no physics acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.plot_passive_activity import bounded_prefix, sha


def fixture(root):
    report, lock, certificate = [root/name for name in ('report.json', 'run-lock.json', 'certificate.json')]
    report.write_text('{"synthetic_report_identity_only":true}\n')
    lock.write_text('{"synthetic_lock_identity_only":true}\n')
    flags = [{'physics_step':s, 'simulation_time_s':s/60, 'active':s % 31 != 0,
              'body_ids':['cart'] if s % 31 else [], 'stage_ids':['cart_phase'] if s % 31 else []}
             for s in range(601, 5801)]
    metrics = {'window_start_step':600, 'window_end_step':5800}
    selected = flags[:-2]
    measured = {'chain_duration_s':5198/60, 'net_effective_action_s':sum(r['active'] for r in selected)/60,
                'motion_occupancy':sum(r['active'] for r in selected)/len(selected), 'maximum_idle_s':1/60}
    value = {'schema':'simscene.bounded_entry_clock.v1', 'file_integrity_verified':True,
             'supplemental_complete':True, 'physical_entry_no_escape_complete':True,
             'bounded_timing_floors_passed':True, 'inner_no_escape':True,
             'provenance':{'independently_retained_full_report_sha256':sha(report),
                           'original_files_sha256':{'run-lock.json':sha(lock)}},
             'actual_first_entry_observed_step_bounds_inclusive':[5798,5798],
             'every_possible_original_prefix':{'original_full_masks_sha256':hashlib.sha256(json.dumps(flags,
                 sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
                 'original_full_window':[600,5800], 'source_flags_unchanged':True,
                 'prefixes':[{'end_boundary_step':5798,'interval_start_inclusive':600,
                     'interval_end_exclusive':5798,'passed':True,'checks':{'all_floors':True},'metrics':measured}]}}
    certificate.write_text(json.dumps(value))
    return report, lock, certificate, flags, metrics, value, measured


class BoundedActivityPlotTest(unittest.TestCase):
    def test_explicit_v2_certificate_keeps_the_same_prefix_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, lock, certificate, flags, metrics, value, _ = fixture(Path(tmp))
            old = bounded_prefix(flags,metrics,report,lock,1/60,certificate)
            value['schema']='simscene.bounded_entry_clock.v2'
            certificate.write_text(json.dumps(value))
            new = bounded_prefix(flags,metrics,report,lock,1/60,certificate)
            self.assertEqual(old[:2],new[:2])

    def test_uses_only_original_prefix_without_mutating_source_or_inventing_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, lock, certificate, flags, metrics, _, expected = fixture(Path(tmp))
            before = copy.deepcopy((flags, metrics)); files = [p.read_bytes() for p in (report, lock, certificate)]
            selected, measured, provenance = bounded_prefix(flags, metrics, report, lock, 1/60, certificate)
            self.assertEqual([r['physics_step'] for r in selected], list(range(601,5799)))
            self.assertTrue(all(a is b for a,b in zip(selected,flags)))
            for key,value in expected.items():self.assertAlmostEqual(measured[key],value,places=10)
            self.assertEqual(measured['window_end_step'],5798)
            self.assertEqual(provenance['original_stock_window_end_step'],5800)
            self.assertNotIn('passed',provenance)
            self.assertEqual((flags,metrics),before)
            self.assertEqual([p.read_bytes() for p in (report,lock,certificate)],files)

    def test_foreign_incomplete_noncollapsed_or_changed_mask_clock_is_rejected(self):
        for mutation in ('schema','foreign_report','unverified','noncollapsed','mask_hash','window','metrics'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as tmp:
                report, lock, certificate, flags, metrics, value, _ = fixture(Path(tmp))
                if mutation=='schema':value['schema']='simscene.bounded_entry_clock.unknown'
                if mutation=='foreign_report':value['provenance']['independently_retained_full_report_sha256']='0'*64
                if mutation=='unverified':value['file_integrity_verified']=False
                if mutation=='noncollapsed':value['actual_first_entry_observed_step_bounds_inclusive'][1]+=1
                if mutation=='mask_hash':value['every_possible_original_prefix']['original_full_masks_sha256']='0'*64
                if mutation=='window':value['every_possible_original_prefix']['original_full_window'][1]-=1
                if mutation=='metrics':value['every_possible_original_prefix']['prefixes'][0]['metrics']['net_effective_action_s']+=1/60
                certificate.write_text(json.dumps(value))
                with self.assertRaises(ValueError):bounded_prefix(flags,metrics,report,lock,1/60,certificate)
