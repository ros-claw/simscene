"""Bounded camera warm-up without inventing or duplicating video frames."""
from contextlib import contextmanager

RENDER_FLUSH_UPDATES = 2


@contextmanager
def paused_render_barrier(*, read_state, is_playing, pause, play, pump,
                          updates=RENDER_FLUSH_UPDATES):
    """Flush RGB rendering at a fixed physical state before batch readback.

    A nonempty annotator buffer can belong to an earlier app update. Pixel
    changes are not a freshness clock: stationary scenes can have equal frames.
    SDK-specific moving-body RGB tests validate the barrier separately.
    """
    if type(updates) is not int or not 2 <= updates <= 8:
        raise ValueError('render barrier updates must be an integer from 2 to 8')
    before = read_state()
    was_playing = is_playing()
    pause()
    try:
        if is_playing():
            raise RuntimeError('camera render barrier requires a paused timeline')
        for _ in range(updates):
            pump()
            if is_playing() or read_state() != before:
                raise RuntimeError('physics advanced during camera render barrier')
        yield {'policy': 'paused-render-barrier-v1', 'application_updates': updates,
               'absolute_physics_step': before[0], 'absolute_simulation_time_s': before[1],
               'physics_unchanged': True}
        if is_playing() or read_state() != before:
            raise RuntimeError('physics advanced during camera batch readback')
    finally:
        if was_playing:
            play()


# Some Isaac render products become ready well after the initial update burst,
# especially when a headless renderer is starting on a shared GPU.
MAX_WARMUP_UPDATES = 600

def read_rgb(sensor, pump=None, max_updates=0):
    if type(max_updates) is not int or max_updates < 0:
        raise ValueError('max_updates must be a nonnegative integer')
    for attempt in range(max_updates+1):
        rgb, _ = sensor.get_data('rgb', tiled=True)
        shape = getattr(rgb, 'shape', None) if rgb is not None else None
        if rgb is not None and (shape is None or len(shape)>=2 and all(int(size)>0 for size in shape)):
            return rgb
        if attempt < max_updates:
            if pump is None:raise ValueError('pump is required to wait for camera data')
            pump()
    return None
