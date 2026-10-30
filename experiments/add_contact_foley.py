"""Design light contact sounds from frozen-case contacts and the real edit map.

This is post-production sound design, not a simulated acoustic microphone.
Video packets are copied; source frames and causal chronology are unchanged.
"""
import argparse
import copy
import hashlib
import json
import math
import random
import struct
import subprocess
import wave
from pathlib import Path


def map_events(edit):
    events=[]
    for segment in edit['segments']:
        run=Path(segment['run_directory']);lock=json.loads((run/'run-lock.json').read_text())
        name=lock.get('acceptance_case_file')
        if name not in ('acceptance-case.json',):continue
        case=json.loads((run/name).read_text());result=json.loads((run/'result.json').read_text())
        if case.get('schema')!='simscene.passive_chain.v1':continue
        pairs=list(case['edges'])+[[case['receiver']['body_id'],p] for p in case['receiver']['collider_ids']]
        seen=set()
        for first,second in pairs:
            prefix=first+'|/World/'+second.replace('-','_')+'|'
            reverse=second+'|/World/'+first.replace('-','_')+'|'
            records=[v for k,v in result['contact_counts'].items() if k.startswith((prefix,reverse)) and v.get('count',0)>0]
            if not records:continue
            step=min(v['first_physics_step'] for v in records);identity=tuple(sorted([first,second]))
            if identity in seen:continue
            seen.add(identity);time=step/60
            if not segment['source_sim_start_s']<=time<segment['source_sim_end_s']:continue
            events.append({'run_id':run.name,'pair':[first,second],'physics_step':step,'source_sim_time_s':time,'output_time_s':segment['output_start_s']+(time-segment['source_sim_start_s'])/segment['speed'],'kind':'metal' if case['bodies'].get(first,{}).get('kind')=='sphere' else 'tile','playback_speed':segment['speed']})
    return sorted(events,key=lambda e:e['output_time_s'])


def render_audio(events, duration, destination, rate=48000):
    if len(events)>4096 or not 0<duration<=600:raise ValueError('foley event/duration budget exceeded')
    samples=[0.] * math.ceil(duration*rate)
    for event in events:
        rng=random.Random(hashlib.sha256(json.dumps(event,sort_keys=True).encode()).digest())
        metal=event['kind']=='metal';length=.20 if metal else .085;frequency=1850 if metal else 1050
        start=round(event['output_time_s']*rate)
        for i in range(round(length*rate)):
            if start+i>=len(samples):break
            t=i/rate;envelope=math.exp(-t/(.04 if metal else .017))
            value=(math.sin(2*math.pi*frequency*t)+.35*math.sin(2*math.pi*frequency*1.57*t)+.35*rng.uniform(-1,1))*envelope*.075
            samples[start+i]+=value
    with wave.open(str(destination),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate)
        output.writeframes(b''.join(struct.pack('<h',round(math.tanh(v)*20000)) for v in samples))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source');parser.add_argument('destination');args=parser.parse_args()
    from simscene.video_tools import inspect,sha
    source=Path(args.source).resolve();destination=Path(args.destination).resolve()
    if destination.exists():raise FileExistsError(destination)
    original=inspect(source);assert not original['issues'] and original['simulation_timeline']['passed']
    edit=json.loads(source.with_suffix('.edit.json').read_text());events=map_events(edit)
    if not events:raise ValueError('no frozen passive-chain contacts occur in this edit')
    audio=destination.with_suffix('.contact-foley.wav');render_audio(events,original['duration_s'],audio)
    command=['ffmpeg','-hide_banner','-loglevel','warning','-y','-i',str(source),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','160k','-shortest','-movflags','+faststart',str(destination)]
    with destination.with_suffix('.foley.ffmpeg.log').open('wb') as log:subprocess.run(command,check=True,stderr=log,stdout=subprocess.DEVNULL)
    manifest=copy.deepcopy(edit);manifest['path']=str(destination);manifest['sha256']=sha(destination)
    manifest['audio_design']={'scope':'Post-designed synthetic contact sounds timed from logged frozen-case events; not simulated acoustics','source_silent_video':str(source),'source_silent_video_sha256':sha(source),'wav':str(audio),'wav_sha256':sha(audio),'events':events,'command':command,'video':'packet copy, no re-encoding'}
    destination.with_suffix('.edit.json').write_text(json.dumps(manifest,indent=2))
    check=inspect(destination)
    assert check['decoded_frame_count']==original['decoded_frame_count'] and check['simulation_timeline']['passed'] and not check['issues']
    destination.with_suffix('.inspection.json').write_text(json.dumps(check,indent=2));print(json.dumps({'file':str(destination),'events':len(events),'duration_s':check['duration_s']}))

if __name__=='__main__':main()
