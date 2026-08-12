"""IconShape, CursorShape, ImageShape, SvgShape: bounds + opaque content,
nothing else.

Behavioral port of IconContainer, CursorContainer, ImageContainer, and
SvgContainer (via VectorGraphicsContainer). None of the four override
ClickableAt in the source — they fall through to the base
DrawableContainer's bounds-inflate-5 test, same as TextShape. The only
field any of them actually has is ImageContainer's `shadow` flag;
IconContainer, CursorContainer, and VectorGraphicsContainer have none.

DefaultSize (icon/cursor/SVG-document native size, or a fixed fallback)
is deliberately not modeled here, consistent with StepLabelShape's
DefaultSize: it's a UI-editor "what size to place a newly-created shape
at" concern, not data the shape itself needs to carry — bounds is
caller-supplied here exactly as it is for every other shape.

Bitmap content (Icon/Cursor/Image) is stored as an (H, W, 4) uint8 RGBA
array, matching the representation used throughout capture and filters
rather than inventing a separate image type. SVG content is stored as
raw markup text, the natural "opaque content" representation for vector
data before any rendering exists.
"""

import numpy as np

from orcshot.core.drawing import hit_test
from orcshot.core.geometry import Rect
from orcshot.core.shapes import CursorShape, IconShape, ImageShape, SvgShape


def rgba_image(w=16, h=16):
    return np.full((h, w, 4), (10, 20, 30, 255), dtype=np.uint8)


class TestIconShape:
    def test_stores_bounds_and_image(self):
        image = rgba_image()
        shape = IconShape(bounds=Rect(0, 0, 16, 16), image=image)
        assert shape.bounds == Rect(0, 0, 16, 16)
        assert np.array_equal(shape.image, image)

    def test_has_no_clickable_at_override(self):
        shape = IconShape(bounds=Rect(0, 0, 16, 16), image=rgba_image())
        assert not hasattr(shape, "clickable_at")
        assert hit_test(shape, 3, 3)  # falls through to the generic fallback


class TestCursorShape:
    def test_stores_bounds_and_image(self):
        image = rgba_image()
        shape = CursorShape(bounds=Rect(5, 5, 21, 21), image=image)
        assert shape.bounds == Rect(5, 5, 21, 21)
        assert np.array_equal(shape.image, image)

    def test_has_no_clickable_at_override(self):
        shape = CursorShape(bounds=Rect(0, 0, 16, 16), image=rgba_image())
        assert not hasattr(shape, "clickable_at")


class TestImageShape:
    def test_stores_bounds_image_and_shadow(self):
        image = rgba_image(32, 32)
        shape = ImageShape(bounds=Rect(0, 0, 32, 32), image=image, shadow=True)
        assert shape.bounds == Rect(0, 0, 32, 32)
        assert np.array_equal(shape.image, image)
        assert shape.shadow is True

    def test_shadow_defaults_to_false(self):
        shape = ImageShape(bounds=Rect(0, 0, 32, 32), image=rgba_image(32, 32))
        assert shape.shadow is False

    def test_has_no_clickable_at_override(self):
        shape = ImageShape(bounds=Rect(0, 0, 32, 32), image=rgba_image(32, 32))
        assert not hasattr(shape, "clickable_at")


class TestSvgShape:
    def test_stores_bounds_and_markup(self):
        markup = "<svg width='10' height='10'></svg>"
        shape = SvgShape(bounds=Rect(0, 0, 10, 10), svg_data=markup)
        assert shape.bounds == Rect(0, 0, 10, 10)
        assert shape.svg_data == markup

    def test_has_no_clickable_at_override(self):
        shape = SvgShape(bounds=Rect(0, 0, 10, 10), svg_data="<svg></svg>")
        assert not hasattr(shape, "clickable_at")
