"""CPU fixtures for the two explicit SDK Base MDL module mappings."""
import tempfile
from pathlib import Path
import unittest
from simscene.mdl_snapshot import runtime_closure


class MdlRuntimeRootTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.package=self.root/'package';self.package.mkdir()
        self.sdk=self.root/'sdk';self.sdk.mkdir();self.launcher=self.sdk/'python.sh';self.launcher.write_text('not executed')
        self.core=self.sdk/'kit/mdl/core';self.base=self.core/'Base';self.base.mkdir(parents=True)
        (self.core/'mdl').mkdir()
        (self.base/'OmniPBR.mdl').write_text('mdl 1.7; import Helper::*; import ::df::*;')
        (self.base/'OmniGlass.mdl').write_text('mdl 1.7; using ::df import *;')
        (self.base/'Helper.mdl').write_text('mdl 1.7; export string texture="textures/fixture.png";')
        (self.base/'textures').mkdir();(self.base/'textures/fixture.png').write_bytes(b'original CPU fixture')
        (self.core/'mdl/df.mdl').write_text('mdl 1.7;')
        (self.package/'wrapper.mdl').write_text('mdl 1.7; using ::OmniPBR import OmniPBR; import ::OmniGlass::*;')
        self.files=[{'path':'wrapper.mdl'}]

    def test_known_absolute_base_modules_and_standard_transitive_closure(self):
        proof=runtime_closure(self.package,self.files,self.launcher)
        self.assertEqual(set(proof),{'kit/mdl/core/Base/OmniPBR.mdl','kit/mdl/core/Base/OmniGlass.mdl',
            'kit/mdl/core/Base/Helper.mdl','kit/mdl/core/Base/textures/fixture.png','kit/mdl/core/mdl/df.mdl'})
        original=proof['kit/mdl/core/Base/Helper.mdl']['sha256']
        (self.base/'Helper.mdl').write_text('mdl 1.7; // changed SDK module')
        changed=runtime_closure(self.package,self.files,self.launcher)
        self.assertNotEqual(changed['kit/mdl/core/Base/Helper.mdl']['sha256'],original)

    def test_supplied_runtime_must_be_exact_classifier_path(self):
        runtime={'OmniPBR.mdl':str(self.base/'OmniPBR.mdl')}
        self.assertTrue(runtime_closure(self.package,self.files,self.launcher,runtime))
        other=self.root/'OmniPBR.mdl';other.write_text('mdl 1.7;')
        for wrong in [{'OmniPBR.mdl':str(other)}, {'OmniPBR.mdl':str(self.base/'Helper.mdl')},
                      {'Custom.mdl':str(self.base/'Helper.mdl')}]:
            with self.subTest(runtime=wrong),self.assertRaises(ValueError):
                runtime_closure(self.package,self.files,self.launcher,wrong)

    def test_only_exact_known_names_use_base_no_custom_basename_search(self):
        (self.package/'wrapper.mdl').write_text('mdl 1.7; import ::Custom::*;')
        (self.base/'Custom.mdl').write_text('mdl 1.7;')
        with self.assertRaises(ValueError):runtime_closure(self.package,self.files,self.launcher)
        (self.core/'mdl/Custom.mdl').write_text('mdl 1.7;')
        proof=runtime_closure(self.package,self.files,self.launcher)
        self.assertEqual(set(proof),{'kit/mdl/core/mdl/Custom.mdl'})

    def test_missing_base_module_and_symlink_never_fall_back(self):
        (self.base/'OmniPBR.mdl').unlink()
        (self.core/'mdl/OmniPBR.mdl').write_text('mdl 1.7; // cannot substitute for Base')
        with self.assertRaises(ValueError):runtime_closure(self.package,self.files,self.launcher)
        outside=self.root/'outside.mdl';outside.write_text('mdl 1.7;')
        (self.base/'OmniPBR.mdl').symlink_to(outside)
        with self.assertRaises(ValueError):runtime_closure(self.package,self.files,self.launcher)

    def test_builtin_absolute_import_requires_explicit_launcher(self):
        with self.assertRaises(ValueError):runtime_closure(self.package,self.files)


if __name__=='__main__':unittest.main()
