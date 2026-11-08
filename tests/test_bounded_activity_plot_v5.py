"""Version admission for presentation only; no extra physical/action credit."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments import plot_passive_activity_v4 as old, plot_passive_activity_v5 as new
from test_bounded_activity_plot_v4 import fixture


class BoundedActivityPlotV5Test(unittest.TestCase):
    def test_source_delta_is_only_one_explicit_certificate_schema(self):
        before=Path(old.__file__).read_bytes()
        token=b"('simscene.bounded_entry_clock.v1', 'simscene.bounded_entry_clock.v2', 'simscene.bounded_entry_clock.v3', 'simscene.bounded_entry_clock.v4')"
        self.assertEqual(before.count(token),1)
        self.assertEqual(Path(new.__file__).read_bytes(),before.replace(token,token[:-1]+b", 'simscene.bounded_entry_clock.v5')"))

    def test_original_rows_metrics_and_provenance_guards_survive_new_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,lock,certificate,flags,metrics,value,_=fixture(Path(tmp))
            baseline=old.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
            value['schema']='simscene.bounded_entry_clock.v5';certificate.write_text(json.dumps(value))
            selected,measured,provenance=new.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
            self.assertEqual(baseline[:2],(selected,measured))
            self.assertTrue(all(a is b for a,b in zip(flags,selected)))
            self.assertNotIn('passed',provenance)
            with self.assertRaises(ValueError):old.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
            value['inner_no_escape']=False;certificate.write_text(json.dumps(value))
            with self.assertRaises(ValueError):new.bounded_prefix(flags,metrics,report,lock,1/60,certificate)
