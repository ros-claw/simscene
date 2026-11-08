"""Reviewed Sand3D template. No program text or paths come from scene parameters."""


def build(s3d, parameters):
    s3d.empty_scene()
    s3d.units('m')
    plate = s3d.box('guide_plate', parameters['length_m'], parameters['width_m'], parameters['thickness_m'])
    s3d.material(plate, 'painted_metal', color='#16899c', roughness=.55)
    return s3d.assembly('guide', plate)
