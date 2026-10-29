"""Run local NVIDIA Surface Gripper sample, limiting rendering to one GPU."""
import os,sys
from pathlib import Path
source_path=Path(os.environ['SIMSCENE_ISAAC_ROOT'])/'standalone_examples/api/isaacsim.robot.surface_gripper/gripper_grasp.py'
source=source_path.read_text().replace('SimulationApp({"headless": args.headless or args.test})','SimulationApp({"headless": args.headless or args.test, "multi_gpu": False, "active_gpu": 0})')
sys.argv=[str(source_path),'--test']
exec(compile(source,str(source_path),'exec'),{'__name__':'__main__','__file__':str(source_path)})
