"""Cut a labelled, traceable highlight from one verified physics recording."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from simscene.evidence_integrity import verify as verify_outputs
from simscene.run_integrity import verify as verify_inputs

if len(sys.argv) != 3:
    raise SystemExit('usage: make_three_arm_highlight.py RUN_DIRECTORY OUTPUT_DIRECTORY')
run, out = (Path(x).resolve() for x in sys.argv[1:])
status = json.loads((run/'job-status.json').read_text())
case = json.loads((run/'verification.json').read_text())
inputs, outputs = verify_inputs(run), verify_outputs(run)
if (status.get('state') != 'completed' or status.get('exit_code') != 0 or
        status.get('exit_code_inferred') is not False or case.get('passed') is not True or
        inputs.get('passed') is not True or outputs.get('passed') is not True or outputs.get('partial')):
    raise SystemExit('run did not pass its pinned physical case and evidence checks')
result = json.loads((run/'result.json').read_text())
choices = [('kawasaki', 'camera_overview.mp4'), ('franka', 'camera_grasp_view.mp4'),
           ('ur10', 'camera_overview.mp4')]
clips = []
for robot, filename in choices:
    transitions = result['followers'][robot]['transitions']
    start = next(item['physics_step'] for item in transitions if item['index'] == 2)
    end = next(item['physics_step'] for item in transitions if item['index'] == 9)
    if end <= start:
        raise ValueError('invalid pick-cycle transition times')
    source = run/filename
    if not source.is_file():
        raise ValueError('recorded camera video missing')
    clips.append({'robot':robot, 'source':str(source),
                  'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                  'start_s':max(0, start/60-3), 'duration_s':(end-start)/60+7,
                  'tracking_start_step':start, 'retract_start_step':end})
out.mkdir(parents=True, exist_ok=False)
command = ['ffmpeg', '-v', 'error', '-nostdin']
for clip in clips:
    command += ['-ss', str(clip['start_s']), '-t', str(clip['duration_s']), '-i', clip['source']]
command += ['-filter_complex',
            ''.join(f'[{i}:v]setpts=PTS-STARTPTS,fps=6,scale=640:480,setsar=1[v{i}];' for i in range(len(clips))) +
            ''.join(f'[v{i}]' for i in range(len(clips))) + f'concat=n={len(clips)}:v=1:a=0[v]',
            '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', str(out/'highlight.mp4')]
subprocess.run(command, check=True)
manifest = {'source_run':str(run), 'physical_case_passed':True, 'input_and_output_locks_passed':True,
            'source_simulation_time_s':result['simulation_time_s'], 'clips':clips,
            'playback':'Six frames per simulated second, in order, with cuts between robot cycles; no generated or interpolated frames.',
            'highlight_sha256':hashlib.sha256((out/'highlight.mp4').read_bytes()).hexdigest()}
(out/'provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'output':str(out/'highlight.mp4'), 'clips':len(clips)}))
