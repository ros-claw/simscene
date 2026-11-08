"""Presentation-only one-token schema extension; source rows stay original."""
import copy,json,tempfile,unittest
from pathlib import Path
from experiments import plot_passive_activity_v5 as old,plot_passive_activity_v6 as new
from test_bounded_activity_plot_v4 import fixture
class BoundedActivityPlotV6Tests(unittest.TestCase):
 def test_exactly_one_schema_literal_is_the_complete_source_delta(self):
  a=Path(old.__file__).read_bytes();token=b"('simscene.bounded_entry_clock.v1', 'simscene.bounded_entry_clock.v2', 'simscene.bounded_entry_clock.v3', 'simscene.bounded_entry_clock.v4', 'simscene.bounded_entry_clock.v5')"
  self.assertEqual(a.count(token),1);self.assertEqual(Path(new.__file__).read_bytes(),a.replace(token,token[:-1]+b", 'simscene.bounded_entry_clock.v6')"))
 def test_original_rows_metrics_and_original_plot_rejection_are_retained(self):
  with tempfile.TemporaryDirectory() as tmp:
   report,lock,certificate,flags,metrics,value,_=fixture(Path(tmp));baseline=old.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
   value['schema']='simscene.bounded_entry_clock.v6';certificate.write_text(json.dumps(value));selected,measured,provenance=new.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
   self.assertEqual(baseline[:2],(selected,measured));self.assertTrue(all(a is b for a,b in zip(flags,selected)));self.assertNotIn('passed',provenance)
   with self.assertRaises(ValueError):old.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
 def test_every_original_completion_custody_and_prefix_guard_still_blocks(self):
  changes=['unknown_schema','foreign_report','foreign_lock','unverified','incomplete','no_entry','timing','escape','noncollapsed','mask_hash','window','metrics','changed_source','missing_step','prefix']
  for change in changes:
   with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
    report,lock,certificate,flags,metrics,value,_=fixture(Path(tmp));value['schema']='simscene.bounded_entry_clock.v6';timing=value['every_possible_original_prefix']
    if change=='unknown_schema':value['schema']='unknown'
    if change=='foreign_report':value['provenance']['independently_retained_full_report_sha256']='0'*64
    if change=='foreign_lock':value['provenance']['original_files_sha256']['run-lock.json']='0'*64
    if change=='unverified':value['file_integrity_verified']=False
    if change=='incomplete':value['supplemental_complete']=False
    if change=='no_entry':value['physical_entry_no_escape_complete']=False
    if change=='timing':value['bounded_timing_floors_passed']=False
    if change=='escape':value['inner_no_escape']=False
    if change=='noncollapsed':value['actual_first_entry_observed_step_bounds_inclusive'][1]+=1
    if change=='mask_hash':timing['original_full_masks_sha256']='0'*64
    if change=='window':timing['original_full_window'][1]-=1
    if change=='metrics':timing['prefixes'][0]['metrics']['net_effective_action_s']+=1/60
    if change=='changed_source':timing['source_flags_unchanged']=False
    if change=='missing_step':flags.pop(20)
    if change=='prefix':timing['prefixes'][0]['passed']=False
    certificate.write_text(json.dumps(value))
    with self.assertRaises(ValueError):new.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
if __name__=='__main__':unittest.main()
