import unittest
from types import SimpleNamespace
from simscene.worker.overlap_diagnostics import OverlapDiagnostics


class OverlapTest(unittest.TestCase):
    def test_records_hits_and_marks_missing_self_and_skipped_steps(self):
        class Query:
            def overlap_shape(self,a,b,report,any_hit):
                if a==1:report(SimpleNamespace(rigid_body='/robot/body',collision='/robot/shape'))
                report(SimpleNamespace(rigid_body='/world',collision='/world/table'))
        shapes=[{'path':'/robot/shape','body':'/robot/body','type':'Mesh'},
                {'path':'/robot/uncovered','body':'/robot/other','type':'Mesh'}]
        monitor=OverlapDiagnostics(shapes,Query(),lambda p:(1 if p.endswith('shape') else 2,0))
        monitor.sample(0);monitor.sample(2)
        summary=monitor.summary()
        self.assertEqual(summary['step_gaps'],1)
        self.assertEqual(summary['missing_self_hits']['/robot/uncovered'],2)
        self.assertEqual(monitor.counts['/robot/shape|/world/table']['count'],2)
        self.assertFalse(summary['truncated'])

    def test_pair_limit_and_query_errors_are_explicit(self):
        class Query:
            def overlap_shape(self,a,b,report,any_hit):
                if a==2:raise RuntimeError('query failed')
                report(SimpleNamespace(rigid_body='different',collision='other'))
        shapes=[{'path':'one','body':'body','type':'Mesh'},{'path':'two','body':'body','type':'Mesh'}]
        monitor=OverlapDiagnostics(shapes,Query(),lambda p:(1 if p=='one' else 2,0),max_pairs=0)
        monitor.sample(0)
        self.assertTrue(monitor.summary()['truncated'])
        self.assertEqual(monitor.summary()['error_count'],1)

    def test_spawned_and_removed_shapes_keep_history_without_unrelated_pairs(self):
        class Query:
            def overlap_shape(self,a,b,report,any_hit):
                report(SimpleNamespace(rigid_body='body'+str(a),collision='shape'+str(a)))
                report(SimpleNamespace(rigid_body='body3',collision='shape3'))
        initial=[{'path':'shape1','body':'body1','type':'Mesh'}]
        monitor=OverlapDiagnostics(initial,Query(),lambda p:(int(p[-1]),0),robot_prefixes=['shape2'])
        monitor.add({'path':'shape2','body':'body2','type':'Cube'});monitor.sample(1);monitor.remove('shape2')
        self.assertEqual(len(monitor.summary()['shapes']),2)
        self.assertEqual(monitor.summary()['active_shape_count'],1)
        self.assertNotIn('shape1|shape3',monitor.counts)
        self.assertIn('shape2|shape3',monitor.counts)
