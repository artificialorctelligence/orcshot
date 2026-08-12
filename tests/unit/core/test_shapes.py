"""Concrete annotation shapes.

Behavioral port of RectangleContainer, EllipseContainer, LineContainer,
and ArrowContainer from the Windows source. The interesting part is
clickable_at, not Draw (we have no renderer yet): a filled shape is
clickable anywhere inside it, a hollow one only near its outline —
ported from RectangleClickableAt / EllipseClickableAt / the GraphicsPath
IsOutlineVisible calls in LineContainer/ArrowContainer.
"""

import pytest

from orcshot.core.geometry import Rect
from orcshot.core.shapes import (
    TRANSPARENT,
    ArrowShape,
    EllipseShape,
    LineShape,
    RectangleShape,
    ShapeStyle,
    is_visible,
)


class TestIsVisible:
    def test_alpha_zero_is_not_visible(self):
        assert not is_visible((255, 0, 0, 0))

    def test_alpha_above_zero_is_visible(self):
        assert is_visible((255, 0, 0, 1))

    def test_transparent_constant_is_not_visible(self):
        assert not is_visible(TRANSPARENT)


class TestRectangleShape:
    def make(self, fill_color=TRANSPARENT, line_thickness=2):
        return RectangleShape(
            bounds=Rect(10, 10, 110, 60),
            style=ShapeStyle(line_thickness=line_thickness, fill_color=fill_color),
        )

    def test_filled_rectangle_is_clickable_anywhere_inside(self):
        # Ported from RectangleClickableAt: a visible fill makes the
        # whole interior clickable, not just the border.
        rect = self.make(fill_color=(0, 255, 0, 255))
        assert rect.clickable_at(60, 35)  # dead center, nowhere near a border

    def test_hollow_rectangle_interior_is_not_clickable(self):
        rect = self.make(fill_color=TRANSPARENT)
        assert not rect.clickable_at(60, 35)

    def test_hollow_rectangle_is_clickable_near_the_border(self):
        rect = self.make(fill_color=TRANSPARENT, line_thickness=2)
        # margin = line_thickness + 10 = 12, so within 6px of the top
        # edge (y=10) counts.
        assert rect.clickable_at(60, 13)

    def test_hollow_rectangle_is_not_clickable_past_the_margin(self):
        rect = self.make(fill_color=TRANSPARENT, line_thickness=2)
        assert not rect.clickable_at(60, 30)  # 20px from the nearest edge

    def test_far_away_point_is_never_clickable(self):
        rect = self.make(fill_color=(0, 255, 0, 255))
        assert not rect.clickable_at(1000, 1000)

    def test_even_zero_thickness_is_still_clickable_near_the_border(self):
        # Ported faithfully, including the quirk: margin = thickness + 10
        # is applied unconditionally, so a 0-thickness border is still
        # selectable near where it would be drawn — the +10 floor exists
        # so an invisible-bordered shape doesn't become unselectable.
        rect = self.make(fill_color=TRANSPARENT, line_thickness=0)
        assert rect.clickable_at(10, 35)  # right on the border

    def test_thickness_low_enough_to_zero_out_the_margin_disables_clicking(self):
        rect = self.make(fill_color=TRANSPARENT, line_thickness=-15)  # margin = -5
        assert not rect.clickable_at(10, 35)


class TestEllipseShape:
    def make(self, fill_color=TRANSPARENT, line_thickness=2):
        # Bounds (0,0,100,50): center (50,25), semi-axes a=50, b=25.
        return EllipseShape(
            bounds=Rect(0, 0, 100, 50),
            style=ShapeStyle(line_thickness=line_thickness, fill_color=fill_color),
        )

    def test_filled_ellipse_is_clickable_at_its_center(self):
        ellipse = self.make(fill_color=(0, 255, 0, 255))
        assert ellipse.clickable_at(50, 25)

    def test_hollow_ellipse_center_is_not_clickable(self):
        ellipse = self.make(fill_color=TRANSPARENT)
        assert not ellipse.clickable_at(50, 25)

    def test_hollow_ellipse_is_clickable_at_the_top_of_its_arc(self):
        # Top-center of the bounding box (50, 0) sits exactly on the
        # ellipse boundary for any axis-aligned ellipse.
        ellipse = self.make(fill_color=TRANSPARENT, line_thickness=2)
        assert ellipse.clickable_at(50, 0)

    def test_hollow_ellipse_is_not_clickable_far_outside(self):
        ellipse = self.make(fill_color=TRANSPARENT)
        assert not ellipse.clickable_at(-100, -100)

    def test_hollow_ellipse_is_not_clickable_deep_inside(self):
        ellipse = self.make(fill_color=TRANSPARENT)
        assert not ellipse.clickable_at(55, 25)  # near center, not the rim


class TestLineShape:
    def make(self, start=(0, 0), end=(100, 100), line_thickness=2):
        return LineShape(start=start, end=end, style=ShapeStyle(line_thickness=line_thickness))

    def test_bounds_is_the_normalized_span_of_the_endpoints(self):
        line = self.make(start=(100, 0), end=(0, 100))
        assert line.bounds == Rect(0, 0, 100, 100)

    def test_a_reversed_diagonal_has_the_same_bounds_but_is_a_different_line(self):
        # The bug this guards: two diagonals of the same bounding box
        # are different lines. Reducing a line to just its Rect loses
        # that direction — this shape must keep the real endpoints.
        backslash = self.make(start=(0, 0), end=(100, 100))  # "\"
        forwardslash = self.make(start=(100, 0), end=(0, 100))  # "/"

        assert backslash.bounds == forwardslash.bounds
        # (50, 50) is the center of a square bounding box, so it sits on
        # BOTH diagonals — not a useful test point. (25, 25) is on the
        # "\" diagonal (y=x) but well off the "/" diagonal (x+y=100).
        assert backslash.clickable_at(25, 25)
        assert not forwardslash.clickable_at(25, 25)

    def test_point_on_the_segment_is_clickable(self):
        line = self.make(start=(0, 0), end=(100, 0))
        assert line.clickable_at(50, 0)

    def test_point_near_the_segment_is_clickable_within_the_margin(self):
        # margin = line_thickness + 5 = 7, so within 3.5px counts.
        line = self.make(start=(0, 0), end=(100, 0), line_thickness=2)
        assert line.clickable_at(50, 3)

    def test_point_near_the_segment_beyond_the_margin_is_not_clickable(self):
        line = self.make(start=(0, 0), end=(100, 0), line_thickness=2)
        assert not line.clickable_at(50, 10)

    def test_point_collinear_but_past_the_endpoint_is_not_clickable(self):
        # A segment, not an infinite line — being on the extended line
        # past either end doesn't count.
        line = self.make(start=(0, 0), end=(100, 0))
        assert not line.clickable_at(150, 0)

    def test_zero_thickness_line_is_never_clickable(self):
        line = self.make(line_thickness=-5)  # thickness + 5 = 0
        assert not line.clickable_at(50, 0)


class TestArrowShape:
    def make(self, start=(0, 0), end=(100, 0), line_thickness=2):
        return ArrowShape(start=start, end=end, style=ShapeStyle(line_thickness=line_thickness))

    def test_is_a_line_shape(self):
        assert isinstance(self.make(), LineShape)

    def test_uses_a_wider_margin_than_a_plain_line(self):
        # Ported straight from the source: LineContainer uses
        # thickness + 5, ArrowContainer uses thickness + 10 — a real
        # asymmetry in Greenshot, not a typo to "fix". A point 4px off
        # the segment is outside a Line's margin but inside an Arrow's.
        line = LineShape(start=(0, 0), end=(100, 0), style=ShapeStyle(line_thickness=2))
        arrow = self.make(line_thickness=2)

        assert not line.clickable_at(50, 4)
        assert arrow.clickable_at(50, 4)


# --- Property-based tests -------------------------------------------------

from hypothesis import assume, given
from hypothesis import strategies as st

_coord = st.integers(min_value=-1_000, max_value=1_000)
_thickness = st.integers(min_value=1, max_value=20)
_t = st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False)


@given(x1=_coord, y1=_coord, x2=_coord, y2=_coord, thickness=_thickness, t=_t)
def test_any_point_on_a_line_segment_is_always_clickable(x1, y1, x2, y2, thickness, t):
    assume((x1, y1) != (x2, y2))
    px = x1 + t * (x2 - x1)
    py = y1 + t * (y2 - y1)
    line = LineShape(start=(x1, y1), end=(x2, y2), style=ShapeStyle(line_thickness=thickness))

    # margin/2 is always >= 3 here (min thickness 1 + hit margin 5, /2),
    # comfortably larger than the float->int rounding error (<=~0.71).
    assert line.clickable_at(round(px), round(py))


@given(x1=_coord, y1=_coord, x2=_coord, y2=_coord, thickness=_thickness, t=_t)
def test_any_point_on_an_arrow_segment_is_always_clickable(x1, y1, x2, y2, thickness, t):
    assume((x1, y1) != (x2, y2))
    px = x1 + t * (x2 - x1)
    py = y1 + t * (y2 - y1)
    arrow = ArrowShape(start=(x1, y1), end=(x2, y2), style=ShapeStyle(line_thickness=thickness))

    assert arrow.clickable_at(round(px), round(py))


@given(x1=_coord, y1=_coord, x2=_coord, y2=_coord)
def test_line_bounds_do_not_depend_on_which_endpoint_is_which(x1, y1, x2, y2):
    forward = LineShape(start=(x1, y1), end=(x2, y2))
    backward = LineShape(start=(x2, y2), end=(x1, y1))
    assert forward.bounds == backward.bounds


@given(left=_coord, top=_coord, w=st.integers(1, 500), h=st.integers(1, 500), thickness=_thickness)
def test_rectangle_center_is_always_clickable_when_filled(left, top, w, h, thickness):
    rect = RectangleShape(
        bounds=Rect(left, top, left + w, top + h),
        style=ShapeStyle(line_thickness=thickness, fill_color=(0, 255, 0, 255)),
    )
    assert rect.clickable_at(left + w // 2, top + h // 2)


@given(left=_coord, top=_coord, w=st.integers(1, 500), h=st.integers(1, 500), thickness=_thickness)
def test_ellipse_center_is_always_clickable_when_filled(left, top, w, h, thickness):
    ellipse = EllipseShape(
        bounds=Rect(left, top, left + w, top + h),
        style=ShapeStyle(line_thickness=thickness, fill_color=(0, 255, 0, 255)),
    )
    assert ellipse.clickable_at(left + w // 2, top + h // 2)
