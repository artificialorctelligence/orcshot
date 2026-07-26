"""Obfuscation filters operating on (H, W, 4) uint8 RGBA numpy arrays.

Behavioral ports of the filters in the Windows source's
Greenshot.Editor/Drawing/Filters; the box blur follows
ImageHelper.ApplyBoxBlur (the portable non-GDI+ path).
"""

from __future__ import annotations

import secrets

import numpy as np

from greenshot_linux.core.geometry import Rect


def _default_rng() -> np.random.Generator:
    # Seeded from the OS CSPRNG each call: the pixelation noise exists to
    # defeat depixelation attacks, so the stream must not be predictable
    # across invocations. (The Windows source uses a crypto RNG directly;
    # PCG64 seeded with 128 fresh bits is the numpy-vectorizable stand-in.)
    return np.random.default_rng(secrets.randbits(128))


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


def _jittered_boundaries(length: int, pixel_size: int, jitter: int, rng) -> list[int]:
    bounds = [0]
    position = 0
    while position < length:
        step = pixel_size + int(rng.integers(-jitter, jitter + 1))
        if step < 2:
            step = 2
        position += step
        if position >= length:
            bounds.append(length)
            break
        bounds.append(position)
    return bounds


def _pixelize_band(band: np.ndarray, x_bounds: np.ndarray, rng) -> None:
    band_height = band.shape[0]
    starts = x_bounds[:-1]
    widths = np.diff(x_bounds)

    column_sums = band.sum(axis=0, dtype=np.int64)
    block_sums = np.add.reduceat(column_sums, starts, axis=0)
    averages = block_sums // (widths * band_height)[:, None]

    column_min = band.min(axis=0)
    column_max = band.max(axis=0)
    block_min = np.minimum.reduceat(column_min, starts, axis=0).astype(np.int64)
    block_max = np.maximum.reduceat(column_max, starts, axis=0).astype(np.int64)
    max_diff = (block_max[:, :3] - block_min[:, :3]).max(axis=1)

    # Noise is scaled by the color variation inside each block, so solid
    # blocks come out as their exact average with no noise at all.
    scale = np.minimum(1.0, max_diff / 32.0)
    block_noise_range = np.round(12 * scale).astype(np.int64)[:, None]
    pixel_noise_range = np.round(3 * scale).astype(np.int64)

    block_offsets = rng.integers(
        -block_noise_range, block_noise_range + 1, size=(len(starts), 3)
    )

    average_columns = np.repeat(averages, widths, axis=0)
    offset_columns = np.repeat(block_offsets, widths, axis=0)
    noise_range_columns = np.repeat(pixel_noise_range, widths)

    pixel_noise = rng.integers(
        -noise_range_columns[None, :, None],
        noise_range_columns[None, :, None] + 1,
        size=(band_height, band.shape[1], 3),
    )
    rgb = average_columns[None, :, :3] + offset_columns[None] + pixel_noise
    band[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    # Alpha gets the block average without noise, as in the Windows source.
    band[:, :, 3] = average_columns[:, 3].astype(np.uint8)[None, :]


def pixelize(
    image: np.ndarray, rect: Rect, pixel_size: int, rng=None
) -> np.ndarray:
    """Pixelate the part of ``image`` covered by ``rect``; returns a new array.

    Behavioral port of the Windows PixelizationFilter: a jittered block
    grid anchored at the rect origin, each block filled with its average
    color plus variation-scaled random noise. ``rng`` is injectable for
    tests; it must provide numpy's ``Generator.integers`` interface.
    """
    out = image.copy()
    apply_rect = rect.intersect(_image_bounds(image))
    if apply_rect is None or pixel_size <= 1:
        return out
    if rng is None:
        rng = _default_rng()
    pixel_size = min(pixel_size, apply_rect.width, apply_rect.height)

    region = out[apply_rect.top:apply_rect.bottom, apply_rect.left:apply_rect.right]
    height, width = region.shape[:2]
    jitter = max(1, pixel_size // 3)

    y_bounds = _jittered_boundaries(height, pixel_size, jitter, rng)
    for band_index in range(len(y_bounds) - 1):
        band = region[y_bounds[band_index]:y_bounds[band_index + 1]]
        x_bounds = np.array(_jittered_boundaries(width, pixel_size, jitter, rng))
        _pixelize_band(band, x_bounds, rng)
    return out
