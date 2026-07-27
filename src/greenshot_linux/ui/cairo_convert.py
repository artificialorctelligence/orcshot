"""numpy RGBA <-> Cairo ARGB32 conversion.

See the module docstring in test_cairo_convert.py for the byte-order
derivation (empirically confirmed, not assumed) and the documented
premultiplication limitation.
"""

from __future__ import annotations

import cairo
import numpy as np


def numpy_to_cairo_surface(image: np.ndarray) -> cairo.ImageSurface:
    """Convert an (H, W, 4) uint8 RGBA array into a Cairo ARGB32 surface."""
    height, width = image.shape[:2]
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, width)

    buf = np.zeros((height, stride // 4, 4), dtype=np.uint8)
    buf[:, :width, 0] = image[:, :, 2]  # B
    buf[:, :width, 1] = image[:, :, 1]  # G
    buf[:, :width, 2] = image[:, :, 0]  # R
    buf[:, :width, 3] = image[:, :, 3]  # A

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

    image = np.empty((height, width, 4), dtype=np.uint8)
    image[:, :, 0] = buf[:, :, 2]  # R
    image[:, :, 1] = buf[:, :, 1]  # G
    image[:, :, 2] = buf[:, :, 0]  # B
    image[:, :, 3] = buf[:, :, 3]  # A
    return image
