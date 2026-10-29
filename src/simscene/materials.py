"""Author an explicit USD Preview Surface material override."""
def apply_material(stage, prim, name, config):
    from pxr import Gf,Sdf,UsdShade
    material=UsdShade.Material.Define(stage,'/World/Looks/'+name.replace('-','_'))
    shader=UsdShade.Shader.Define(stage,material.GetPath().AppendChild('PreviewSurface'))
    shader.CreateIdAttr('UsdPreviewSurface')
    color=config.get('color',[.5,.5,.5]); emission=config.get('emissive',[0,0,0])
    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput('emissiveColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emission))
    for name,value in [('roughness',config.get('roughness',.5)),('metallic',config.get('metallic',0)),('opacity',config.get('opacity',1))]:
        shader.CreateInput(name,Sdf.ValueTypeNames.Float).Set(float(value))
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material,bindingStrength=UsdShade.Tokens.strongerThanDescendants)
