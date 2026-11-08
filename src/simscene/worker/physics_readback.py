"""Passive USD physics-scene readback; this module never changes settings."""
import math

SCENE_PATH = '/World/PhysicsScene'
TIMESTEP_ATTRIBUTE = 'physxScene:timeStepsPerSecond'


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def read_physics_settings(stage, requested_device):
    """Read loaded scene values and validate an explicit dynamics-device request.

    The timestep is reported only when its attribute has an authored value;
    schema defaults and the worker's configured update frequency are not proof.
    This records USD settings, not independent GPU/CPU execution telemetry.
    """
    if requested_device not in ('default', 'cpu', 'gpu'):
        raise ValueError('invalid requested physics device')
    prim = stage.GetPrimAtPath(SCENE_PATH)

    def attribute(name):
        return prim.GetAttribute(name) if prim else None

    def value(name):
        attr = attribute(name)
        return attr.Get() if attr else None

    enabled = value('physxScene:enableGPUDynamics')
    enabled = enabled if type(enabled) is bool else None
    broadphase = value('physxScene:broadphaseType')
    broadphase = str(broadphase) if broadphase is not None else None
    direction = value('physics:gravityDirection')
    if direction is not None:
        try:
            direction = [_number(component) for component in direction]
            if len(direction) != 3 or any(component is None for component in direction):
                direction = None
        except TypeError:
            direction = None
    timestep = attribute(TIMESTEP_ATTRIBUTE)
    authored_timestep = (_number(timestep.Get()) if timestep and timestep.HasAuthoredValueOpinion() else None)
    result = {'scene_prim_path': SCENE_PATH, 'requested_device': requested_device,
              'enable_gpu_dynamics': enabled, 'broadphase_type': broadphase,
              'gravity_direction': direction,
              'gravity_magnitude_m_s2': _number(value('physics:gravityMagnitude')),
              'authored_time_steps_per_second': authored_timestep,
              'timestep_attribute': TIMESTEP_ATTRIBUTE if authored_timestep is not None else None,
              'request_matches_observation': None if requested_device == 'default' else enabled is (requested_device == 'gpu'),
              'scope': 'loaded USD physics scene settings; not independent execution-device telemetry'}
    if requested_device != 'default' and enabled is not (requested_device == 'gpu'):
        error = ValueError(f'physics device request {requested_device} differs from observed enableGPUDynamics={enabled}')
        error.physics_settings = result
        raise error
    return result
