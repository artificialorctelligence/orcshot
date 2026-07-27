"""TextShape: text content on a RectangleShape-like box, but with its own
hit-test rule.

Behavioral port of TextContainer, which extends RectangleContainer (same
line/fill/shadow fields) but overrides ClickableAt back to the *base*
DrawableContainer behavior — plain bounds inflated by 5 — rather than
inheriting RectangleContainer's fill-aware outline test. Text should be
clickable anywhere in its box regardless of whether a border/fill is
visible, since the glyphs themselves are what the user perceives as the
shape. TextShape has no clickable_at method at all: Layer.hit_test's
existing bounds-inflate-5 fallback already matches this exactly, so
there's nothing shape-specific to write.
"""

from greenshot_linux.core.drawing import hit_test
from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import RectangleShape, ShapeStyle, TextShape


class TestDefaults:
    def test_default_field_values_match_the_windows_source(self):
        shape = TextShape(bounds=Rect(0, 0, 100, 50), text="hello")

        assert shape.font_family == "sans-serif"
        assert shape.font_size == 11.0
        assert shape.bold is False
        assert shape.italic is False
        assert shape.horizontal_alignment == "center"
        assert shape.vertical_alignment == "center"
        assert shape.style == ShapeStyle()  # thickness 2, red line, transparent fill, shadow


class TestBounds:
    def test_bounds_is_the_stored_rect(self):
        shape = TextShape(bounds=Rect(10, 10, 110, 60), text="hello")
        assert shape.bounds == Rect(10, 10, 110, 60)


class TestHitTesting:
    def test_has_no_clickable_at_override(self):
        # The faithful port of TextContainer.ClickableAt reverting to
        # the base behavior is to not define one at all.
        shape = TextShape(bounds=Rect(0, 0, 100, 50), text="hello")
        assert not hasattr(shape, "clickable_at")

    def test_interior_is_clickable_even_with_a_transparent_fill(self):
        # Unlike RectangleShape, whose hollow interior is NOT clickable
        # (the fill-aware outline test), Text's interior is always
        # clickable via the generic bounds-inflate-5 fallback — this is
        # the actual behavioral difference the override exists for.
        text = TextShape(bounds=Rect(0, 0, 100, 50), text="hello")
        rect = RectangleShape(bounds=Rect(0, 0, 100, 50))  # same bounds, transparent fill

        assert hit_test(text, 50, 25)  # dead center
        assert not hit_test(rect, 50, 25)

    def test_bounds_inflated_by_five_still_counts(self):
        shape = TextShape(bounds=Rect(10, 10, 110, 60), text="hello")
        assert hit_test(shape, 8, 30)  # 2px outside the left edge

    def test_far_outside_the_inflated_bounds_does_not_count(self):
        shape = TextShape(bounds=Rect(10, 10, 110, 60), text="hello")
        assert not hit_test(shape, 500, 500)
