"""Packaging identity and parallel installer contracts; no global registration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugins.build import build, versions, PYTHON_VERSION, PACKAGE_VERSION
from plugins.install import install


class PackagingContractTests(unittest.TestCase):
    def test_version_mapping_has_one_project_source(self):
        self.assertEqual((PYTHON_VERSION,PACKAGE_VERSION),('0.2.0.dev1','0.2.0-dev.1'))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for python,plugin in [('0.3.0.dev12','0.3.0-dev.12'),('0.3.0','0.3.0')]:
                (root/'pyproject.toml').write_text('[project]\nversion = "'+python+'"\n')
                self.assertEqual(versions(root),(python,plugin))
            (root/'pyproject.toml').write_text('[project]\nversion = "0.3.0rc1"\n')
            with self.assertRaises(ValueError):versions(root)

    def package(self,root):
        for name in ('plugin.json','mcp.json','server/launch.py','server/vendor/simscene/__init__.py','skills/build-scene/SKILL.md'):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
        return root

    def test_parallel_mcp_name_add_and_exact_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);package=self.package(root/'package');destination=root/'installed';calls=[]
            def command(args,**kwargs):
                calls.append(args)
                if args[2]=='list':value=[{'name':'simscene'}]
                elif args[2]=='get':
                    added=calls[-2];separator=added.index('--')
                    value={'name':'simscene-v2','transport':{'type':'stdio','command':added[separator+1],'args':[str(destination/'server/launch.py')]}}
                else:value={}
                from types import SimpleNamespace
                return SimpleNamespace(stdout=json.dumps(value))
            with patch('plugins.install.subprocess.run',side_effect=command):
                result=install(package,destination,register_codex=True,mcp_name='simscene-v2')
            self.assertTrue(result['codex_mcp_registered']);self.assertEqual(result['mcp_name'],'simscene-v2')
            self.assertEqual(calls[1][2:4],['add','simscene-v2'])
            self.assertEqual(calls[2][2:4],['get','simscene-v2'])

    def test_existing_parallel_registration_and_invalid_name_refuse_before_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);package=self.package(root/'package');destination=root/'installed'
            with patch('plugins.install.subprocess.run') as run:
                run.return_value.stdout=json.dumps([{'name':'simscene-v2'}])
                with self.assertRaises(FileExistsError):install(package,destination,register_codex=True,mcp_name='simscene-v2')
            with self.assertRaises(ValueError):install(package,destination,mcp_name='../bad')
            self.assertFalse(destination.exists())

    def test_build_refuses_existing_or_dangling_symlink_before_subprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);link=root/'link';link.symlink_to(root/'absent')
            with patch('plugins.build.subprocess.run') as run:
                for destination in (root,link):
                    with self.assertRaises(FileExistsError):build(destination)
                run.assert_not_called()
