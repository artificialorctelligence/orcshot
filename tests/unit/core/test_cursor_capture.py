"""Pure placement math for cursor auto-capture - see
core/cursor_capture.py's module docstring for the Windows-source
citation this formula is ported from.
"""

import numpy as np

from orcshot.core.cursor_capture import cursor_bounds_in_capture, cursor_shape_for_capture
from orcshot.core.geometry import Rect
from orcshot.core.shapes import CursorShape


def _cursor_image(w=8, h=8):
    image = np.zeros((h, w, 4), dtype=np.uint8)
    image[:, :] = (255, 0, 0, 255)
    return image


class TestCursorBoundsInCapture:
    def test_cursor_at_capture_origin_with_zero_hotspot(self):
        bounds = cursor_bounds_in_capture(
            cursor_x=100, cursor_y=100, hotspot_x=0, hotspot_y=0,
            width=24, height=24, capture_origin_x=100, capture_origin_y=100,
        )
        assert bounds == Rect(0, 0, 24, 24)

    def test_hotspot_offset_shifts_bounds_up_and_left(self):
        # the cursor's "position" is its hotspot, not its top-left corner -
        # a nonzero hotspot (e.g. an arrow cursor's tip) pulls the bitmap's
        # top-left back by that amount.
        bounds = cursor_bounds_in_capture(
            cursor_x=100, cursor_y=100, hotspot_x=5, hotspot_y=3,
            width=24, height=24, capture_origin_x=0, capture_origin_y=0,
        )
        assert bounds == Rect(95, 97, 119, 121)

    def test_capture_origin_offsets_into_region_local_coordinates(self):
        # a region capture starting at (500, 300) on screen must translate
        # screen-space cursor coordinates into image-local coordinates.
        bounds = cursor_bounds_in_capture(
            cursor_x=550, cursor_y=350, hotspot_x=0, hotspot_y=0,
            width=16, height=16, capture_origin_x=500, capture_origin_y=300,
        )
        assert bounds == Rect(50, 50, 66, 66)

    def test_cursor_outside_capture_region_yields_negative_bounds(self):
        # not rejected here - that's a separate intersection check against
        # the capture rect, done by the caller via Rect.intersect.
        bounds = cursor_bounds_in_capture(
            cursor_x=10, cursor_y=10, hotspot_x=0, hotspot_y=0,
            width=16, height=16, capture_origin_x=500, capture_origin_y=500,
        )
        assert bounds == Rect(-490, -490, -474, -474)

    def test_width_and_height_are_preserved(self):
        bounds = cursor_bounds_in_capture(
            cursor_x=0, cursor_y=0, hotspot_x=0, hotspot_y=0,
            width=32, height=48, capture_origin_x=0, capture_origin_y=0,
        )
        assert bounds.width == 32
        assert bounds.height == 48


class TestCursorShapeForCapture:
    def test_cursor_inside_the_capture_becomes_a_cursor_shape(self):
        image = _cursor_image()
        capture_rect = Rect(500, 300, 900, 700)

        shape = cursor_shape_for_capture(
            image, x=550, y=350, hotspot_x=0, hotspot_y=0, capture_rect=capture_rect,
        )

        assert isinstance(shape, CursorShape)
        assert shape.bounds == Rect(50, 50, 58, 58)
        assert shape.image is image

    def test_cursor_entirely_outside_the_capture_is_dropped(self):
        # faithful port of Surface.cs:552-565's intersect check - a
        # cursor that's over a different monitor than the captured
        # region shouldn't show up as a drawable at all.
        image = _cursor_image()
        capture_rect = Rect(0, 0, 400, 300)

        shape = cursor_shape_for_capture(
            image, x=2000, y=2000, hotspot_x=0, hotspot_y=0, capture_rect=capture_rect,
        )

        assert shape is None

    def test_cursor_partially_overlapping_the_capture_edge_is_kept(self):
        image = _cursor_image(w=8, h=8)
        capture_rect = Rect(0, 0, 100, 100)

        # cursor bitmap's bounds would be (96, 96, 104, 104) - only the
        # top-left 4x4 corner overlaps the 100x100 capture.
        shape = cursor_shape_for_capture(
            image, x=96, y=96, hotspot_x=0, hotspot_y=0, capture_rect=capture_rect,
        )

        assert shape is not None
        assert shape.bounds == Rect(96, 96, 104, 104)

    def test_cursor_exactly_touching_the_edge_does_not_intersect(self):
        # Rect.intersect treats a zero-width/height overlap as no
        # intersection (see core/geometry.py) - a cursor bitmap that
        # starts exactly at the capture's right/bottom edge is fully
        # outside, not a 1px sliver kept.
        image = _cursor_image(w=8, h=8)
        capture_rect = Rect(0, 0, 100, 100)

        shape = cursor_shape_for_capture(
            image, x=100, y=100, hotspot_x=0, hotspot_y=0, capture_rect=capture_rect,
        )

        assert shape is None
