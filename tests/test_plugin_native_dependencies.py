import subprocess,sys,tempfile,unittest
from pathlib import Path
from plugins.build import copy_installed_dependencies
class PluginNativeDependenciesTest(unittest.TestCase):
 def test_portable_image_dependency_loads_in_isolated_interpreter(self):
  # This exercises the real installed wheel records and its private .libs;
  # importing PIL in the builder process alone cannot detect missing vendored
  # libraries or a stale distribution version mixed with another extension.
  with tempfile.TemporaryDirectory() as directory:
   vendor=Path(directory);versions=copy_installed_dependencies(vendor)
   import PIL
   self.assertEqual(next(v for k,v in versions.items() if k.lower()=='pillow'),PIL.__version__)
   script='import sys,io;sys.path.insert(0,sys.argv[1]);from PIL import Image;b=io.BytesIO();Image.new("RGB",(4,4),(10,20,30)).save(b,format="PNG");b.seek(0);assert Image.open(b).size==(4,4);b=io.BytesIO();Image.new("RGB",(4,4)).save(b,format="JPEG");b.seek(0);assert Image.open(b).format=="JPEG"'
   subprocess.run([sys.executable,'-I','-c',script,str(vendor)],check=True)
