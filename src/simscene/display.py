"""USD seven-segment displays for live, measured counts.

This authoring helper does not itself invent or infer a count. A caller must
supply the measured value and describe its source in the surrounding scene.
"""
from pxr import Gf, Sdf, UsdGeom, UsdShade

SEGMENTS={0:'abcedf',1:'bc',2:'abged',3:'abgcd',4:'fgbc',5:'afgcd',6:'afgecd',7:'abc',8:'abcdefg',9:'abfgcd'}
LAYOUT={
    'a':(0,.05,.044,.006),'g':(0,0,.044,.006),'d':(0,-.05,.044,.006),
    'f':(-.025,.025,.006,.044),'b':(.025,.025,.006,.044),
    'e':(-.025,-.025,.006,.044),'c':(.025,-.025,.006,.044),
}


def create(stage,path,digits=3,color=(.05,1.,.1)):
    if type(digits) is not int or not 1<=digits<=6:raise ValueError('digits must be between 1 and 6')
    if stage.GetPrimAtPath(path):raise ValueError('display path already exists')
    root=UsdGeom.Xform.Define(stage,path)
    material=UsdShade.Material.Define(stage,path+'/Material');shader=UsdShade.Shader.Define(stage,path+'/Material/Surface')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput('emissiveColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
    for digit in range(digits):
        group=UsdGeom.Xform.Define(stage,f'{path}/digit_{digit}')
        group.AddTranslateOp().Set(Gf.Vec3d(digit*.075,0,0))
        for segment,(x,z,width,height) in LAYOUT.items():
            cube=UsdGeom.Cube.Define(stage,f'{path}/digit_{digit}/{segment}');cube.CreateSizeAttr(1)
            cube.AddTranslateOp().Set(Gf.Vec3d(x,0,z));cube.AddScaleOp().Set(Gf.Vec3f(width,.008,height))
            UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(material)
    set_value(stage,path,digits,0)
    return root


def set_value(stage,path,digits,value):
    if type(value) is not int or value<0 or value>=10**digits:raise ValueError('value does not fit the display')
    text=str(value).rjust(digits)
    for index,char in enumerate(text):
        active=SEGMENTS[int(char)] if char!=' ' else ''
        for segment in LAYOUT:
            prim=stage.GetPrimAtPath(f'{path}/digit_{index}/{segment}')
            if not prim:raise ValueError('display segment missing')
            UsdGeom.Imageable(prim).GetVisibilityAttr().Set('inherited' if segment in active else 'invisible')


def set_overflow(stage,path,digits):
    """Show dashes instead of silently displaying an incorrect number."""
    for index in range(digits):
        for segment in LAYOUT:
            prim=stage.GetPrimAtPath(f'{path}/digit_{index}/{segment}')
            if not prim:raise ValueError('display segment missing')
            UsdGeom.Imageable(prim).GetVisibilityAttr().Set('inherited' if segment=='g' else 'invisible')
