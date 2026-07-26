"""Obfuscation filters operating on (H, W, 4) uint8 RGBA numpy arrays.

Behavioral ports of the filters in the Windows source's
Greenshot.Editor/Drawing/Filters; the box blur follows
ImageHelper.ApplyBoxBlur (the portable non-GDI+ path).
"""

from __future__ import annotations

import numpy as np

from greenshot_linux.core.geometry import Rect


def _image_bounds(image: np.ndarray) -> Rect:
    return Rect(left=0, top=0, right=image.shape[1], bottom=image.shape[0])


def _box_blur_pass(region: np.ndarray, half: int, axis: int) -> np.ndarray:
    # Sliding-window mean with the window clipped at the region edges
    # (divide by the actual window size, not the nominal one) and
    # truncating integer division, matching the Windows reference.
    n = region.shape[axis]
    sums = np.cumsum(region, axis=axis, dtype=np.int32)
    zero_shape = list(region.shape)
    zero_shape[axis] = 1
    sums = np.concatenate([np.zeros(zero_shape, dtype=np.int32), sums], axis=axis)

    positions = np.arange(n)
    lo = np.maximum(positions - half, 0)
    hi = np.minimum(positions + half + 1, n)
    window_sums = np.take(sums, hi, axis=axis) - np.take(sums, lo, axis=axis)

    hits_shape = [1, 1, 1]
    hits_shape[axis] = n
    hits = (hi - lo).reshape(hits_shape)
    return (window_sums // hits).astype(np.uint8)


def box_blur(image: np.ndarray, rect: Rect, radius: int) -> np.ndarray:
    """Blur the part of ``image`` covered by ``rect``; returns a new array.

    Even radii are bumped to the next odd value and a radius <= 1 is a
    no-op, as in the Windows implementation. The blur only reads pixels
    inside the rect, so content outside it cannot bleed in.
    """
    out = image.copy()
    apply_rect = rect.intersect(_image_bounds(image))
    if apply_rect is None:
        return out

    window = radius + 1 if radius % 2 == 0 else radius
    if window <= 1:
        return out
    half = window // 2

    region = out[apply_rect.top:apply_rect.bottom, apply_rect.left:apply_rect.right]
    # Two horizontal+vertical rounds, not the textbook three: the Windows
    # source found 2x the closest match to the GDI+ blur it emulates.
    for axis in (1, 0, 1, 0):
        region[...] = _box_blur_pass(region, half, axis)
    return out
