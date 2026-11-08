"""Apply opt-in renderer settings after stage load and record their readback."""
import math

WATCH = ['/rtx/rendermode','/rtx/post/aa/op','/rtx/post/dlss/execMode',
         '/rtx/post/dof/enabled','/rtx/post/motionblur/enabled','/rtx/post/histogram/enabled',
         '/rtx/post/tonemap/op','/rtx/post/tonemap/filmIso','/rtx/post/tonemap/exposureTime',
         '/rtx/post/tonemap/fNumber','/rtx/post/tonemap/colorMode','/rtx/post/tonemap/enableSrgbToGamma']

def readback(settings):
    return {key:settings.get(key) for key in WATCH}

def desired_settings(config):
    if not config:return {}
    desired={'/rtx/rendermode':config['renderer'],'/rtx/post/aa/op':3 if config['anti_aliasing']=='dlss_quality' else 4,
             '/rtx/post/dof/enabled':config['depth_of_field'],'/rtx/post/motionblur/enabled':config['motion_blur'],
             '/rtx/post/histogram/enabled':False,'/rtx/post/tonemap/op':6,
             '/rtx/post/tonemap/filmIso':100.0*2**config['exposure_ev'],
             '/rtx/post/tonemap/exposureTime':1/60,'/rtx/post/tonemap/fNumber':4.0,
             '/rtx/post/tonemap/colorMode':0,'/rtx/post/tonemap/enableSrgbToGamma':True}
    if config['anti_aliasing']=='dlss_quality':desired['/rtx/post/dlss/execMode']=2
    return desired

def wait_for_options(settings,desired,update=None,max_updates=120):
    """Wait for real renderer option registration without creating any keys.

    The caller owns the application-update callback and must keep physics
    stopped. Missing options still fail, and no requested value is written
    until every requested option has actually been registered.
    """
    if type(max_updates) is not int or max_updates<0:
        raise ValueError('renderer registration update bound must be a nonnegative integer')
    initial_missing=[key for key in desired if settings.get(key) is None]
    for count in range(max_updates+1):
        missing=[key for key in desired if settings.get(key) is None]
        if not missing:
            return {'initial_missing_options':initial_missing,'updates':count,
                    'all_requested_options_registered':True,'created_missing_options':False}
        if update is None or count==max_updates:
            raise RuntimeError('requested renderer option is unavailable after '+str(count)+' updates: '+', '.join(missing))
        update()

def configure(settings,config,update=None,max_updates=120):
    before=readback(settings)
    if not config:return {'requested':None,'before':before,'after_stage':before}
    desired=desired_settings(config)
    registration=wait_for_options(settings,desired,update,max_updates)
    for key,value in desired.items():
        if settings.get(key) is None:raise RuntimeError('requested renderer option is unavailable: '+key)
        settings.set(key,value)
    check(settings,desired)
    return {'requested':config,'before':before,'after_stage':readback(settings),'expected':desired,'registration':registration,
            'color_pipeline':'RTX tonemap sRGB display output -> RGB annotator -> FFmpeg sRGB/BT.709 conversion'}

def check(settings,desired):
    for key,value in desired.items():
        actual=settings.get(key)
        if isinstance(value,float):match=isinstance(actual,(float,int)) and math.isclose(actual,value,rel_tol=1e-5,abs_tol=1e-6)
        else:match=actual==value
        if not match:raise RuntimeError(f'renderer setting overridden: {key}: requested {value}, actual {actual}')
