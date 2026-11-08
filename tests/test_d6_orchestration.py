"""CPU parity of explicit source versions; no measured house acceptance."""
import ast
import copy
import hashlib
from pathlib import Path
import unittest

from experiments import composed_event_mechanisms as c1, composed_event_mechanisms_v2 as c2
from experiments import whole_home_fidelity_v7 as f7, whole_home_fidelity_v8 as f8
from experiments import whole_home_suite_v7 as s7, whole_home_suite_v8 as s8
from experiments import box_halfspace_observation_v2 as h2, box_halfspace_observation_v3 as h3
from experiments import bounded_entry_clock_v4 as k4, bounded_entry_clock_v5 as k5
from experiments import retained_report_integrity_v2 as retained
from experiments import retained_whole_home_suite_v2 as aggregate


class ExplicitD6OrchestrationTest(unittest.TestCase):
    def test_all_unchanged_numerical_functions_have_identical_ast(self):
        def functions(module):
            return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(Path(module.__file__).read_text()).body if isinstance(n,ast.FunctionDef)}
        for before,after,changed in ((c1,c2,set()),(f7,f8,{'assert_kernel','assert_software_freeze','validate_floors'}),
                (s7,s8,set()),(h2,h3,set()),(k4,k5,{'evaluate','reduced_report','verify'})):
            old,new=functions(before),functions(after)
            self.assertEqual(set(old),set(new))
            for name in old.keys()-changed:
                with self.subTest(module=after.__name__,function=name):self.assertEqual(old[name],new[name])
        self.assertEqual(c2.BASE_CHECKS,c1.BASE_CHECKS|{'declared_D6_loaded_modes_and_same_sample_frames'})
        self.assertEqual(c1.PHYSICAL_CHECKS,c2.PHYSICAL_CHECKS)
        self.assertEqual(k4.LIMIT_KEYS,k5.LIMIT_KEYS)

    def test_source_dependencies_are_pinned_and_original_freeze_is_not_reused(self):
        f8.assert_kernel();k5.assert_dependencies();retained.assert_dependencies();aggregate.assert_dependencies()
        self.assertEqual(f8.ORCHESTRATION_VERSION,8)
        self.assertNotEqual(f8.SOFTWARE_FREEZE_SHA256,f7.SOFTWARE_FREEZE_SHA256)
        self.assertNotEqual(k5.SCHEMA,k4.SCHEMA)
        self.assertNotEqual(h3.SCHEMA,h2.SCHEMA)
        original=Path('/code/rosclaw/simscene/evidence/whole-room-sugar-20261031/generic-freeze/v41-software.json')
        if original.is_file():
            with self.assertRaises(ValueError):f8.assert_software_freeze(original)

    def test_complete_raw_mechanism_reports_retain_every_original_predicate(self):
        from test_composed_event_mechanisms import fixture
        inputs=fixture();unchanged=copy.deepcopy(inputs)
        old=c1.evaluate(*inputs,1/60);new=c2.evaluate(*inputs,1/60)
        self.assertTrue(new['passed'],new)
        new['schema']=old['schema'];new['source_kernels_sha256']=old['source_kernels_sha256']
        for component in new['mechanisms'].values():
            self.assertTrue(component['raw_p1_report']['checks'].pop('declared_D6_loaded_modes_and_same_sample_frames'))
        self.assertEqual(new,old)
        self.assertEqual(inputs,unchanged)

    def test_halfspace_geometry_is_identical_including_earliest_entry_and_escape(self):
        from test_box_halfspace_observation_v2 import fixture
        for centers in (None,[[2,0,0],[0,0,0],[2,0,0],[0,0,0]]):
            run,spec,contract,_=fixture(centers=centers)
            old=h2.evaluate(run,spec,contract)
            new=h3.evaluate(run,spec,{**contract,'schema':h3.SCHEMA})
            new['schema']=old['schema'];new['helper_sha256']=old['helper_sha256']
            self.assertEqual(new,old)

    def test_clock_preserves_union_prefix_floors_and_never_hides_escape_or_missing_step(self):
        from test_bounded_entry_clock_v4 import fixture
        for collapsed in (True,False):
            run,spec,case,stock,inner,outer,contract=fixture(collapsed=collapsed)
            old=k4.evaluate(run,spec,case,stock,inner,outer,contract)
            new=k5.evaluate(run,spec,case,stock,{**inner,'schema':h3.SCHEMA},{**outer,'schema':h3.SCHEMA},{**contract,'schema':k5.SCHEMA})
            new['schema']=old['schema']
            if 'stability_authority' in new:new['stability_authority']=old['stability_authority']
            self.assertEqual(new,old)
            first,last=old['actual_first_entry_observed_step_bounds_inclusive']
            dt=contract['physics_dt_s']
            self.assertEqual(k4.prefixes(stock,case,first,last,dt),k5.prefixes(stock,case,first,last,dt))
            missing=copy.deepcopy(stock);missing['activity']['per_step_motion_flags'].pop(10)
            with self.assertRaises(ValueError):k5.prefixes(missing,case,first,last,dt)
            loose=copy.deepcopy(case);loose['activity']['limits']['minimum_net_effective_action_s']=44
            with self.assertRaises(ValueError):k5.prepare({**contract,'schema':k5.SCHEMA,'limits':loose['activity']['limits']},{**inner,'schema':h3.SCHEMA},{**outer,'schema':h3.SCHEMA},spec,loose)
