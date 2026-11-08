import json
import tempfile
import unittest
from pathlib import Path
from experiments.pilot_usage import collect, normalize


class UsageTests(unittest.TestCase):
    def test_cache_and_reasoning_are_not_extra_total(self):
        v = normalize({'input_tokens': 1000, 'cached_input_tokens': 800, 'output_tokens': 100, 'reasoning_output_tokens': 70})
        self.assertEqual(v['total_tokens'], 1100)
        self.assertEqual(v['uncached_input_tokens'], 200)
        with self.assertRaises(ValueError):normalize({'input_tokens': 1, 'cached_input_tokens': 2, 'output_tokens': 0})

    def test_request_counter_dedup_and_cli_reconciliation(self):
        with tempfile.TemporaryDirectory() as d:
            e, s = Path(d)/'events', Path(d)/'session'
            one = {'input_tokens': 100, 'cached_input_tokens': 20, 'output_tokens': 10}
            total = {'input_tokens': 200, 'cached_input_tokens': 40, 'output_tokens': 20}
            e.write_text(json.dumps({'type': 'turn.completed', 'usage': total})+'\n')
            def record(c):return {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': c, 'last_token_usage': one, 'last_usage_includes_reasoning': True}}}
            s.write_text('\n'.join(json.dumps(record(v)) for v in (one, one, total))+'\n')
            v = collect(e, s)
            self.assertEqual(len(v['request_events']), 2)
            self.assertTrue(v['cli_and_request_counters_reconcile'])
            self.assertIsNone(v['request_events'][0]['request_id'])

    def test_missing_usage_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'empty'; p.write_text('{"type":"turn.failed"}\n')
            self.assertEqual(collect(p)['usage_availability'], 'unknown')
            self.assertIsNone(collect(p)['aggregate_reported_usage'])
