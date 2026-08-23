"""Pure sizing/positioning math behind the region-select magnifier
loupe (ui/region_select.py draws it; ui/magnifier.py renders it to
Cairo). Ported from the Windows source's Greenshot/Forms/CaptureForm.cs:

- DrawZoom (~line 866): the magnifier previews a 25x25px source crop
  centered on the cursor, scaled up into a circular preview.
- VerifyZoomAnimation (~line 812): sizes that preview to
  min(screen_width, screen_height) // 5, rounded down to a multiple of
  4, and positions it offset from the cursor - checking, in this exact
  priority order, whichever of the four surrounding quadrants
  (bottom-right, bottom-left, top-right, top-left) both stays on
  screen and doesn't cover the in-progress selection rect, falling
  back to allowing that overlap only if no quadrant can avoid it.

Task #168 follow-up: the *numbers* behind this (patch size, gap,
diameter divisor/rounding, plus ui/magnifier.py's ring/crosshair sizes
and ui/eyedropper.py's own fixed loupe size, and ui/region_select.py's
overlay colors) used to be independently hardcoded a fifth time in
extension.js, the bundled GNOME Shell extension - kept in sync only by
a human remembering to update all five. GJS can't import this module
at all (a completely separate process - see icon_geometry.json's own
citation trail in ui/icons.py for the identical constraint), so the
*algorithm* still has to be a second, hand-written implementation
there - but the numbers don't have to be. magnifier_constants.json
(same directory as icon_geometry.json) is that shared data; this
module's own magnifier_constants() is the Python-side reader,
extension.js has its own.
"""

from __future__ import annotations

import functools
import json
from typing import Optional, Tuple

from orcshot.core.geometry import Rect
from orcshot.resources import RESOURCES_DIR

Point = Tuple[int, int]

_MAGNIFIER_CONSTANTS_PATH = (
    RESOURCES_DIR / "gnome-shell-extensions" / "orcshot-clipboard@orcshot.org" / "magnifier_constants.json"
)


@functools.lru_cache(maxsize=1)
def magnifier_constants() -> dict:
    return json.loads(_MAGNIFIER_CONSTANTS_PATH.read_text())


def magnifier_diameter(screen_width: int, screen_height: int) -> int:
    constants = magnifier_constants()
    size = min(screen_width, screen_height) // constants["region_select_diameter_divisor"]
    return size - (size % constants["region_select_diameter_round_to"])


def magnifier_source_rect(cursor: Point, size: int = None) -> Rect:
    if size is None:
        size = magnifier_constants()["patch_size"]
    cx, cy = cursor
    half = size // 2
    return Rect(cx - half, cy - half, cx - half + size, cy - half + size)


def _contains_rect(outer: Rect, inner: Rect) -> bool:
    return outer.left <= inner.left and outer.top <= inner.top and outer.right >= inner.right and outer.bottom >= inner.bottom


def magnifier_offset(
    cursor: Point, screen_bounds: Rect, avoid_rect: Optional[Rect], diameter: int, gap: int = None,
) -> Point:
    """The (dx, dy) offset from ``cursor`` to the magnifier's top-left
    corner. Tries bottom-right, bottom-left, top-right, then top-left
    of the cursor (Windows' own priority order) - first requiring both
    on-screen placement and no overlap with ``avoid_rect`` (the
    in-progress selection), then relaxing the overlap requirement if
    nothing satisfies both, so there's always *some* on-screen result
    as long as the diameter itself fits on screen at all.
    """
    if gap is None:
        gap = magnifier_constants()["region_select_gap"]
    candidates = (
        (gap, gap),
        (-gap - diameter, gap),
        (gap, -gap - diameter),
        (-gap - diameter, -gap - diameter),
    )
    for allow_overlap in (False, True):
        for dx, dy in candidates:
            left, top = cursor[0] + dx, cursor[1] + dy
            rect = Rect(left, top, left + diameter, top + diameter)
            if not _contains_rect(screen_bounds, rect):
                continue
            if allow_overlap or avoid_rect is None or rect.intersect(avoid_rect) is None:
                return (dx, dy)
    return candidates[0]
