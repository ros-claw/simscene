"""Cut four genuine synchronized camera recordings into an 80 s video.

The source is a completed 300 s Isaac run, with simulation-time playback at
1:1 speed. The individual views and their continuous original videos remain in
the run; no synthetic frames, narration or success numbers are introduced.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from simscene.evidence_integrity import verify

if len(sys.argv) != 3:
    raise SystemExit('usage: render_three_arm_showcase.py RUN_DIRECTORY NEW_OUTPUT_MP4')
root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
if output.exists():
    raise SystemExit('output already exists')
record = json.loads((root/'result.json').read_text())
integrity = verify(root)
if not integrity['passed'] or integrity['partial'] or record.get('actual_physics_steps', 0) < 13200:
    raise SystemExit('a complete, intact run of at least 220 simulated seconds is required')
segments = [('overview', 140, 160), ('grasp_view', 160, 180),
            ('top_view', 180, 200), ('moving_view', 200, 220)]
paths = []
for name, _, end in segments:
    info = record.get('videos', {}).get(name, {})
    path = Path(info.get('path', '')).resolve()
    if not path.is_file() or path.parent != root or path.is_symlink():
        raise SystemExit('missing or external source recording: '+name)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                            '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    if float(json.loads(probe.stdout)['format']['duration']) < end:
        raise SystemExit('recording does not cover requested interval: '+name)
    paths.append(path)
filters = [f'[{i}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]'
           for i, (_, start, end) in enumerate(segments)]
filters.append(''.join(f'[v{i}]' for i in range(len(segments)))+f'concat=n={len(segments)}:v=1:a=0[out]')
command = ['ffmpeg', '-hide_banner', '-loglevel', 'error']
for path in paths:
    command += ['-i', str(path)]
command += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-c:v', 'libx264',
            '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', str(output)]
output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(command, check=True)
def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()
provenance = {'run_directory': str(root), 'input_evidence_integrity': integrity['passed'],
              'segments': [{'camera': name, 'start_simulation_s': start, 'end_simulation_s': end,
                            'file': str(path), 'sha256': digest(path)}
                           for (name, start, end), path in zip(segments, paths)],
              'output': str(output), 'output_sha256': digest(output), 'playback_seconds': 80,
              'scope': 'A presentation cut from real synchronized cameras at recorded simulation speed; it is not independent evidence of sorting success.'}
output.with_suffix('.provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')
print(json.dumps(provenance, indent=2))
