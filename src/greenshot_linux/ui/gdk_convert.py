"""numpy RGBA <-> GdkPixbuf conversion.

See the module docstring in test_gdk_convert.py for the byte-order
derivation (empirically confirmed, not assumed): unlike Cairo's
ARGB32, GdkPixbuf.Colorspace.RGB stores literal R, G, B, A bytes in
that order, so there's no channel swap to do here.
"""

from __future__ import annotations

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib

import numpy as np


def numpy_to_pixbuf(image: np.ndarray) -> GdkPixbuf.Pixbuf:
    """Convert an (H, W, 4) uint8 RGBA array into a GdkPixbuf."""
    height, width = image.shape[:2]
    rowstride = width * 4
    data = np.ascontiguousarray(image).tobytes()
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(data), GdkPixbuf.Colorspace.RGB, True, 8, width, height, rowstride
    )


def pixbuf_to_numpy(pixbuf: GdkPixbuf.Pixbuf) -> np.ndarray:
    """Convert a GdkPixbuf back into an (H, W, 4) uint8 RGBA array."""
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels, rowstride = pixbuf.get_n_channels(), pixbuf.get_rowstride()

    # Rows are padded to `rowstride`, and GdkPixbuf may leave the final
    # row unpadded, so the buffer can be short of height * rowstride.
    data = pixbuf.get_pixels()
    if len(data) < height * rowstride:
        data = data + bytes(height * rowstride - len(data))
    rows = np.frombuffer(data, dtype=np.uint8).reshape(height, rowstride)
    pixels = rows[:, : width * channels].reshape(height, width, channels)

    image = np.empty((height, width, 4), dtype=np.uint8)
    if channels == 4:
        image[:, :, :] = pixels
    else:
        image[:, :, :3] = pixels[:, :, :3]
        image[:, :, 3] = 255
    return image
