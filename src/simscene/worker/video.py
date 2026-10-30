"""Native-resolution simulation-time recording with auditable frame provenance."""
import json
import shutil
import subprocess
from pathlib import Path
from simscene.capture import output_config
from simscene.video_color import SRGB_TO_REC709

class VideoRecorder:
    def __init__(self,path,fps,width=640,height=480,*,camera_id=None,output=None,budget=None,diagnostics=None,start_step=0):
        executable=shutil.which('ffmpeg')
        if not executable:raise RuntimeError('ffmpeg is required for camera recording')
        if type(fps) is not int or fps not in (1,2,3,4,5,6,10,12,15,20,30):raise ValueError('fps must divide 60')
        self.path=Path(path);self.fps=fps;self.width=width;self.height=height;self.frames=0
        self.camera_id=camera_id or self.path.stem;self.output=output_config(output);self.budget=budget or {};self.diagnostics=diagnostics or {}
        self.keyframes=[];self.last_step=0;self.closed=False;self.start_step=start_step
        self.manifest_path=self.path.with_suffix('.frames.jsonl');self.manifest=self.manifest_path.open('w')
        self.log=self.path.with_suffix('.ffmpeg.log').open('wb')
        self.command=[executable,'-hide_banner','-loglevel','warning','-y','-threads','2',
            '-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','-',
            '-an','-c:v','libx264','-threads','2','-preset',self.output['preset'],'-crf',str(self.output['crf']),
            # Isaac rgb annotator supplies display-referred sRGB bytes. Convert
            # sRGB full-range RGB to limited-range BT.709 SDR; labels alone
            # would not transform the transfer function or RGB/YUV matrix.
            '-vf',SRGB_TO_REC709,
            '-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709',
            '-g',str(fps*5),'-movflags','frag_keyframe+empty_moov+default_base_moof','-flush_packets','1',str(self.path)]
        try:self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.log)
        except Exception:self.log.close();self.manifest.close();raise

    def _budget_check(self):
        root=self.path.parent
        used=sum(p.stat().st_size for p in root.iterdir() if p.is_file() and (p.suffix in ('.mp4','.png','.jsonl') or '.ffmpeg.' in p.name))
        if used>self.budget.get('max_recording_bytes',8*1024**3):raise RuntimeError('recording storage budget exceeded')
        if shutil.disk_usage(root).free<self.budget.get('min_free_bytes',2*1024**3):raise RuntimeError('recording minimum free-space budget exceeded')

    def write(self,frame,physics_step=None,sim_time_s=None,render_context=None):
        if self.closed:raise RuntimeError('recorder is closed')
        if frame.shape!=(self.height,self.width,3) or str(frame.dtype)!='uint8':raise RuntimeError(f'Unexpected camera frame shape/dtype: {frame.shape}, {frame.dtype}')
        expected=self.start_step+(self.frames+1)*(60//self.fps)
        physics_step=expected if physics_step is None else physics_step
        sim_time_s=physics_step/60 if sim_time_s is None else sim_time_s
        if physics_step!=expected or abs(sim_time_s-physics_step/60)>1e-7:raise RuntimeError('camera frame physics clock is discontinuous')
        if self.frames%self.fps==0:self._budget_check()
        try:self.process.stdin.write(frame.tobytes())
        except (OSError,BrokenPipeError) as error:raise RuntimeError('ffmpeg failed while recording; inspect '+str(self.path.with_suffix('.ffmpeg.log'))) from error
        record={'frame_id':self.frames,'camera_id':self.camera_id,'physics_step':physics_step,'sim_time_s':sim_time_s,'width':self.width,'height':self.height,'video_time_s':self.frames/self.fps}
        if render_context:record['render_context']=render_context
        interval=self.diagnostics.get('keyframe_interval_s',10)
        if self.frames==0 or (self.frames+1)/self.fps<=self.diagnostics.get('png_seconds',0) or interval and physics_step%max(1,round(interval*60))==0:
            from PIL import Image
            key=self.path.with_name(self.path.stem+f'_frame_{self.frames:06d}.png')
            Image.fromarray(frame).save(key);record['raw_png']=str(key);self.keyframes.append(str(key))
        self.manifest.write(json.dumps(record)+'\n');self.manifest.flush()
        self.frames+=1;self.last_step=physics_step

    def close(self):
        try:
            self.process.stdin.close();code=self.process.wait(timeout=60);self.manifest.close();self.closed=True
            if code or not self.frames:raise RuntimeError(f'video encoding failed: exit={code}, frames={self.frames}; '+str(self.path.with_suffix('.ffmpeg.log')))
            self._budget_check()
            return {'path':str(self.path),'fps':self.fps,'frames':self.frames,'duration_s':self.frames/self.fps,
                    'width':self.width,'height':self.height,'native_resolution':[self.width,self.height],
                    'timebase':'simulation','first_physics_step':self.start_step+60//self.fps,'last_physics_step':self.last_step,
                    'frame_manifest':str(self.manifest_path),'keyframes':self.keyframes,'encoding':self.output,'encoder_command':self.command,
                    'input_color':'display-referred sRGB RGB24 full range','output_color':'BT.709 SDR limited-range YUV420P; transfer and matrix converted',
                    'encoder_log':str(self.path.with_suffix('.ffmpeg.log'))}
        finally:
            if self.process.poll() is None:self.process.kill();self.process.wait()
            self.log.close();self.manifest.close();self.closed=True

    def abort(self):
        if self.process.poll() is None:self.process.kill();self.process.wait()
        if self.process.stdin and not self.process.stdin.closed:
            try:self.process.stdin.close()
            except OSError:pass
        self.log.close();self.manifest.close();self.closed=True
