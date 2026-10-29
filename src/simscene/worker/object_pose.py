"""Read dynamically spawned object positions from the current USD stage."""
def position(stage, object_id):
    from pxr import UsdGeom
    path='/World/'+object_id.replace('-','_')
    prim=stage.GetPrimAtPath(path)
    if not prim:raise RuntimeError('tracked object does not exist: '+object_id)
    return list(UsdGeom.XformCache().GetLocalToWorldTransform(prim).ExtractTranslation())
