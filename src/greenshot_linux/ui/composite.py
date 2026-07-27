"""Flatten a base image plus an annotation Layer into one final image,
for export (clipboard/file save). Reuses the exact rendering pipeline
the live editor uses (numpy_to_cairo_surface + render_layer +
cairo_surface_to_numpy), so what gets exported is pixel-identical to
what was on screen - not a second, potentially-diverging render path.
"""

from __future__ import annotations

import cairo
import numpy as np

from greenshot_linux.core.drawing import Layer
from greenshot_linux.ui.cairo_convert import cairo_surface_to_numpy, numpy_to_cairo_surface
from greenshot_linux.ui.render import render_layer


def composite_to_numpy(base_image: np.ndarray, layer: Layer, rng=None) -> np.ndarray:
    surface = numpy_to_cairo_surface(base_image)
    ctx = cairo.Context(surface)
    render_layer(ctx, layer, base_image=base_image, rng=rng)
    return cairo_surface_to_numpy(surface)
