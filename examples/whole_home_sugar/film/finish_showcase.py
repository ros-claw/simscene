"""Edit source footage and exact-pose camera renders with per-frame provenance.

No simulation is started. All live cuts keep their recorded speed. Slow shots
must already contain 60 Hz recorded samples played at 30 fps, with no interpolation.
"""
import argparse
from array import array
import json
from pathlib import Path
import subprocess
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from simscene.video_tools import probe, sha


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines()]


class Edit:
    def __init__(self, out, font):
        self.out = out.resolve(); self.out.mkdir(parents=True, exist_ok=False)
        self.font = font.resolve(); self.mapping = []; self.parts = []; self.sources = {}

    def command(self, args):
        with (self.out / 'ffmpeg.log').open('ab') as log:
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'warning', '-threads', '2', *args],
                           check=True, stdout=subprocess.DEVNULL, stderr=log)

    def text(self, value, x, y, size=36, color='white'):
        path = self.out / f'text-{len(list(self.out.glob("text-*.txt"))):03d}.txt'
        path.write_text(value)
        return f'drawtext=fontfile={self.font}:textfile={path}:expansion=none:fontsize={size}:fontcolor={color}:x={x}:y={y}'

    def encode(self, args, filters, frames, name):
        dest = self.out / (name + '.mp4')
        self.command([*args, '-vf', ','.join(filters), '-frames:v', str(frames), '-an',
                      '-r', '30', '-fps_mode', 'cfr',
                      '-c:v', 'libx264', '-threads', '2', '-preset', 'medium', '-crf', '18',
                      '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709',
                      '-color_primaries', 'bt709', '-color_trc', 'bt709', str(dest)])
        self.parts.append(dest)
        return dest

    def live(self, source, source_rows, first, last, label, name, provenance):
        source = Path(source)
        if str(source) not in self.sources:
            self.sources[str(source)] = sha(source)
        selected = source_rows[first:last]
        if len(selected) != last-first or not selected:
            raise ValueError('incomplete source frame selection')
        filters = [f'trim=start_frame={first}:end_frame={last}', 'settb=1/30', 'setpts=N',
                   'drawbox=x=0:y=0:w=iw:h=86:color=0x101d25@0.88:t=fill',
                   self.text(label, 42, 20, 32)]
        self.encode(['-i', str(source)], filters, len(selected), name)
        for i, r in enumerate(selected):
            self.mapping.append({'output_frame': len(self.mapping), 'edit_segment': name, 'kind': provenance,
                'source': str(source), 'source_frame': first+i,
                'source_physics_step': r.get('source_physics_step', r.get('physics_step')),
                'source_run_id': r.get('source_run_id', r.get('run_id')),
                'speed': r.get('playback_speed', r.get('speed', 1))})

    def card(self, name, frames, lines, still=None, source_row=None):
        filters = []
        if still:
            self.sources[str(still)] = sha(still)
            args = ['-loop', '1', '-framerate', '30', '-i', str(still)]
            filters += ['drawbox=x=0:y=0:w=iw:h=300:color=0x101d25@0.8:t=fill']
        else:
            args = ['-f', 'lavfi', '-i', 'color=c=0x101d25:s=1920x1080:r=30']
        for value, x, y, size, color in lines:
            filters.append(self.text(value, x, y, size, color))
        dest = self.encode(args, filters, frames, name)
        for _ in range(frames):
            self.mapping.append({'output_frame': len(self.mapping), 'edit_segment': name, 'kind': 'labelled_still' if still else 'graphic_card',
                                 'still': str(still) if still else None, 'source_pose': source_row})
        return dest

    def finish(self, name, expected_frames, foley=None):
        if len(self.mapping) != expected_frames:
            raise ValueError(f'edit has {len(self.mapping)} frames, expected {expected_frames}')
        for source, digest in self.sources.items():
            if sha(source) != digest:
                raise ValueError('source changed while editing')
        concat = self.out / 'concat.txt'
        concat.write_text(''.join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in self.parts))
        silent = self.out / (name + '-silent.mp4')
        self.command(['-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy', '-movflags', '+faststart', str(silent)])
        dest = self.out / (name + '.mp4'); audio = None
        if foley:
            target = next(r for r in self.mapping if r.get('source_physics_step', -1) >= 5858 and r.get('speed') == 1)
            delay = round(target['output_frame']/30*48000)
            # Build the complete PCM track explicitly. Filter timestamp gaps
            # can produce a nominally 55s AAC stream with only a few seconds of
            # decoded samples; a full WAV makes timing and silence inspectable.
            pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', '97.6', '-i', str(foley),
                '-t', '0.24', '-vn', '-ar', '48000', '-ac', '1', '-f', 's16le', '-'])
            cue = array('h'); cue.frombytes(pcm)
            if sys.byteorder != 'little': cue.byteswap()
            onset = next(i for i, v in enumerate(cue) if abs(v) > 98)
            cue = cue[onset:]; gain = .25*32767/max(abs(v) for v in cue)
            cue = array('h', (round(v*gain) for v in cue))
            track = array('h', [0]) * round(expected_frames/30*48000)
            track[delay:delay+len(cue)] = cue
            if sys.byteorder != 'little': track.byteswap()
            wav = self.out/'complete-post-foley.wav'
            with wave.open(str(wav), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(track.tobytes())
            self.command(['-i', str(silent), '-i', str(wav),
                          '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                          '-movflags', '+faststart', str(dest)])
            audio = {'kind': 'post-production cup foley; not simulated acoustics', 'source': str(foley),
                     'source_sha256': sha(foley), 'source_start_s': 97.6, 'duration_s': .24,
                     'trimmed_leading_samples': onset, 'gain': gain, 'complete_pcm_wav': str(wav), 'pcm_sha256': sha(wav),
                     'output_sample_48000Hz': delay, 'aligned_source_contact_step': 5858}
        else:
            dest.write_bytes(silent.read_bytes())
        metadata = probe(dest)
        stream = next(s for s in metadata['streams'] if 'width' in s)
        assert int(stream['nb_read_frames']) == expected_frames and stream['avg_frame_rate'] == '30/1'
        assert abs(float(metadata['format']['duration'])-expected_frames/30) < .001
        mapping = self.out / 'frame-map.jsonl'
        mapping.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in self.mapping))
        receipt = {'schema': 'simscene.mixed_source_edit.v1', 'path': str(dest), 'sha256': sha(dest),
            'frames': expected_frames, 'fps': 30, 'duration_s': expected_frames/30,
            'source_files_sha256': self.sources, 'font_file': str(self.font), 'font_sha256': sha(self.font),
            'frame_map': str(mapping), 'frame_map_sha256': sha(mapping), 'audio': audio,
            'new_physics_runs': 0, 'visual_review': 'pending decoded images and temporal strips', 'metadata': metadata}
        (self.out / 'film.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
        return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--replay', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--font', type=Path, default=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
    p.add_argument('--foley', type=Path)
    p.add_argument('--mode', choices=['public', 'slow'], required=True)
    a = p.parse_args()
    complete = read(a.replay/'render-complete.json')
    assert complete['new_physics_steps'] == 0
    for clip in complete['videos']:
        assert sha(clip['path']) == clip['sha256']
    edit = Edit(a.output, a.font)

    def native(start, end, camera, name, label='同次物理记录 · 原速节选'):
        journal = rows(a.run/f'camera_{camera}.frames.jsonl')
        ids = [i for i, r in enumerate(journal) if start <= r['sim_time_s'] < end]
        assert len(ids) == round((end-start)*30) and ids == list(range(ids[0], ids[-1]+1))
        for r in journal:
            r['run_id'] = a.run.name
        edit.live(a.run/f'camera_{camera}.mp4', journal, ids[0], ids[-1]+1, label, name, 'original_native_camera')

    def replay(shot, label):
        clip = next(c for c in complete['videos'] if c['shot_id'] == shot)
        journal = rows(clip['frame_map'])
        edit.live(clip['path'], journal, 0, clip['frames'], label, shot, 'new_camera_exact_recorded_poses')

    if a.mode == 'public':
        edit.card('opening', 60, [('只想加一块糖', 80, 76, 78, 'white'),
            ('200 张骨牌，只为一块糖', 84, 190, 38, '0xe9cf9b'),
            ('片头定帧 · 同次物理记录新增机位', 1000, 1020, 24, 'white')],
            a.replay/'opening/frame-00000.png', {'source_run_id': a.run.name, 'source_physics_step': 0})
        native(9, 12.5, 'story_camera', 'release', '只放开一颗球。｜同次物理记录 · 原速节选')
        native(16.5, 22.5, 'story_camera', 'study', '书房醒了。｜原速节选')
        native(29, 35, 'story_camera', 'shelf', '下一站，一座还没放下的桥。｜原速节选')
        replay('bridge_detail', '门变成桥，擀面杖过桥。｜新增机位 · 原速记录重渲染')
        replay('rope_detail', '配重向下，抽屉向外。｜新增机位 · 原速记录重渲染')
        native(54, 56.5, 'fixed_overview', 'car_wide', '然后，小车出发。｜原速节选')
        replay('car_depart', '穿过走廊。｜跟拍 · 原速记录重渲染')
        replay('car_arrive', '省略中段路程，抵达下一站。｜跟拍 · 原速记录重渲染')
        native(82.5, 87, 'story_camera', 'hall', '接力继续。｜原速节选')
        native(92, 96.5, 'story_camera', 'fan', '最后一排，最后一张。｜原速节选')
        replay('finale_detail', '终于，轮到这一块糖。｜新增机位 · 原速记录重渲染')
        edit.card('ending', 75, [('好了，一块。', '(w-text_w)/2', 350, 92, 'white'),
            ('ROSClaw / SimScene', '(w-text_w)/2', 520, 38, '0xe9cf9b'),
            ('github.com/ros-claw/simscene', '(w-text_w)/2', 600, 30, 'white'),
            ('106 秒连续原速版随工程交付 · 杯响为后期拟音', '(w-text_w)/2', 950, 26, '0xc3d2d8')])
        result = edit.finish('only-one-sugar-public-55s', 1650, a.foley)
    else:
        edit.card('opening', 45, [('把精彩，慢慢看。', '(w-text_w)/2', 380, 80, 'white'),
            ('0.5× 慢动作 · 60 Hz 真实位置记录 · 新增机位', '(w-text_w)/2', 540, 34, '0xe9cf9b')])
        replay('slow_wave', '0.5× 慢动作｜骨牌波浪 · 记录重渲染 · 无插帧')
        replay('slow_bridge', '0.5× 慢动作｜转盘、柜门、过桥 · 记录重渲染')
        replay('slow_sugar', '0.5× 慢动作｜最后一次交接，不切镜 · 记录重渲染')
        edit.card('ending', 75, [('原速故事，87.65 秒。', '(w-text_w)/2', 380, 74, 'white'),
            ('慢放只供观看，不计入物理验收时长。', '(w-text_w)/2', 530, 36, '0xe9cf9b'),
            ('github.com/ros-claw/simscene', '(w-text_w)/2', 650, 30, 'white')])
        result = edit.finish('only-one-sugar-details-20s', 600)
    print(json.dumps({'path': result['path'], 'frames': result['frames'], 'duration_s': result['duration_s']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
