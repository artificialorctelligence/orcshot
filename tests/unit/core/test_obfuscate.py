"""ObfuscateShape: bounds + a filter mode, nothing else.

Behavioral port of ObfuscateContainer (a FilterContainer that swaps in
either BlurFilter or PixelizationFilter). Unlike every other shape,
this one carries no visual content of its own — rendering it means
re-filtering the region of the *original captured image* under its
bounds (see ui/render.py's render_obfuscate), not drawing paths. That
rendering-time behavior lives in ui/render.py and is tested there;
this module only covers the shape's own data and hit-testing.

FilterContainer doesn't override ClickableAt in the source, so this
falls through to the base DrawableContainer's bounds-inflate-5 test,
same as TextShape/IconShape/CursorShape/ImageShape/SvgShape.

The single ``amount`` field is a deliberate simplification: the source
gives BlurFilter and PixelizationFilter independent fields
(BLUR_RADIUS=3, PIXEL_SIZE=5) that keep their own values when you
switch between them. Here, switching ``mode`` without also setting
``amount`` reuses whatever ``amount`` already is - simpler data model,
documented rather than silently diverging.
"""

from greenshot_linux.core.drawing import hit_test
from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import ObfuscateMode, ObfuscateShape


class TestObfuscateShape:
    def test_defaults_match_the_source_defaults(self):
        # ObfuscateContainer.InitializeFields: PREPARED_FILTER_OBFUSCATE
        # defaults to PreparedFilter.PIXELIZE, whose own PIXEL_SIZE
        # field defaults to 5.
        shape = ObfuscateShape(bounds=Rect(0, 0, 20, 20))
        assert shape.mode is ObfuscateMode.PIXELIZE
        assert shape.amount == 5

    def test_stores_bounds_and_mode(self):
        shape = ObfuscateShape(bounds=Rect(5, 5, 25, 25), mode=ObfuscateMode.BLUR, amount=7)
        assert shape.bounds == Rect(5, 5, 25, 25)
        assert shape.mode is ObfuscateMode.BLUR
        assert shape.amount == 7

    def test_has_no_clickable_at_override(self):
        shape = ObfuscateShape(bounds=Rect(0, 0, 20, 20))
        assert not hasattr(shape, "clickable_at")
        assert hit_test(shape, 3, 3)  # falls through to the generic fallback

    def test_is_frozen_and_comparable(self):
        a = ObfuscateShape(bounds=Rect(0, 0, 10, 10))
        b = ObfuscateShape(bounds=Rect(0, 0, 10, 10))
        assert a == b
