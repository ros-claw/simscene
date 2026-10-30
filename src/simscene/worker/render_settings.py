"""Apply opt-in renderer settings after stage load and record their readback."""
import math

WATCH = ['/rtx/rendermode','/rtx/post/aa/op','/rtx/post/dlss/execMode',
         '/rtx/post/dof/enabled','/rtx/post/motionblur/enabled','/rtx/post/histogram/enabled',
         '/rtx/post/tonemap/op','/rtx/post/tonemap/filmIso','/rtx/post/tonemap/exposureTime',
         '/rtx/post/tonemap/fNumber','/rtx/post/tonemap/colorMode','/rtx/post/tonemap/enableSrgbToGamma']

def readback(settings):
    return {key:settings.get(key) for key in WATCH}

def configure(settings,config):
    before=readback(settings)
    if not config:return {'requested':None,'before':before,'after_stage':before}
    desired={'/rtx/rendermode':config['renderer'],'/rtx/post/aa/op':3 if config['anti_aliasing']=='dlss_quality' else 4,
             '/rtx/post/dof/enabled':config['depth_of_field'],'/rtx/post/motionblur/enabled':config['motion_blur'],
             '/rtx/post/histogram/enabled':False,'/rtx/post/tonemap/op':6,
             '/rtx/post/tonemap/filmIso':100.0*2**config['exposure_ev'],
             '/rtx/post/tonemap/exposureTime':1/60,'/rtx/post/tonemap/fNumber':4.0,
             '/rtx/post/tonemap/colorMode':0,'/rtx/post/tonemap/enableSrgbToGamma':True}
    if config['anti_aliasing']=='dlss_quality':desired['/rtx/post/dlss/execMode']=2
    for key,value in desired.items():
        if settings.get(key) is None:raise RuntimeError('requested renderer option is unavailable: '+key)
        settings.set(key,value)
    check(settings,desired)
    return {'requested':config,'before':before,'after_stage':readback(settings),'expected':desired,
            'color_pipeline':'RTX tonemap sRGB display output -> RGB annotator -> FFmpeg sRGB/BT.709 conversion'}

def check(settings,desired):
    for key,value in desired.items():
        actual=settings.get(key)
        if isinstance(value,float):match=isinstance(actual,(float,int)) and math.isclose(actual,value,rel_tol=1e-5,abs_tol=1e-6)
        else:match=actual==value
        if not match:raise RuntimeError(f'renderer setting overridden: {key}: requested {value}, actual {actual}')
