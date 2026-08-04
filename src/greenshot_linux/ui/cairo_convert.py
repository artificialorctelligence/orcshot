"""numpy RGBA <-> Cairo ARGB32 conversion.

See the module docstring in test_cairo_convert.py for the byte-order
derivation (empirically confirmed, not assumed) and how premultiplied
alpha is handled.
"""

from __future__ import annotations

import cairo
import numpy as np


def _premultiply(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """RGB scaled by alpha/255, matching Cairo's FORMAT_ARGB32 contract
    (premultiplied alpha) - the numpy RGBA convention used everywhere
    else in this codebase is straight alpha (see capture/x11_cursor.py's
    module docstring), so this conversion is needed on the way into a
    Cairo surface, with _unpremultiply below as its inverse on the way
    out. Same per-channel-loop structure as x11_cursor.py's own
    _unpremultiply, for consistency.
    """
    alpha_f = alpha.astype(np.float32) / 255.0
    result = np.empty_like(rgb)
    for channel in range(3):
        result[:, :, channel] = np.round(rgb[:, :, channel].astype(np.float32) * alpha_f).astype(np.uint8)
    return result


def _unpremultiply(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Inverse of _premultiply - straight alpha, matching this
    codebase's numpy RGBA convention. Identical algorithm to
    x11_cursor.py's own _unpremultiply (int8 truncation on the way
    back out means a genuinely translucent pixel can be off by one
    per channel after a round trip - inherent to 8-bit premultiplied
    alpha, not something either implementation can avoid).
    """
    alpha_f = alpha.astype(np.float32)
    nonzero = alpha_f > 0
    result = np.zeros_like(rgb)
    for channel in range(3):
        straight = np.zeros_like(alpha_f)
        premultiplied = rgb[:, :, channel][nonzero].astype(np.float32)
        straight[nonzero] = premultiplied * 255.0 / alpha_f[nonzero]
        result[:, :, channel] = np.clip(straight, 0, 255).astype(np.uint8)
    return result


def numpy_to_cairo_surface(image: np.ndarray) -> cairo.ImageSurface:
    """Convert an (H, W, 4) uint8 RGBA array into a Cairo ARGB32 surface."""
    height, width = image.shape[:2]
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, width)

    alpha = image[:, :, 3]
    premultiplied = _premultiply(image[:, :, :3], alpha)

    buf = np.zeros((height, stride // 4, 4), dtype=np.uint8)
    buf[:, :width, 0] = premultiplied[:, :, 2]  # B
    buf[:, :width, 1] = premultiplied[:, :, 1]  # G
    buf[:, :width, 2] = premultiplied[:, :, 0]  # R
    buf[:, :width, 3] = alpha

    return cairo.ImageSurface.create_for_data(
        bytearray(buf.tobytes()), cairo.FORMAT_ARGB32, width, height, stride
    )


def cairo_surface_to_numpy(surface: cairo.ImageSurface) -> np.ndarray:
    """Convert a Cairo ARGB32 surface back into an (H, W, 4) uint8 RGBA array."""
    surface.flush()
    width, height = surface.get_width(), surface.get_height()
    stride = surface.get_stride()

    raw = np.frombuffer(surface.get_data(), dtype=np.uint8)
    buf = raw.reshape(height, stride // 4, 4)[:, :width]

    alpha = buf[:, :, 3]
    premultiplied_rgb = np.stack([buf[:, :, 2], buf[:, :, 1], buf[:, :, 0]], axis=-1)  # R, G, B
    straight_rgb = _unpremultiply(premultiplied_rgb, alpha)

    image = np.empty((height, width, 4), dtype=np.uint8)
    image[:, :, :3] = straight_rgb
    image[:, :, 3] = alpha
    return image
