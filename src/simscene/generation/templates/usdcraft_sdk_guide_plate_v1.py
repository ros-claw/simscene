"""Only this shipped SDK authoring program may be compiled by the adapter."""
import json
from pathlib import Path
from sdk import (ArticulatedObject, BaseMode, Box, Inertial, Origin,
                 RigidBodyProperties, TestContext, TestReport, estimate_mass_from_density)

PARAMETERS = json.loads(Path(__file__).with_name('dimensions.json').read_text())
LENGTH_M = PARAMETERS['length_m']
WIDTH_M = PARAMETERS['width_m']
THICKNESS_M = PARAMETERS['thickness_m']
DENSITY_KG_M3 = 650.


def build_object_model() -> ArticulatedObject:
    model = ArticulatedObject(name='simscene_usdcraft_guide_plate', base_mode=BaseMode.FLOATING)
    model.meta['mode'] = 'static'
    shape = Box((LENGTH_M, WIDTH_M, THICKNESS_M))
    model.physics_material('contact', static_friction=.55, dynamic_friction=.4,
                           restitution=.05, density=DENSITY_KG_M3)
    finish = model.material('wood', rgba=(.5, .3, .16, 1.), roughness=.65)
    body = model.part('body', inertial=Inertial.from_geometry(
        shape, mass=estimate_mass_from_density(shape, DENSITY_KG_M3),
        origin=Origin(xyz=(0., 0., THICKNESS_M / 2))),
        rigid_body=RigidBodyProperties(physics_material='contact'))
    body.visual(shape, origin=Origin(xyz=(0., 0., THICKNESS_M / 2)), material=finish, name='plate')
    return model


object_model = build_object_model()


def run_tests() -> TestReport:
    ctx = TestContext(object_model)
    bounds = ctx.part_world_aabb('body')
    ctx.check('grounded plate', bounds is not None and abs(bounds[0][2]) < 1e-6)
    if bounds is not None:
        ctx.check('specified length', abs(bounds[1][0] - bounds[0][0] - LENGTH_M) < 1e-6)
        ctx.check('specified width', abs(bounds[1][1] - bounds[0][1] - WIDTH_M) < 1e-6)
        ctx.check('specified thickness', abs(bounds[1][2] - bounds[0][2] - THICKNESS_M) < 1e-6)
    return ctx.report()
