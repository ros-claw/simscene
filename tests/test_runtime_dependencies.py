import tempfile
import unittest
from pathlib import Path
from simscene.runtime_dependencies import classify

class RuntimeDependencyTest(unittest.TestCase):
    def test_only_known_installed_runtime_mdls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); base=root/'kit/mdl/core/Base'; base.mkdir(parents=True)
            (base/'OmniPBR.mdl').write_text('content')
            result=classify(['OmniPBR.mdl','OmniGlass.mdl','../OmniPBR.mdl'],str(root/'python.sh'))
            self.assertIn('OmniPBR.mdl',result['runtime_provided'])
            self.assertEqual(result['unresolved'],['OmniGlass.mdl','../OmniPBR.mdl'])
