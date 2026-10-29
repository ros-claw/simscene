import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plugins.install import install


def package_at(root):
    root = Path(root)
    for path in ('plugin.json','mcp.json','server/launch.py','server/vendor/simscene/__init__.py','skills/build-scene/SKILL.md'):
        target=root/path; target.parent.mkdir(parents=True,exist_ok=True);target.write_text('test')
    return root


class InstallerTest(unittest.TestCase):
    def test_files_and_project_skill_are_installed_without_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); package=package_at(base/'package');project=base/'project';project.mkdir()
            result=install(package,base/'installed',project=project)
            self.assertTrue(result['package_installed']);self.assertFalse(result['codex_mcp_registered'])
            self.assertFalse(result['native_plugin_installed'])
            self.assertTrue((project/'.agents/skills/build-scene/SKILL.md').is_file())
            with self.assertRaises(FileExistsError):install(package,base/'installed',project=project)

    def test_existing_skill_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);package=package_at(base/'package');project=base/'project';skill=project/'.agents/skills/build-scene';skill.mkdir(parents=True);(skill/'SKILL.md').write_text('original')
            with self.assertRaises(FileExistsError):install(package,base/'installed',project=project)
            self.assertEqual((skill/'SKILL.md').read_text(),'original');self.assertFalse((base/'installed').exists())

    def test_conflicting_registration_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); package=package_at(base/'package')
            with patch('plugins.install.subprocess.run') as run:
                run.return_value.stdout=json.dumps([{'name':'simscene'}])
                with self.assertRaises(FileExistsError):install(package,base/'installed',register_codex=True)
            self.assertFalse((base/'installed').exists())

    def test_source_and_destination_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            package=package_at(Path(temp)/'package')
            with self.assertRaises(ValueError):install(package,package/'copy')

    def test_dangling_destination_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);package=package_at(base/'package');link=base/'link';link.symlink_to(base/'other')
            with self.assertRaises(FileExistsError):install(package,link)
            self.assertFalse((base/'other').exists())
