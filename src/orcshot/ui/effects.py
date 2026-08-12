"""Whole-image effects that need GTK/Cairo (resize resampling, torn-
edge path masking) - everything else lives in core/effects.py as pure
numpy. Not unit tested for the same reason other Cairo/GdkPixbuf-
touching ui/ modules aren't - verified live instead (see REQUIREMENTS.md's
"Whole-image effects" section).
"""

from __future__ import annotations

import random

import cairo
import gi
import numpy as np

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

from orcshot.core.effects import drop_shadow_image
from orcshot.ui.cairo_convert import cairo_surface_to_numpy, numpy_to_cairo_surface
from orcshot.ui.gdk_convert import numpy_to_pixbuf, pixbuf_to_numpy


def resize_image(image: np.ndarray, new_width: int, new_height: int) -> np.ndarray:
    """Good-faith equivalent of ImageHelper.ResizeImage
    (ImageHelper.cs:1421-1550), which resamples via GDI+'s
    InterpolationMode.HighQualityBicubic. GdkPixbuf has no bicubic
    filter; GdkPixbuf.InterpType.HYPER is its own highest-quality
    option (GdkPixbuf's docs recommend it specifically for
    downscaling) - the closest available equivalent without adding a
    new dependency, not a pixel-identical port of GDI+'s exact
    resampling kernel.
    """
    pixbuf = numpy_to_pixbuf(image)
    scaled = pixbuf.scale_simple(new_width, new_height, GdkPixbuf.InterpType.HYPER)
    return pixbuf_to_numpy(scaled)


def _torn_points(start: float, end: float, count: int, tooth_height: int):
    if count <= 0:
        return []
    step = (end - start) / count
    return [
        (start + step * i, random.randint(1, tooth_height - 1) if tooth_height > 1 else 0)
        for i in range(1, count)
    ]


def torn_edge_image(
    image: np.ndarray,
    tooth_height: int = 12,
    horizontal_tooth_range: int = 20,
    vertical_tooth_range: int = 20,
    edges=(True, True, True, True),  # (top, right, bottom, left) - TornEdgeEffect.cs's order
    generate_shadow: bool = True,
    shadow_size: int = 7,
    darkness: float = 0.6,
    offset=(-1, -1),
) -> np.ndarray:
    """Whole-image torn-edge effect - a good-faith reproduction of the
    *documented* algorithm behind TornEdgeEffect/ImageHelper.CreateTornEdge
    (ImageHelper.cs:372-486): builds a jagged path around the image
    (each edge divided into ``*_tooth_range``-wide regions, each region's
    boundary randomly displaced inward by ``[1, tooth_height)``, per
    Windows' own unseeded ``Random.Next`` - so, like Windows, every
    application looks organically different, which is the intended
    "torn" look, not nondeterminism to fix), fills it with the source
    image (giving anti-aliased jagged edges), then optionally pipes
    the result through drop_shadow_image, matching
    TornEdgeEffect extending DropShadowEffect with ``GenerateShadow``
    defaulting true. Uses the same defaults as Windows (tooth height
    12, tooth range 20, shadow size 7, all 4 edges torn).
    """
    h, w = image.shape[:2]
    pad = shadow_size
    canvas_w, canvas_h = w + pad * 2, h + pad * 2
    top_edge, right_edge, bottom_edge, left_edge = edges
    left_x, top_y = pad, pad
    right_x, bottom_y = pad + w, pad + h

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas_w, canvas_h)
    ctx = cairo.Context(surface)

    top_count = max(1, round(w / horizontal_tooth_range))
    side_count = max(1, round(h / vertical_tooth_range))

    ctx.move_to(left_x, top_y)
    if top_edge:
        for pos, jitter in _torn_points(left_x, right_x, top_count, tooth_height):
            ctx.line_to(pos, top_y + jitter)
    ctx.line_to(right_x, top_y)

    if right_edge:
        for pos, jitter in _torn_points(top_y, bottom_y, side_count, tooth_height):
            ctx.line_to(right_x - jitter, pos)
    ctx.line_to(right_x, bottom_y)

    if bottom_edge:
        for pos, jitter in _torn_points(right_x, left_x, top_count, tooth_height):
            ctx.line_to(pos, bottom_y - jitter)
    ctx.line_to(left_x, bottom_y)

    if left_edge:
        for pos, jitter in _torn_points(bottom_y, top_y, side_count, tooth_height):
            ctx.line_to(left_x + jitter, pos)
    ctx.close_path()

    image_surface = numpy_to_cairo_surface(image)
    ctx.set_source_surface(image_surface, pad, pad)
    ctx.fill()

    result = cairo_surface_to_numpy(surface)
    if generate_shadow:
        result = drop_shadow_image(result, darkness=darkness, size=shadow_size, offset=offset)
    return result
