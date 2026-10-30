"""Validated camera, encoding and presentation settings shared by every backend."""
import copy
import math

PROFILES = {
    'preview': {'resolution':[640,360], 'fps':2},
    'technical_showcase_1080p': {'resolution':[1920,1080], 'fps':30},
    'technical_showcase_4k': {'resolution':[3840,2160], 'fps':30},
}
DEFAULT_OUTPUT = {'codec':'h264','crf':18,'preset':'medium','pixel_format':'yuv420p'}
DEFAULT_RENDER = {'anti_aliasing':'dlss_quality','depth_of_field':False,'motion_blur':False,
                  'exposure_mode':'manual','exposure_ev':0.0,'renderer':'RealTimePathTracing'}

def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def resolution(value):
    if not isinstance(value,list) or len(value)!=2 or any(type(v) is not int or not 64<=v<=4096 or v%2 for v in value):
        raise ValueError('resolution must be [width,height], even integers between 64 and 4096')
    return value

def output_config(value=None):
    if value is not None and (not isinstance(value,dict) or set(value)-set(DEFAULT_OUTPUT)):
        raise ValueError('output accepts codec, crf, preset and pixel_format')
    result={**DEFAULT_OUTPUT,**(value or {})}
    if result['codec']!='h264' or result['pixel_format']!='yuv420p':raise ValueError('only h264/yuv420p is supported')
    if type(result['crf']) is not int or not 0<=result['crf']<=35:raise ValueError('crf must be an integer from 0 to 35')
    if result['preset'] not in ('ultrafast','superfast','veryfast','faster','fast','medium','slow','slower'):raise ValueError('unsupported H.264 preset')
    return result

def validate_presentation(value):
    if not isinstance(value,dict) or set(value)-{'profile','capture','output','budget','diagnostics'}:raise ValueError('unsupported presentation fields')
    profile=value.get('profile','preview')
    if profile not in PROFILES:raise ValueError('unknown presentation profile')
    capture=value.get('capture',{})
    if not isinstance(capture,dict) or set(capture)-({'resolution','fps'}|set(DEFAULT_RENDER)):raise ValueError('unsupported capture fields')
    resolution(capture.get('resolution',PROFILES[profile]['resolution']))
    if type(capture.get('fps',PROFILES[profile]['fps'])) is not int or capture.get('fps',PROFILES[profile]['fps']) not in (1,2,3,4,5,6,10,12,15,20,30):raise ValueError('capture fps must divide 60 and be at most 30')
    if capture.get('anti_aliasing','dlss_quality') not in ('dlss_quality','dlaa'):raise ValueError('anti_aliasing must be dlss_quality or dlaa')
    if capture.get('renderer','RealTimePathTracing') not in ('RealTimePathTracing','PathTracing'):raise ValueError('unsupported renderer')
    for field in ('depth_of_field','motion_blur'):
        if type(capture.get(field,False)) is not bool:raise ValueError(field+' must be boolean')
    if capture.get('exposure_mode','manual')!='manual':raise ValueError('only locked manual exposure is supported')
    if not finite(capture.get('exposure_ev',0)) or not -10<=capture.get('exposure_ev',0)<=10:raise ValueError('exposure_ev must be finite and between -10 and 10')
    output_config(value.get('output'))
    budget=value.get('budget',{})
    if not isinstance(budget,dict) or set(budget)-{'max_recording_bytes','min_free_bytes','max_cameras'}:raise ValueError('unsupported recording budget fields')
    for key,default in (('max_recording_bytes',8*1024**3),('min_free_bytes',2*1024**3),('max_cameras',2)):
        if type(budget.get(key,default)) is not int or budget.get(key,default)<1:raise ValueError('recording budgets must be positive integers')
    diagnostics=value.get('diagnostics',{})
    if not isinstance(diagnostics,dict) or set(diagnostics)-{'png_seconds','keyframe_interval_s'}:raise ValueError('unsupported diagnostics fields')
    for key,default,limit in (('png_seconds',0,10),('keyframe_interval_s',10,1200)):
        if not finite(diagnostics.get(key,default)) or not 0<=diagnostics.get(key,default)<=limit:raise ValueError('invalid diagnostic '+key)
    return value

def camera_config(scene,obj):
    presentation=scene.get('presentation')
    if presentation is not None:validate_presentation(presentation)
    presentation=presentation or {}
    profile=presentation.get('profile')
    capture=copy.deepcopy(PROFILES[profile] if profile else {'resolution':[640,480]})
    capture.update(presentation.get('capture',{}))
    optics=obj.get('camera',{})
    if not isinstance(optics,dict) or set(optics)-{'resolution','focal_length_mm','horizontal_aperture_mm','focus_distance_m','f_stop','clipping_range_m','output','capture_window'}:raise ValueError('unsupported camera fields')
    capture['resolution']=resolution(optics.get('resolution',capture['resolution']))
    capture['fps']=obj.get('record_fps',capture.get('fps'))
    for field,default,low,high in (('focal_length_mm',24,.1,2000),('horizontal_aperture_mm',36,.1,200),('focus_distance_m',5,.001,10000),('f_stop',0,0,128)):
        val=optics.get(field,default)
        if not finite(val) or not low<=val<=high:raise ValueError('invalid camera '+field)
        capture[field]=val
    clip=optics.get('clipping_range_m',[.01,10000])
    if not isinstance(clip,list) or len(clip)!=2 or not all(finite(v) for v in clip) or not 0<clip[0]<clip[1]<=1e7:raise ValueError('invalid clipping_range_m')
    window=optics.get('capture_window',{})
    if not isinstance(window,dict) or set(window)-{'start_step','end_step'} or type(window.get('start_step',0)) is not int or not 0<=window.get('start_step',0)<72000 or ('end_step' in window and (type(window['end_step']) is not int or not window.get('start_step',0)<window['end_step']<=72000)):
        raise ValueError('capture_window requires bounded integer start_step < end_step')
    if capture['fps'] and (window.get('start_step',0)%(60//capture['fps']) or window.get('end_step',0)%(60//capture['fps'])):raise ValueError('capture window must align to frame intervals')
    capture['capture_window']=window
    capture['clipping_range_m']=clip
    capture['output']=output_config(optics.get('output',presentation.get('output')))
    capture['diagnostics']=presentation.get('diagnostics',{})
    capture['budget']=presentation.get('budget',{})
    # Existing scenes keep their renderer settings until they opt into a profile.
    capture['render']={**DEFAULT_RENDER,**{k:v for k,v in presentation.get('capture',{}).items() if k in DEFAULT_RENDER}} if profile or presentation.get('capture') else None
    return capture
