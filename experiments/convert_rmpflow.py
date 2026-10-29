"""Run the packaged robot profile utility from a source checkout."""
import runpy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
runpy.run_module("simscene.robotics.profile_scripts.convert_rmpflow", run_name="__main__")
