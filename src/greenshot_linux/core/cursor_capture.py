"""Where a captured mouse cursor lands in a screenshot - the pure
placement math behind cursor auto-capture (see capture/cursor.py for
the X11 mechanism that supplies these numbers, and ui/capture_modes.py
etc. for wiring it into each capture mode).

Faithful port of WindowCapture.CaptureCursor's placement formula
(Greenshot.Base/Core/WindowCapture.cs:81-97): the cursor's on-screen
hotspot position, minus the cursor image's own hotspot offset within
its bitmap, minus the capture region's own screen origin, gives the
cursor bitmap's top-left corner relative to the captured image.
"""

from __future__ import annotations

import numpy as np

from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import CursorShape


def cursor_shape_for_capture(
    image: np.ndarray,
    x: int,
    y: int,
    hotspot_x: int,
    hotspot_y: int,
    capture_rect: Rect,
) -> CursorShape | None:
    """None if the cursor doesn't overlap the captured region at all -
    faithful port of Surface's constructor-time check
    (Greenshot.Editor/Drawing/Surface.cs:552-565): the cursor is only
    ever added as a drawable element if its bounds intersect the
    capture. ``x``/``y``/``hotspot_x``/``hotspot_y``/``image`` come
    straight from a capture.cursor.CursorSnapshot - taken as plain
    values, not that type itself, so this stays in core/ without
    depending on the capture/ adapter layer.
    """
    height, width = image.shape[:2]
    bounds = cursor_bounds_in_capture(x, y, hotspot_x, hotspot_y, width, height, capture_rect.left, capture_rect.top)
    local_capture_bounds = Rect(0, 0, capture_rect.width, capture_rect.height)
    if bounds.intersect(local_capture_bounds) is None:
        return None
    return CursorShape(bounds=bounds, image=image)


def cursor_bounds_in_capture(
    cursor_x: int,
    cursor_y: int,
    hotspot_x: int,
    hotspot_y: int,
    width: int,
    height: int,
    capture_origin_x: int,
    capture_origin_y: int,
) -> Rect:
    left = cursor_x - hotspot_x - capture_origin_x
    top = cursor_y - hotspot_y - capture_origin_y
    return Rect(left, top, left + width, top + height)
