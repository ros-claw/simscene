"""Historical worktop evidence is a geometric prefilter for a new placement."""
import asyncio
import json
import math
import unittest


def observation(asset_id, extent, *, passed=True, direct=True, settled=True):
    return {
        'source_ref': {'source_id': 'gso-glb', 'asset_id': asset_id,
                       'revision': 'a'*40, 'variant_id': None},
        'physics_passed': passed,
        'footprint': {'centered_xy_envelope_m': extent},
        'support': {'kind': 'horizontal_static_primitive_box',
                    'direct_worktop_contact': direct, 'settled': settled},
    }


class WorktopFitTests(unittest.TestCase):
    def test_uses_axis_dimensions_and_edge_margin(self):
        from simscene.recipes.worktop_fit import filter_observations

        options = [observation('small', [.11, .08]), observation('too_deep', [.10, .16]),
                   observation('too_wide', [.19, .06]), observation('no_contact', [.05, .05], direct=False),
                   observation('unstable', [.05, .05], settled=False),
                   observation('failed_case', [.05, .05], passed=False)]
        result = filter_observations(options, width_m=.22, depth_m=.18, edge_clearance_m=.02)
        self.assertEqual([entry['source_ref']['asset_id'] for entry in result['matches']], ['small'])
        self.assertEqual(result['matches'][0]['minimum_worktop_xy_m'], [.15, .12])
        boundary = filter_observations(options[:1], width_m=.15, depth_m=.12, edge_clearance_m=.02)
        self.assertEqual(len(boundary['matches']), 1)
        rounded = [observation('decimal_boundary', [.10, .10])]
        fit = filter_observations(rounded, width_m=.30, depth_m=.30, edge_clearance_m=.10)
        self.assertEqual(len(fit['matches']), 1)
        too_small = filter_observations(rounded, width_m=.299999, depth_m=.30, edge_clearance_m=.10)
        self.assertEqual(too_small['matches'], [])
        exact = filter_observations(rounded, width_m=math.nextafter(.10, 0), depth_m=.10,
                                    edge_clearance_m=0)
        self.assertEqual(exact['matches'], [])
        self.assertEqual([item['reason'] for item in result['excluded']],
                         ['insufficient_worktop_xy', 'insufficient_worktop_xy',
                          'no_verified_support_result', 'no_verified_support_result',
                          'no_verified_support_result'])

    def test_preserves_pose_and_rejects_invalid_dimensions(self):
        from simscene.recipes.worktop_fit import filter_observations

        option = observation('fixed_pose', [.20, .12])
        fit = filter_observations([option], width_m=.14, depth_m=.22, edge_clearance_m=0)
        self.assertEqual(fit['matches'], [])
        self.assertEqual(fit['excluded'][0]['reason'], 'insufficient_worktop_xy')
        for width, depth, edge in ((0, .5, .01), (.5, math.inf, .01), (True, .5, .01),
                                   (.5, .5, -.01), (.5, .5, math.nan)):
            with self.subTest(width=width, depth=depth, edge=edge), self.assertRaises(ValueError):
                filter_observations([option], width_m=width, depth_m=depth, edge_clearance_m=edge)

    def test_resource_template_calls_real_filter(self):
        from simscene.mcp_server import server

        templates = asyncio.run(server.list_resource_templates())
        self.assertIn('simscene://recipes/worktop-fit/{width_m}/{depth_m}/{edge_clearance_m}',
                      {str(template.uriTemplate) for template in templates})
        contents = asyncio.run(server.read_resource('simscene://recipes/worktop-fit/0.66/0.50/0.02'))
        result = json.loads(next(iter(contents)).content)
        by_source = {row['source_ref']['asset_id'] for row in result['matches']}
        baseline = 'ReadytoUse_Rolled_Fondant_Pure_White_24_oz_box'
        self.assertEqual(by_source, {
            baseline, 'B01DN8TB5U', 'Crunch_Girl_Scouts_Candy_Bars_Peanut_Butter_Creme_78_oz_box',
        })
        narrow = asyncio.run(server.read_resource('simscene://recipes/worktop-fit/0.30/0.24/0.02'))
        narrow = json.loads(next(iter(narrow)).content)
        self.assertEqual({row['source_ref']['asset_id'] for row in narrow['matches']},
                         by_source - {baseline})
        self.assertEqual(result['support_kind'], 'horizontal_static_primitive_box')
        self.assertIn('new run', result['scope'])
