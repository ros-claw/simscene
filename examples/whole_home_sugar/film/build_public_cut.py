"""Build the 55-second original-speed cut from the two sealed MAIN1 cameras.

Run with the repository's Python environment. No physics is launched and the
source run is never edited. A separate replay-render can supply extra views.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'src'))
from simscene.video_tools import export, probe, sha


def command(argv):
    subprocess.run(argv, check=True, stdout=subprocess.DEVNULL)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--output-directory', type=Path, required=True)
    p.add_argument('--font', type=Path, default=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
    p.add_argument('--cup-foley-from-director', type=Path)
    p.add_argument('--resume', action='store_true', help='reuse the completed silent edit; only finish audio/provenance')
    a = p.parse_args(); out = a.output_directory.resolve(); out.mkdir(exist_ok=a.resume, parents=True)
    intent = json.loads(Path(__file__).with_name('shot-windows.json').read_text())
    if a.resume:
        edited = json.loads((out/'live-50.5s.edit.json').read_text())
        if sha(out/'live-50.5s.mp4') != edited['sha256']:
            raise ValueError('completed live edit changed')
        for segment in edited['segments']:
            if segment['run_directory'] != str(a.run.resolve()) or sha(segment['source']) != segment['source_sha256']:
                raise ValueError('resume source differs')
        edited['manifest_path'] = str(out/'live-50.5s.edit.json')
        mapping = [json.loads(x) for x in (out/'public-frame-map.jsonl').read_text().splitlines()]
        if len(mapping) != 1515:
            raise ValueError('incomplete completed frame map')
        silent = out/'only-one-sugar-public-55s-silent.mp4'
    else:
        live = []
        for s in intent['main_cut']['segments']:
            if s['type'] != 'main1_live':
                continue
            windows = [(s['sim_in_s'], s['sim_out_s'], 'story_camera')]
            if s['id'] == 'M5':
                windows = [(54, 56.5, 'fixed_overview'), (56.5, 60, 'story_camera')]
            for start, end, camera in windows:
                live.append({'run_directory': str(a.run.resolve()), 'camera': camera,
                             'start_sim_time_s': start, 'end_sim_time_s': end, 'speed': 1,
                             'title': '同一次仿真 · 原速节选' + ('｜省略中段路程' if s['id'] == 'M6' else '')})
        edited = export(live, out/'live-50.5s.mp4', font_file=a.font)
        assert sum(s['output_frames'] for s in edited['segments']) == 1515
        font = a.font.resolve()
        def card(filename, frames, lines):
            filters = []
            for i, (text, size, y, color) in enumerate(lines):
                path = out/(filename+str(i)+'.txt'); path.write_text(text)
                filters.append(f'drawtext=fontfile={font}:textfile={path}:expansion=none:fontsize={size}:fontcolor={color}:x=(w-text_w)/2:y={y}')
            command(['ffmpeg', '-loglevel', 'error', '-threads', '2', '-f', 'lavfi', '-i', 'color=c=0x101d25:s=1920x1080:r=30',
                     '-vf', ','.join(filters), '-frames:v', str(frames), '-an', '-c:v', 'libx264', '-threads', '2',
                     '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-color_range', 'tv',
                     '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', str(out/filename)])
        card('opening.mp4', 60, [('只想加一块糖', 88, 390, 'white'),
                                ('200 张骨牌，只为一块糖', 38, 530, '0xd7c3a1'),
                                ('只放开一颗球。', 30, 625, '0xc3d2d8')])
        card('ending.mp4', 75, [('好了，一块。', 88, 390, 'white'),
                               ('ROSClaw / SimScene', 38, 535, '0xd7c3a1'),
                               ('github.com/ros-claw/simscene', 28, 620, '0xc3d2d8'),
                               ('106 秒连续原速版与可编辑工程随项目交付', 26, 700, '0xc3d2d8'),
                               ('杯响：后期拟音', 22, 1010, '0xc3d2d8')])
        concat = out/'concat.txt'
        concat.write_text(''.join("file '"+str(out/f).replace("'", "'\\''")+"'\n" for f in ['opening.mp4', 'live-50.5s.mp4', 'ending.mp4']))
        silent = out/'only-one-sugar-public-55s-silent.mp4'
        command(['ffmpeg', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy', '-movflags', '+faststart', str(silent)])
        mapping = []
        for segment in edited['segments']:
            source = Path(segment['run_directory'])/('camera_'+segment['camera']+'.frames.jsonl')
            rows = [json.loads(x) for x in source.read_text().splitlines()]
            for i, row in enumerate(rows[segment['source_start_frame']:segment['source_end_frame_exclusive']]):
                mapping.append({'output_frame_id': 60+round(segment['output_start_s']*30)+i,
                                'source_frame_id': row['frame_id'], 'source_physics_step': row['physics_step'],
                                'source_sim_time_s': row['sim_time_s'], 'camera': segment['camera'],
                                'run_id': a.run.name, 'speed': 1})
        assert len(mapping) == 1515
        (out/'public-frame-map.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in mapping))
    final = out/'only-one-sugar-public-55s.mp4'
    audio = None
    if a.cup_foley_from_director:
        # Source callback: relative step5858; find its actual retained frame.
        contact = next(x for x in mapping if x['source_physics_step'] >= 5858)
        sample = round(contact['output_frame_id']/30*48000)
        wav = out/'cup-post-foley.wav'
        if not wav.exists():
            command(['ffmpeg', '-loglevel', 'error', '-ss', '97.6', '-i', str(a.cup_foley_from_director),
                     '-t', '0.24', '-vn', '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)])
        if not final.exists():
            command(['ffmpeg', '-loglevel', 'error', '-i', str(silent), '-i', str(wav),
                     '-filter_complex', f'[1:a]adelay={sample}S:all=1,apad=whole_dur=55,atrim=duration=55[a]',
                     '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(final)])
        audio = {'source': str(a.cup_foley_from_director.resolve()), 'source_sha256': sha(a.cup_foley_from_director),
                 'source_start_s': 97.6, 'duration_s': .24, 'output_sample_48000Hz': sample,
                 'kind': 'disclosed post-production foley, not native acoustics'}
    else:
        final.write_bytes(silent.read_bytes())
    metadata = probe(final)
    video = next(s for s in metadata['streams'] if 'width' in s)
    assert int(video['nb_read_frames']) == 1650
    record = {'schema': 'simscene.sugar_public_film.v1', 'status': 'encoded_pending_visual_review',
              'path': str(final), 'sha256': sha(final), 'duration_s': 55, 'frames': 1650,
              'live_frames': 1515, 'graphic_card_frames': 135, 'speed': 1,
              'run_id': a.run.name, 'native_source_edit': edited['manifest_path'],
              'frame_map': str(out/'public-frame-map.jsonl'), 'audio': audio,
              'scope': 'Same original MAIN1, chronological original-speed excerpts with explicit time omissions; not a55s continuous chain.',
              'metadata': metadata}
    (out/'public-film.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'path': str(final), 'duration_s': 55, 'frames': 1650}, ensure_ascii=False))


if __name__ == '__main__':
    main()
