import unittest
from experiments.verify_chain_suite import physical_objects

class ChainSuiteInputTest(unittest.TestCase):
    def test_snapshot_location_does_not_change_physical_identity(self):
        specs=[]
        for run in ('run-a','run-b'):
            specs.append({'objects':{'table':{'kind':'asset','position':[1,2,3],'asset_path':'/'+run+'/assets/sha/root.usd','asset_physics':'visual_only'}},'_checker_asset_identities':{'table':{'source':'https://example.test/table.usd','package_sha256':'sha','root_relative_to_run':'assets/sha/root.usd'}}})
        self.assertEqual(physical_objects(specs[0]),physical_objects(specs[1]))
        specs[1]['objects']['table']['position'][2]+=.15
        self.assertNotEqual(physical_objects(specs[0]),physical_objects(specs[1]))

    def test_unverified_asset_identity_is_rejected(self):
        with self.assertRaises(ValueError):physical_objects({'objects':{'table':{'kind':'asset','asset_path':'unverified.usd'}}})
