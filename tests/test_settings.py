import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from simscene.settings import update,get,config_path
class SettingsTest(unittest.TestCase):
    def test_persisted_defaults_and_environment_override(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CONFIG_HOME':directory},clear=True):
            root=Path(directory);runtime=root/'python.sh';runtime.write_text('test')
            result=update({'isaac_python':str(runtime),'cache_bytes':12345,'usd_search_url':'https://example.test'})
            self.assertEqual(result['status'],'configured_not_registered_or_installed')
            self.assertEqual(get('isaac_python'),str(runtime));self.assertEqual(get('cache_bytes'),12345)
            self.assertEqual(config_path().stat().st_mode & 0o777,0o600)
            with patch.dict(os.environ,{'SIMSCENE_ISAAC_PYTHON':'/override'}):self.assertEqual(get('isaac_python'),'/override')
            self.assertNotIn('token',json.dumps(result).lower())
    def test_rejects_credentials_and_nonpositive_capacity(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CONFIG_HOME':directory},clear=True):
            with self.assertRaises(ValueError):update({'usd_search_url':'https://user:secret@example.test'})
            with self.assertRaises(ValueError):update({'cache_bytes':0})
            self.assertFalse(config_path().exists())
