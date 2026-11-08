"""Make a labelled 20-second split screen from two independently sealed runs."""
import argparse
import json
from pathlib import Path
from finish_showcase import Edit, read, rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--comparison', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--font', type=Path, default=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
    a = p.parse_args(); edit = Edit(a.output, a.font)
    edit.card('question', 60, [('把这根红绳断开，', '(w-text_w)/2', 340, 76, 'white'),
                             ('抽屉还会打开吗？', '(w-text_w)/2', 470, 76, '0xe9cf9b'),
                             ('两次独立运行 · 原速对照', '(w-text_w)/2', 650, 34, 'white')])
    sources = []
    from simscene.video_tools import sha
    for name in ('positive', 'cut'):
        sealed = read(a.comparison/(name+'-native1080p-1x.edit.json'))
        segment = sealed['segments'][0]; source = Path(segment['source'])
        assert sha(source) == segment['source_sha256']
        journal = rows(Path(segment['run_directory'])/('camera_'+segment['camera']+'.frames.jsonl'))
        sources.append((source, segment, journal))
        edit.sources[str(source)] = segment['source_sha256']

    def split(name, fixed=False):
        starts = [next(i for i, r in enumerate(j) if r['physics_step'] == 3000) if fixed else s['source_start_frame']
                  for _, s, j in sources]
        count = 120 if fixed else 360
        labels = ['接通 · 抽屉打开约 36 厘米', '断开抽屉端 · 开启量 0 厘米'] if fixed else ['接通 · 原速', '断开抽屉端 · 原速']
        filters = []
        for i, start in enumerate(starts):
            end = start+1 if fixed else start+count
            hold = ',loop=loop=-1:size=1:start=0' if fixed else ''
            filters.append(f'[{i}:v]trim=start_frame={start}:end_frame={end},crop=960:1080:480:0{hold},settb=1/30,setpts=N,fps=30[p{i}]')
        header = '定帧：各自物理第 3000 步 · 两边配重均已下降约 42 厘米' if fixed else '两次独立运行，各自原速播放 · 起点不同，不代表同步交互'
        filters.append('[p0][p1]hstack=inputs=2,drawbox=x=0:y=0:w=iw:h=110:color=0x101d25@0.94:t=fill,'+
                       edit.text(labels[0], 36, 28, 32)+','+edit.text(labels[1], 996, 28, 32)+','+
                       'drawbox=x=0:y=996:w=iw:h=84:color=0x101d25@0.94:t=fill,'+
                       edit.text(header, '(w-text_w)/2', 1020, 28)+'[v]')
        dest = edit.out/(name+'.mp4')
        args = []
        for source, _, _ in sources:
            args += ['-i', str(source)]
        edit.command([*args, '-filter_complex', ';'.join(filters), '-map', '[v]', '-frames:v', str(count), '-r', '30', '-fps_mode', 'cfr', '-an',
                      '-c:v', 'libx264', '-threads', '2', '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p',
                      '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', str(dest)])
        edit.parts.append(dest)
        for n in range(count):
            panels = []
            for (source, segment, journal), start in zip(sources, starts):
                i = start if fixed else start+n; r = journal[i]
                panels.append({'source': str(source), 'source_frame': i, 'source_run_id': segment['run_id'],
                               'source_physics_step': r['physics_step'], 'speed': 0 if fixed else 1,
                               'crop_pixels_xywh': [480, 0, 960, 1080]})
            edit.mapping.append({'output_frame': len(edit.mapping), 'edit_segment': name, 'kind': 'labelled_still' if fixed else 'independent_native_split_screen', 'panels': panels})

    split('independent-runs')
    split('measured-result', True)
    edit.card('ending', 60, [('断开这一端，结果就改变。', '(w-text_w)/2', 380, 68, 'white'),
                           ('真实被动传力 · ROSClaw / SimScene', '(w-text_w)/2', 530, 36, '0xe9cf9b'),
                           ('github.com/ros-claw/simscene', '(w-text_w)/2', 650, 30, 'white')])
    result = edit.finish('red-rope-causal-comparison-20s', 600)
    print(json.dumps({'path': result['path'], 'frames': result['frames']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
