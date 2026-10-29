"""The route checker binds reviewed asset identities to run snapshots."""
import ast
from pathlib import Path
import tempfile
import unittest


class RouteAssetSnapshotTests(unittest.TestCase):
    def test_reviewed_source_requires_matching_intact_snapshot(self):
        source = Path(__file__).resolve().parents[2]/'experiments/verify_agent_route_edit.py'
        tree = ast.parse(source.read_text())
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == 'matches_reviewed_asset')
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            target = directory/'assets'/'digest'/'origin'/'franka.usd'
            target.parent.mkdir(parents=True)
            target.write_text('#usda 1.0\n')
            suffix = '/FrankaRobotics/FrankaPanda/franka.usd'
            entry = {'kind': 'snapshot', 'source': 'https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.2/Isaac/Robots'+suffix,
                     'root_relative_to_run': str(target.relative_to(directory))}
            namespace = {'assets': {'panda': entry}, 'directory': directory,
                         'checks': {'input_integrity': True}, 'Path': Path}
            exec(compile(module, str(source), 'exec'), namespace)
            matches = namespace['matches_reviewed_asset']
            self.assertTrue(matches('panda', {'asset_path': str(target)}, suffix))
            self.assertFalse(matches('panda', {'asset_path': str(directory/'other.usd')}, suffix))
            namespace['checks']['input_integrity'] = False
            self.assertFalse(matches('panda', {'asset_path': str(target)}, suffix))
            namespace['checks']['input_integrity'] = True
            entry['source'] = entry['source'].replace('omniverse-content-production.s3-us-west-2.amazonaws.com', 'example.org')
            self.assertFalse(matches('panda', {'asset_path': str(target)}, suffix))


if __name__ == '__main__':
    unittest.main()
