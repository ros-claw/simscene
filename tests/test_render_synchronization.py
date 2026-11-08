"""Render receipts cannot substitute nominal cadence for physical synchronization."""
from copy import deepcopy
import unittest
from simscene.video_tools import render_synchronization


class RenderSynchronizationTest(unittest.TestCase):
    def rows(self):
        return [{'physics_step':step,'render_context':{'absolute_physics_step':step+3,
            'render_barrier':{'policy':'paused-render-barrier-v1','application_updates':2,
                'absolute_physics_step':step+3,'absolute_simulation_time_s':(step+3)/60,
                'physics_unchanged':True}}} for step in (2,4,6)]

    def test_complete_same_state_receipts_are_distinct_from_legacy_clock(self):
        self.assertEqual(render_synchronization(self.rows())['status'],'guarded')
        self.assertEqual(render_synchronization([{'physics_step':2}])['status'],'unrecorded')

    def test_partial_or_inconsistent_receipts_fail(self):
        original=self.rows()
        for key,value in [('absolute_physics_step',999),('absolute_simulation_time_s',100),
                          ('physics_unchanged',False),('application_updates',True),('policy','unknown')]:
            rows=deepcopy(original);rows[1]['render_context']['render_barrier'][key]=value
            with self.subTest(key=key):
                self.assertEqual(render_synchronization(rows)['status'],'invalid')
        rows=deepcopy(original);del rows[1]['render_context']['render_barrier']
        self.assertEqual(render_synchronization(rows)['status'],'invalid')
