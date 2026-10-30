"""Explicit RGB/SDR conversion without an implicit YUV matrix before tagging.

zscale negotiates planar GBR input/output, so packed RGB is rearranged before
conversion rather than auto-converted to YUV with an unrelated matrix/range.
"""
SRGB_TO_REC709 = ('format=gbrp,zscale=matrixin=gbr:transferin=iec61966-2-1:'
    'primariesin=709:rangein=full:matrix=709:transfer=709:primaries=709:'
    'range=limited,format=yuv420p')
REC709_TO_SRGB = ('zscale=matrixin=709:transferin=709:primariesin=709:'
    'rangein=limited:matrix=gbr:transfer=iec61966-2-1:primaries=709:'
    'range=full,format=gbrp,format=rgb24')


def png_filter(stream):
    if all(stream.get(key) == 'bt709' for key in ('color_space','color_transfer','color_primaries')) and stream.get('color_range') == 'tv':
        return REC709_TO_SRGB
    return 'format=rgb24'
