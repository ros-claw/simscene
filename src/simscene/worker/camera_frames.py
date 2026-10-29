"""Bounded camera warm-up without inventing or duplicating video frames."""
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
