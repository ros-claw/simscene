"""Queue a private 6.2 Python-server health and live-stage probe.

The code editor is deliberately loopback-only and is shut down after the
probe. It is not the network transport for SimScene's MCP service.
"""
import json,os,signal,socket,subprocess,sys,time
from pathlib import Path
root=Path('/tmp/simscene-isaac62-remote-probe');root.mkdir(parents=True,exist_ok=True)
isaac=Path('/data/omniverse/isaac-sim-6.2.0');scripts=isaac/'skills/isaac-sim-remote/scripts'
with socket.socket() as sock:
 sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
cmd=[str(isaac/'isaac-sim.sh'),'--no-window','--no-ros-env','--enable','isaacsim.code_editor.python_server',f'--/exts/isaacsim.code_editor.python_server/port={port}','--/renderer/multiGpu/enabled=false']
(root/'launch.json').write_text(json.dumps({'command':cmd,'port':port,'scope':'local trusted developer IPC only'},indent=2)+'\n')
process=None
with (root/'kit.log').open('w') as log:
 try:
  process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=str(isaac),env=os.environ.copy())
  deadline=time.monotonic()+180
  while time.monotonic()<deadline:
   if process.poll() is not None:raise RuntimeError(f'Isaac exited before server startup: {process.returncode}')
   text=(root/'kit.log').read_text(errors='replace')
   if 'app ready' in text.lower():
    try:
     with socket.create_connection(('127.0.0.1',port),timeout=1):break
    except OSError:pass
   time.sleep(2)
  else:raise RuntimeError('timed out waiting for Isaac app and local server')
  def send(name,*args):
   run=subprocess.run([sys.executable,str(scripts/'isaacsim_send.py'),'--port',str(port),'--timeout','90','--raw',*args],capture_output=True,text=True,timeout=100,check=False)
   (root/(name+'.stdout')).write_text(run.stdout);(root/(name+'.stderr')).write_text(run.stderr)
   if run.returncode:raise RuntimeError(f'{name} failed: {run.stderr[-1000:]}')
   result=json.loads(run.stdout)
   if result.get('status')!='ok':raise RuntimeError(f'{name} returned {result.get("status")}')
   return result
  send('health','--file',str(scripts/'health_check.py'))
  code='''import omni.usd\nfrom pxr import UsdGeom,UsdLux\nctx=omni.usd.get_context()\nstage=ctx.get_stage()\nassert stage is not None\ncube=UsdGeom.Cube.Define(stage,"/World/SimSceneProbeCube")\ncube.CreateSizeAttr(0.2)\nlight=UsdLux.DomeLight.Define(stage,"/World/SimSceneProbeDome")\nlight.CreateIntensityAttr(300.0)\nassert stage.GetPrimAtPath("/World/SimSceneProbeCube")\nprint("SIMSCENE_REMOTE_STAGE_OK")'''
  result=send('stage',code)
  if 'SIMSCENE_REMOTE_STAGE_OK' not in str(result.get('output','')):raise RuntimeError('stage marker missing')
  try:send('shutdown','--file',str(scripts/'shutdown_app.py'))
  except (RuntimeError,subprocess.TimeoutExpired):pass
  try:code=process.wait(timeout=30)
  except subprocess.TimeoutExpired:raise RuntimeError('Isaac did not shut down after request')
  if code!=0:raise RuntimeError(f'Isaac shutdown exit {code}')
  (root/'result.json').write_text(json.dumps({'passed':True,'port':port,'scope':'6.2 local developer IPC health and live stage edits; not cross-machine transport or robot acceptance'},indent=2)+'\n')
 except Exception as error:
  (root/'result.json').write_text(json.dumps({'passed':False,'error':str(error),'port':port},indent=2)+'\n');raise
 finally:
  if process is not None and process.poll() is None:
   os.killpg(process.pid,signal.SIGTERM)
   try:process.wait(timeout=15)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
