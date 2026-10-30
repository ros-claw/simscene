"""Inspect and edit real source recordings with explicit simulation-time mappings."""
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from fractions import Fraction
from .capture import output_config,resolution,finite
from .scene import SceneError
from .video_color import png_filter

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def probe(path):
    executable=shutil.which('ffprobe')
    if not executable:raise SceneError('ffprobe is required')
    command=[executable,'-v','error','-select_streams','v:0','-count_frames','-show_entries',
      'stream=codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt,bit_rate,color_space,color_transfer,color_primaries,color_range,nb_read_frames:format=duration,size','-of','json',str(path)]
    try:return json.loads(subprocess.check_output(command,stderr=subprocess.PIPE,timeout=300))
    except (subprocess.SubprocessError,ValueError) as error:raise SceneError('video probe failed: '+str(error)) from error

def inspect(path,output_dir=None,representative_count=5,record=None):
    path=Path(path).expanduser().resolve()
    if not path.is_file():raise SceneError('video file not found')
    if type(representative_count) is not int or not 1<=representative_count<=12:raise SceneError('representative_count must be 1..12')
    metadata=probe(path)
    if not metadata.get('streams'):raise SceneError('video has no video stream')
    stream=metadata['streams'][0];fps=float(Fraction(stream['avg_frame_rate']));count=int(stream.get('nb_read_frames',0));duration=count/fps if fps else 0
    issues=[];timeline=None
    if record:
        manifest=Path(record.get('frame_manifest',''))
        if not manifest.is_file():issues.append('missing simulation frame manifest')
        else:
            rows=[json.loads(line) for line in manifest.read_text().splitlines()];interval=60//record['fps'];first=record.get('first_physics_step',interval)
            valid=bool(rows) and len(rows)==count==record['frames'] and stream['width']==record['width'] and stream['height']==record['height'] and abs(fps-record['fps'])<1e-7
            from PIL import Image
            camera=None;raw_checks=[]
            for index,row in enumerate(rows):
                if index==0:camera=row.get('camera_id')
                expected=first+index*interval
                valid=valid and row.get('frame_id')==index and row.get('camera_id')==camera and row.get('physics_step')==expected and abs(row.get('sim_time_s',-1)-expected/60)<1e-7 and row.get('width')==stream['width'] and row.get('height')==stream['height'] and abs(row.get('video_time_s',-1)-index/fps)<1e-7
                if row.get('raw_png'):
                    image_path=Path(row['raw_png'])
                    try:
                        with Image.open(image_path) as image:ok=image.size==(stream['width'],stream['height'])
                    except OSError:ok=False
                    raw_checks.append({'path':str(image_path),'native_size_matches':ok});valid=valid and ok
            timeline={'passed':bool(valid),'frames':len(rows),'first_physics_step':first,'last_physics_step':rows[-1]['physics_step'] if rows else None,'interval_steps':interval,'raw_keyframes':raw_checks}
            if not valid:issues.append('native capture size, frame count or simulation clock mismatch')
    else:
        edit_path=path.with_suffix('.edit.json')
        if not edit_path.is_file():issues.append('no simulation frame provenance supplied; container metadata alone cannot establish native capture')
        else:
            try:
                edit=json.loads(edit_path.read_text());valid=edit['sha256']==sha(path) and edit['resolution']==[stream['width'],stream['height']]
                previous=0;source_checks=[]
                for segment in edit['segments']:
                    run=Path(segment['run_directory']);source=Path(segment['source'])
                    from .run_integrity import verify as verify_run
                    from .evidence_integrity import verify as verify_evidence
                    checked=source.is_file() and sha(source)==segment['source_sha256'] and sha(run/'run-lock.json')==segment['run_lock_sha256'] and sha(run/'evidence-lock.json')==segment['evidence_lock_sha256']
                    checked=checked and verify_run(run)['passed'] and verify_evidence(run)['passed']
                    source_checks.append({'run_id':segment['run_id'],'camera':segment['camera'],'passed':bool(checked)})
                    valid=valid and checked and abs(segment['output_start_s']-previous)<1e-6 and segment['output_end_s']>previous and finite(segment['speed']) and segment['speed']>0
                    previous=segment['output_end_s']
                valid=valid and bool(source_checks) and abs(duration-previous)<=max(.1,len(source_checks)/fps)
                timeline={'passed':bool(valid),'kind':'edited_simulation_sources','source_checks':source_checks,'edit_manifest':str(edit_path)}
                if not valid:issues.append('edited source hashes, dimensions or time map mismatch')
            except (OSError,KeyError,TypeError,ValueError) as error:issues.append('invalid edit provenance: '+str(error))

    representatives=[]
    if output_dir:
        root=Path(output_dir).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
        for index in range(representative_count):
            frame_id=min(count-1,max(0,round((count-1)*(index/(representative_count-1) if representative_count>1 else .5))))
            image=root/f'{path.stem}_decoded_{frame_id:06d}.png'
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(path),'-vf',f'select=eq(n\\,{frame_id}),'+png_filter(stream),'-frames:v','1','-vsync','0',str(image)],check=True,timeout=120)
            representatives.append({'frame_id':frame_id,'video_time_s':frame_id/fps,'path':str(image)})
    return {'path':str(path),'sha256':sha(path),'metadata':metadata,'decoded_frame_count':count,'duration_s':duration,'simulation_timeline':timeline,
            'representative_frames':representatives,'representative_png_filter':png_filter(stream),'issues':issues,'requires_visual_review':['subject detail and action visibility','highlights and material loading','occlusion, black frames, cuts and motion continuity']}

def export(segments,destination,output_resolution=None,output=None,allow_upscale=False):
    """segments: run_directory, camera, start/end sim seconds, optional speed/title.

    Every source must have intact run/evidence locks and a continuous native
    capture manifest. Playback speed is an explicit edit, recorded per segment.
    """
    if not isinstance(segments,list) or not 1<=len(segments)<=64:raise SceneError('export requires 1..64 source segments')
    destination=Path(destination).expanduser().resolve()
    if destination.exists():raise SceneError('video destination exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    config=output_config(output);size=resolution(output_resolution or [1920,1080]);width,height=size
    from .run_integrity import verify as verify_run
    from .evidence_integrity import verify as verify_evidence
    mappings=[];files=[];elapsed=0
    import tempfile
    with tempfile.TemporaryDirectory(prefix='simscene-edit-',dir=destination.parent) as tmp:
        tmp=Path(tmp)
        for index,segment in enumerate(segments):
            if not isinstance(segment,dict) or set(segment)-{'run_directory','camera','start_sim_time_s','end_sim_time_s','speed','title'}:raise SceneError('unsupported source segment fields')
            run=Path(segment['run_directory']).expanduser().resolve()
            locks={'inputs':verify_run(run),'outputs':verify_evidence(run)}
            if not all(v.get('passed') is True for v in locks.values()):raise SceneError('source recording integrity check failed: '+str(run))
            result=json.loads((run/'result.json').read_text());record=result.get('videos',{}).get(segment['camera'])
            if not record:raise SceneError('source camera recording not found')
            inspection=inspect(record['path'],record=record,representative_count=1)
            if not inspection['simulation_timeline'] or not inspection['simulation_timeline']['passed']:raise SceneError('source capture is not continuous')
            first=record['first_physics_step']/60;last=record['last_physics_step']/60+1/record['fps']
            start=segment.get('start_sim_time_s',first);end=segment.get('end_sim_time_s',last);speed=segment.get('speed',1)
            if not all(finite(v) for v in (start,end,speed)) or not first-1e-7<=start<end<=last+1e-7 or not .1<=speed<=8:raise SceneError('segment lies outside recorded simulation interval or speed bounds')
            frame_start=math.ceil((start-first)*record['fps']-1e-6);frame_end=min(record['frames'],math.ceil((end-first)*record['fps']-1e-6))
            if frame_end<=frame_start:raise SceneError('empty video segment')
            scale=min(width/record['width'],height/record['height'])
            if scale>1.000001 and not allow_upscale:raise SceneError('upscaling requires allow_upscale=true; acquire native source first')
            output_file=tmp/f'part{index:03d}.mp4';title=segment.get('title','')
            filters=[f'trim=start_frame={frame_start}:end_frame={frame_end}',f'setpts=(PTS-STARTPTS)/{speed}',
                     f'scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos',f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x101720','setsar=1']
            if title:
                if not isinstance(title,str) or len(title)>160 or '\n' in title:raise SceneError('title must be a short single line')
                title_file=tmp/f'title{index:03d}.txt';title_file.write_text(title)
                filters.append(f'drawtext=textfile={title_file}:expansion=none:fontcolor=white:fontsize=28:x=48:y=36:box=1:boxcolor=black@0.55:boxborderw=12')
            composed=destination.with_name(destination.stem+f'_composed_{index:03d}.png')
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-threads','2','-i',record['path'],'-vf',','.join(filters)+','+png_filter(inspection['metadata']['streams'][0]),'-frames:v','1',str(composed)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=120)
            # Keep source cadence. A 6fps source cannot be certified as 30 real
            # observations/s just by asking ffmpeg to duplicate it.
            fps=record['fps']
            if index and fps!=mappings[0]['source_fps']:raise SceneError('mixed capture rates require explicit separate exports')
            cmd=['ffmpeg','-hide_banner','-loglevel','warning','-y','-threads','2','-i',record['path'],'-an','-vf',','.join(filters),'-r',str(fps),'-c:v','libx264','-threads','2','-crf',str(config['crf']),'-preset',config['preset'],'-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',str(output_file)]
            subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=1200)
            length=(frame_end-frame_start)/fps/speed
            mappings.append({'run_id':run.name,'run_directory':str(run),'camera':segment['camera'],'source':record['path'],'source_sha256':inspection['sha256'],
                'source_frame_manifest_sha256':sha(record['frame_manifest']),'run_lock_sha256':sha(run/'run-lock.json'),'evidence_lock_sha256':sha(run/'evidence-lock.json'),
                'source_fps':fps,'source_resolution':[record['width'],record['height']],'source_start_frame':frame_start,'source_end_frame_exclusive':frame_end,
                'source_sim_start_s':first+frame_start/fps,'source_sim_end_s':first+frame_end/fps,'speed':speed,'title':title,
                'composed_keyframe':str(composed),'composed_keyframe_sha256':sha(composed),'output_start_s':elapsed,'output_end_s':elapsed+length,'upscale_factor':max(1,scale),'physics_task_status':result.get('task_status')})
            elapsed+=length;files.append(output_file)
        concat=tmp/'concat.txt';concat.write_text(''.join("file '"+str(file).replace("'","'\\''")+"'\n" for file in files))
        try:
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(destination)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=300)
        except BaseException:
            destination.unlink(missing_ok=True);raise
    manifest={'schema':'simscene.video_edit.v1','path':str(destination),'sha256':sha(destination),'resolution':size,'encoding':config,'segments':mappings,
              'metadata':probe(destination),'visual_review':'pending; inspect representative frames and motion clips before delivery'}
    manifest_path=destination.with_suffix('.edit.json');manifest_path.write_text(json.dumps(manifest,indent=2))
    return {**manifest,'manifest_path':str(manifest_path)}
