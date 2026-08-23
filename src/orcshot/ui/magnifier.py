"""Drawing the region-select magnifier loupe: a circular, nearest-
neighbor-scaled zoom of the pixels right around the cursor, with a
precision crosshair marking the exact cursor pixel. Positioning/sizing
math lives in core/magnifier.py (pure, unit tested); this module is
the Cairo drawing itself - headlessly testable like ui/render.py,
since Cairo needs no X11/display connection, unlike ui/region_select.py
(GTK event-loop glue, verified live instead).

Ported from the Windows source's DrawZoom (Greenshot/Forms/
CaptureForm.cs, ~line 866): a 2px white ring border around the
circular preview, then a black crosshair - a small gap exactly at the
center (the cursor's own pixel) rather than one continuous cross -
outlined in white for contrast against whatever's underneath. The
outline-for-contrast idea is kept; the exact pixel-offset arithmetic
for the gap/outline thickness is simplified to fixed pixel counts
rather than scaled from the zoom factor, since at this widget's size
the difference isn't visually meaningful and fixed constants are far
simpler to reason about.
"""

from __future__ import annotations

import math
from typing import Tuple

import cairo
import numpy as np

from orcshot.core.magnifier import magnifier_constants, magnifier_source_rect
from orcshot.ui.cairo_convert import numpy_to_cairo_surface

Point = Tuple[int, int]


def _clamped_crop(image: np.ndarray, cursor: Point, size: int) -> Tuple[np.ndarray, Point]:
    """The ``size`` x ``size`` crop centered on ``cursor``, clamped to
    ``image``'s real bounds (the cursor can be near a screen edge, where
    a naive centered crop would read out of bounds) - along with where,
    within that crop, the cursor's own pixel actually landed (off-
    center whenever clamping shifted the crop).
    """
    img_h, img_w = image.shape[:2]
    rect = magnifier_source_rect(cursor, size)
    left = max(0, min(rect.left, img_w - size)) if img_w >= size else 0
    top = max(0, min(rect.top, img_h - size)) if img_h >= size else 0
    right = min(img_w, left + size)
    bottom = min(img_h, top + size)
    crop = image[top:bottom, left:right]
    cursor_in_crop = (cursor[0] - left, cursor[1] - top)
    return crop, cursor_in_crop


def draw_magnifier(
    ctx: cairo.Context, frozen_image: np.ndarray, cursor: Point, offset: Point, diameter: int,
    source_size: int = None, dest_pos: Point = None,
) -> None:
    """Draws the loupe at ``dest_pos`` (or ``cursor`` if not given) +
    ``offset`` (top-left corner), ``diameter`` pixels across,
    previewing a ``source_size`` x ``source_size`` crop of
    ``frozen_image`` centered on ``cursor``.

    ``cursor`` and ``dest_pos`` are separate parameters because they
    don't always share a coordinate space. region_select.py passes the
    whole virtual-screen backdrop as ``frozen_image``, where the
    cursor's position on the drawing context *is* also its position
    within that backdrop - there, the default (``dest_pos=None``,
    falling back to ``cursor``) is correct and this parameter can be
    ignored. eyedropper.py/eyedropper_wayland.py instead pass an
    already-small, pre-cropped patch as ``frozen_image`` (for X11: a
    small live grab taken fresh each motion event rather than a full
    frozen backdrop at all; for Wayland: a slice of one), where the
    cursor's position *within that tiny patch* has nothing to do with
    where the loupe should actually be drawn on the much larger overlay
    window - passing the real on-window cursor position as ``dest_pos``
    is required there. Confirmed live: omitting this made the eyedropper
    loupe always render pinned near the drawing context's own origin,
    regardless of the real cursor position.
    """
    constants = magnifier_constants()
    if source_size is None:
        source_size = constants["patch_size"]
    ring_width = constants["loupe_ring_width"]
    crosshair_gap = constants["loupe_crosshair_gap"]
    crosshair_thickness = constants["loupe_crosshair_thickness"]

    crop, cursor_in_crop = _clamped_crop(frozen_image, cursor, source_size)
    crop_h, crop_w = crop.shape[:2]
    if crop_h == 0 or crop_w == 0:
        return

    if dest_pos is None:
        dest_pos = cursor
    dest_x, dest_y = dest_pos[0] + offset[0], dest_pos[1] + offset[1]
    radius = diameter / 2
    center_x, center_y = dest_x + radius, dest_y + radius

    ctx.save()
    ctx.arc(center_x, center_y, radius, 0, 2 * math.pi)
    ctx.clip()

    source_surface = numpy_to_cairo_surface(crop)
    scale_x, scale_y = diameter / crop_w, diameter / crop_h
    ctx.translate(dest_x, dest_y)
    ctx.scale(scale_x, scale_y)
    pattern = cairo.SurfacePattern(source_surface)
    pattern.set_filter(cairo.FILTER_NEAREST)
    ctx.set_source(pattern)
    ctx.paint()
    ctx.restore()

    ctx.save()
    ctx.set_line_width(ring_width)
    ctx.set_source_rgb(1, 1, 1)
    ctx.arc(center_x, center_y, radius - ring_width / 2, 0, 2 * math.pi)
    ctx.stroke()
    ctx.restore()

    # Crosshair, exactly at the cursor's own pixel within the zoomed
    # preview (not necessarily the geometric center, if the crop was
    # clamped near a screen edge) - a small gap at the middle rather
    # than one continuous cross, outlined in white for contrast.
    cross_x = dest_x + (cursor_in_crop[0] + 0.5) * scale_x
    cross_y = dest_y + (cursor_in_crop[1] + 0.5) * scale_y
    arm = radius * 0.7
    gap = crosshair_gap
    ctx.save()
    ctx.arc(center_x, center_y, radius - ring_width, 0, 2 * math.pi)
    ctx.clip()
    for outline, width, color in ((True, crosshair_thickness + 2, (1, 1, 1)), (False, crosshair_thickness, (0, 0, 0))):
        ctx.set_line_width(width)
        ctx.set_source_rgb(*color)
        ctx.move_to(cross_x, cross_y - arm)
        ctx.line_to(cross_x, cross_y - gap)
        ctx.move_to(cross_x, cross_y + gap)
        ctx.line_to(cross_x, cross_y + arm)
        ctx.move_to(cross_x - arm, cross_y)
        ctx.line_to(cross_x - gap, cross_y)
        ctx.move_to(cross_x + gap, cross_y)
        ctx.line_to(cross_x + arm, cross_y)
        ctx.stroke()
    ctx.restore()
