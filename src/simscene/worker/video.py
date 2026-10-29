"""Write simulation-time camera frames to a constant-rate video using ffmpeg."""
import shutil
import subprocess
from pathlib import Path

class VideoRecorder:
    def __init__(self, path, fps, width=640, height=480):
        executable=shutil.which('ffmpeg')
        if not executable: raise RuntimeError('ffmpeg is required for camera recording')
        self.path=Path(path);self.fps=fps;self.width=width;self.height=height;self.frames=0
        self.log=self.path.with_suffix('.ffmpeg.log').open('wb')
        try:
            self.process=subprocess.Popen([executable,'-hide_banner','-loglevel','warning','-y',
                '-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',str(fps),'-i','-',
                '-an','-c:v','libx264','-preset','veryfast','-tune','zerolatency','-pix_fmt','yuv420p',
                '-g',str(fps*5),'-movflags','frag_keyframe+empty_moov+default_base_moof','-flush_packets','1',str(self.path)],
                stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.log)
        except Exception:
            self.log.close();raise

    def write(self, frame):
        if frame.shape != (self.height,self.width,3) or str(frame.dtype)!='uint8':
            raise RuntimeError(f'Unexpected camera frame shape/dtype: {frame.shape}, {frame.dtype}')
        try:self.process.stdin.write(frame.tobytes())
        except (OSError, BrokenPipeError) as error:raise RuntimeError('ffmpeg failed while recording') from error
        self.frames+=1

    def close(self):
        try:
            self.process.stdin.close()
            code=self.process.wait(timeout=60)
            if code or not self.frames:raise RuntimeError(f'video encoding failed: exit={code}, frames={self.frames}')
            return {'path':str(self.path),'fps':self.fps,'frames':self.frames,'duration_s':self.frames/self.fps,
                    'timebase':'simulation','encoder_log':str(self.path.with_suffix('.ffmpeg.log'))}
        finally:
            if self.process.poll() is None:self.process.kill();self.process.wait()
            self.log.close()

    def abort(self):
        if self.process.poll() is None:self.process.kill();self.process.wait()
        if self.process.stdin and not self.process.stdin.closed:
            try:self.process.stdin.close()
            except OSError:pass
        self.log.close()
