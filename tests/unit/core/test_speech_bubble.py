"""SpeechBubbleShape: a TextShape-like box with a triangular tail
pointing at a target location.

Behavioral port of SpeechbubbleContainer, which extends TextContainer
(same font/text fields, different defaults: blue line, white fill,
bold, size 20, no shadow). The base DrawableContainer.Contains is just
`Bounds.Contains(x, y)` — no margin at all — which is why the bubble
interior is clickable despite SpeechbubbleContainer.Contains having no
explicit "filled shape" fast path the way Rectangle/Ellipse do: the
plain bounds check already covers it. The tail sticks out beyond the
bubble's own bounds, so it needs its own hit test.

Two deliberate simplifications from the source, both documented rather
than silently assumed:
1. Corner rounding is a rendering nicety that doesn't change which
   points count as "inside" the bubble (the bounds check dominates), so
   it isn't reproduced in the hit test — a plain rect outline distance
   is used for the few-pixel margin just outside the bubble's edge.
2. The tail hit test here is "point inside the filled triangle", not
   the source's outline-only GraphicsPath.Widen band around the
   triangle's 3 edges. Replicating exact GDI+ path-widening for a thin
   triangle outline isn't worth the complexity for what's a minor UX
   nuance either way.

Also: bounds (the Drawable-protocol property, used for Layer z-order
aggregation) is the union of the bubble rectangle and the tail's own
extent, matching the source's DrawingBounds concept — which is
deliberately a *different*, wider concept than the source's own Bounds
(just the bubble rectangle, used for the interior hit-test fast path).
"""

from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import ShapeStyle, SpeechBubbleShape


class TestDefaults:
    def test_default_field_values_match_the_windows_source(self):
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 100, 60), target=(200, 200), text="hi")

        assert shape.font_size == 20.0
        assert shape.bold is True
        assert shape.italic is False
        assert shape.style.line_color == (0, 0, 255, 255)  # Blue
        assert shape.style.fill_color == (255, 255, 255, 255)  # White
        assert shape.style.shadow is False


class TestInteriorClick:
    def test_center_of_the_bubble_is_always_clickable(self):
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 100, 60), target=(200, 200), text="hi")
        assert shape.clickable_at(50, 30)

    def test_anywhere_inside_the_bubble_rect_is_clickable_regardless_of_fill(self):
        # Ported faithfully: the source's fast path is `Bounds.Contains`
        # with no fill-color check at all (unlike Rectangle/Ellipse).
        shape = SpeechBubbleShape(
            bubble_bounds=Rect(0, 0, 100, 60),
            target=(200, 200),
            text="hi",
            style=ShapeStyle(fill_color=(0, 0, 0, 0)),  # transparent
        )
        assert shape.clickable_at(10, 10)


class TestBorderClick:
    def test_clickable_just_outside_the_bubble_edge_within_the_margin(self):
        shape = SpeechBubbleShape(bubble_bounds=Rect(10, 10, 110, 70), target=(500, 500), text="hi")
        # margin = line_thickness(2) + 10 = 12, so within 6px counts.
        assert shape.clickable_at(10, 5)

    def test_not_clickable_far_outside_the_bubble_and_away_from_the_tail(self):
        shape = SpeechBubbleShape(bubble_bounds=Rect(10, 10, 110, 70), target=(500, 500), text="hi")
        assert not shape.clickable_at(-1000, -1000)


class TestTailClick:
    def test_clickable_on_the_tail_toward_the_target(self):
        # Bubble centered at (50,30); target far below at (50, 500).
        # The tail runs straight down from the bubble's bottom edge, so
        # a point partway down that line, well outside bubble_bounds,
        # must register.
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 100, 60), target=(50, 500), text="hi")
        assert shape.clickable_at(50, 200)

    def test_not_clickable_off_to_the_side_of_the_tail(self):
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 100, 60), target=(50, 500), text="hi")
        assert not shape.clickable_at(500, 200)  # same height, way off to the side

    def test_target_coincident_with_bubble_center_does_not_crash(self):
        # Degenerate case: zero-length tail has no defined direction.
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 100, 60), target=(50, 30), text="hi")
        assert shape.clickable_at(50, 30)  # still inside the bubble itself
        assert not shape.clickable_at(-1000, -1000)


class TestBounds:
    def test_bounds_includes_the_tail_when_it_points_outside_the_bubble_rect(self):
        # Ported from DrawingBounds unioning bubbleBounds and tailBounds
        # — a deliberately *different*, wider concept than the source's
        # own Bounds (used only for the interior-click fast path).
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 100, 60), target=(50, 500), text="hi")
        assert shape.bounds.bottom >= 500

    def test_bounds_is_just_the_bubble_rect_when_the_tail_is_degenerate(self):
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 100, 60), target=(50, 30), text="hi")
        assert shape.bounds == Rect(0, 0, 100, 60)


# --- Property-based tests -------------------------------------------------

from hypothesis import given
from hypothesis import strategies as st

_coord = st.integers(min_value=-1_000, max_value=1_000)
_dim = st.integers(min_value=1, max_value=500)


@given(left=_coord, top=_coord, w=_dim, h=_dim, tx=_coord, ty=_coord)
def test_bubble_center_is_always_clickable(left, top, w, h, tx, ty):
    shape = SpeechBubbleShape(
        bubble_bounds=Rect(left, top, left + w, top + h), target=(tx, ty), text="hi"
    )
    assert shape.clickable_at(left + w // 2, top + h // 2)


@given(left=_coord, top=_coord, w=_dim, h=_dim, tx=_coord, ty=_coord)
def test_the_target_point_itself_is_always_clickable_when_the_tail_is_nondegenerate(
    left, top, w, h, tx, ty
):
    bounds = Rect(left, top, left + w, top + h)
    cx, cy = left + w / 2, top + h / 2
    if (tx, ty) == (cx, cy):
        return  # degenerate: no tail direction, covered by a dedicated example test
    shape = SpeechBubbleShape(bubble_bounds=bounds, target=(tx, ty), text="hi")
    assert shape.clickable_at(tx, ty)
