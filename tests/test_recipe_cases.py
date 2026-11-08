from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from simscene.recipes.cases import freeze_case,freeze_case_file
from simscene.recipes.io import prepared_selection
from test_recipe_io import prepared,digest


class RecipeCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        manifest,acquired,binding=prepared(self.root/'package')
        self.bindings={'payload':binding}
        self.selections={'payload':prepared_selection(manifest,acquired,manifest_sha256=binding['asset_binding']['manifest_sha256'])}
        self.template={'schema':'fixture','prepared_manifest_sha256':'${payload.manifest_sha256}',
                       'source_ref':'${payload.source_ref}','objects':{'unchanged':[1,2,3]}}

    def test_new_pin_comes_from_actual_rebuild_and_original_template_stays_unchanged(self):
        original=deepcopy(self.template)
        result=freeze_case(self.template,self.bindings,self.selections)
        self.assertEqual(self.template,original)
        self.assertEqual(result['case']['prepared_manifest_sha256'],self.bindings['payload']['asset_binding']['manifest_sha256'])
        self.assertIsInstance(result['case']['source_ref'],dict)
        self.assertEqual(result['physical_verification'],'not_run')
        self.assertEqual(result['case']['objects'],self.template['objects'])

    def test_missing_unknown_old_frozen_case_and_changed_source_are_rejected(self):
        for template in ({'source_ref':'old','sha':'a'*64},{'x':'${payload.mass_kg}'},{'x':'${missing.source_ref}'},{'x':'prefix ${payload.source_ref}'}):
            with self.subTest(template=template),self.assertRaises(ValueError):freeze_case(template,self.bindings,self.selections)
        Path(self.bindings['payload']['asset_path']).write_text('tampered')
        with self.assertRaisesRegex(ValueError,'changed'):freeze_case(self.template,self.bindings,self.selections)

    def test_file_is_new_and_report_matches_exact_frozen_bytes(self):
        files={'template.json':self.template,'bindings.json':self.bindings,'lock.json':{'assets':self.selections}}
        for name,value in files.items():(self.root/name).write_text(json.dumps(value))
        result=freeze_case_file(self.root/'template.json',self.root/'bindings.json',self.root/'lock.json',self.root/'frozen.json')
        self.assertEqual(result['case_sha256'],digest(self.root/'frozen.json'))
        self.assertEqual(result['template_sha256'],digest(self.root/'template.json'))
        with self.assertRaises(FileExistsError):freeze_case_file(self.root/'template.json',self.root/'bindings.json',self.root/'lock.json',self.root/'frozen.json')


if __name__=='__main__':unittest.main()
