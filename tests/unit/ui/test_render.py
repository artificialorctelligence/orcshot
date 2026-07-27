"""Cairo rendering of annotation shapes.

Behavioral port of RectangleContainer/EllipseContainer/LineContainer/
ArrowContainer/FreehandContainer's Draw methods and the shared
DrawShadow helper (DrawableContainer.cs): 5 shadow steps, alpha 100
down to 20 in steps of 20 (out of 255), each a black stroke of the
shape's own outline offset diagonally by 0..4px, drawn before the real
shape. FreehandContainer's Draw has no DrawShadow call at all, so
freehand shapes never cast one - ported faithfully, not an oversight.

ArrowContainer's default ArrowHeadCombination is END_POINT, and
ArrowShape (core/shapes.py) has no field for the other combinations -
so only a single end-point arrowhead is rendered here. Its exact
geometry is a deliberate simplification: GDI+'s AdjustableArrowCap(4,6)
has no direct Cairo equivalent, so a filled triangle proportional to
line_thickness is used instead (see _arrowhead_path).

These tests run headless: cairo.ImageSurface needs no X11 connection,
so shapes are rendered to an in-memory surface and inspected as numpy
pixels via the already-tested cairo_surface_to_numpy conversion.
"""

import cairo
import numpy as np
import pytest

from greenshot_linux.core.filters import box_blur, pixelize
from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import (
    ArrowShape,
    EllipseShape,
    FreehandShape,
    LineShape,
    ObfuscateMode,
    ObfuscateShape,
    RectangleShape,
    ShapeStyle,
    TRANSPARENT,
)
from greenshot_linux.core.drawing import Layer
from greenshot_linux.ui.cairo_convert import cairo_surface_to_numpy
from greenshot_linux.ui.render import render_layer, render_shape


class ZeroRng:
    """Stub RNG: no grid jitter, no noise — makes pixelize deterministic
    (same fake used in test_filters.py, redefined here to keep this
    test module self-contained)."""

    def integers(self, low, high=None, size=None):
        if size is None:
            return 0
        return np.zeros(size, dtype=np.int64)


def render_to_numpy(width, height, draw):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    draw(ctx)
    surface.flush()
    return cairo_surface_to_numpy(surface)


class TestRenderRectangle:
    def test_fills_interior_with_fill_color(self):
        style = ShapeStyle(line_thickness=0, fill_color=(0, 255, 0, 255), shadow=False)
        shape = RectangleShape(Rect(10, 10, 50, 50), style)
        result = render_to_numpy(60, 60, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[30, 30]) == (0, 255, 0, 255)

    def test_transparent_fill_leaves_interior_untouched(self):
        style = ShapeStyle(line_thickness=2, line_color=(255, 0, 0, 255), fill_color=TRANSPARENT, shadow=False)
        shape = RectangleShape(Rect(10, 10, 50, 50), style)
        result = render_to_numpy(60, 60, lambda ctx: render_shape(ctx, shape))
        assert result[30, 30, 3] == 0

    def test_draws_stroke_with_line_color(self):
        style = ShapeStyle(line_thickness=4, line_color=(0, 0, 255, 255), fill_color=TRANSPARENT, shadow=False)
        shape = RectangleShape(Rect(10, 10, 50, 50), style)
        result = render_to_numpy(60, 60, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[10, 30]) == (0, 0, 255, 255)

    def test_shadow_paints_pixels_beyond_the_shape_when_enabled(self):
        style = ShapeStyle(line_thickness=2, line_color=(255, 0, 0, 255), fill_color=(0, 255, 0, 255), shadow=True)
        shape = RectangleShape(Rect(10, 10, 50, 50), style)
        result = render_to_numpy(70, 70, lambda ctx: render_shape(ctx, shape))
        band = result[51:57, 51:57]
        assert band[:, :, 3].max() > 0

    def test_no_shadow_leaves_the_band_beyond_the_shape_transparent(self):
        style = ShapeStyle(line_thickness=2, line_color=(255, 0, 0, 255), fill_color=(0, 255, 0, 255), shadow=False)
        shape = RectangleShape(Rect(10, 10, 50, 50), style)
        result = render_to_numpy(70, 70, lambda ctx: render_shape(ctx, shape))
        band = result[51:57, 51:57]
        assert band[:, :, 3].max() == 0


class TestRenderEllipse:
    def test_fills_interior_with_fill_color(self):
        style = ShapeStyle(line_thickness=0, fill_color=(255, 0, 255, 255), shadow=False)
        shape = EllipseShape(Rect(10, 10, 90, 50), style)
        result = render_to_numpy(100, 60, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[30, 50]) == (255, 0, 255, 255)

    def test_stroke_follows_the_ellipse_boundary(self):
        style = ShapeStyle(line_thickness=4, line_color=(10, 20, 30, 255), fill_color=TRANSPARENT, shadow=False)
        shape = EllipseShape(Rect(10, 10, 90, 50), style)
        result = render_to_numpy(100, 60, lambda ctx: render_shape(ctx, shape))
        # top-center of the ellipse's bounding box sits on its boundary
        assert tuple(result[10, 50]) == (10, 20, 30, 255)
        # center is interior, and fill is transparent
        assert result[30, 50, 3] == 0


class TestRenderLine:
    def test_draws_from_start_to_end(self):
        style = ShapeStyle(line_thickness=4, line_color=(0, 100, 200, 255), shadow=False)
        shape = LineShape(start=(10, 10), end=(60, 10), style=style)
        result = render_to_numpy(70, 20, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[10, 35]) == (0, 100, 200, 255)
        assert result[19, 35, 3] == 0

    def test_zero_thickness_draws_nothing(self):
        style = ShapeStyle(line_thickness=0, line_color=(0, 100, 200, 255), shadow=False)
        shape = LineShape(start=(10, 10), end=(60, 10), style=style)
        result = render_to_numpy(70, 20, lambda ctx: render_shape(ctx, shape))
        assert result[:, :, 3].max() == 0


class TestRenderArrow:
    def test_draws_the_line_body(self):
        style = ShapeStyle(line_thickness=4, line_color=(255, 0, 0, 255), shadow=False)
        shape = ArrowShape(start=(10, 30), end=(60, 30), style=style)
        result = render_to_numpy(70, 60, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[30, 20]) == (255, 0, 0, 255)

    def test_arrowhead_flares_beyond_the_line_width_near_the_end_only(self):
        style = ShapeStyle(line_thickness=4, line_color=(255, 0, 0, 255), shadow=False)
        shape = ArrowShape(start=(10, 30), end=(60, 30), style=style)
        result = render_to_numpy(70, 60, lambda ctx: render_shape(ctx, shape))
        # (50, 26) sits inside the end arrowhead's triangle but outside
        # the 4px-wide line stroke (y in [28, 32]).
        assert result[26, 50, 3] > 0
        # the mirror point near the start has no arrowhead (only
        # ArrowHeadCombination.END_POINT is supported) and is outside
        # the line stroke too, so it must stay transparent.
        assert result[26, 15, 3] == 0


class TestRenderFreehand:
    def test_draws_through_the_points(self):
        style = ShapeStyle(line_thickness=4, line_color=(0, 255, 255, 255))
        shape = FreehandShape(points=((10, 10), (10, 50), (50, 50)), style=style)
        result = render_to_numpy(60, 60, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[30, 10]) == (0, 255, 255, 255)
        assert tuple(result[50, 30]) == (0, 255, 255, 255)

    def test_fewer_than_two_points_draws_nothing(self):
        style = ShapeStyle(line_thickness=4, line_color=(0, 255, 255, 255))
        shape = FreehandShape(points=((10, 10),), style=style)
        result = render_to_numpy(60, 60, lambda ctx: render_shape(ctx, shape))
        assert result[:, :, 3].max() == 0

    def test_never_casts_a_shadow(self):
        style = ShapeStyle(line_thickness=4, line_color=(0, 255, 255, 255), shadow=True)
        shape = FreehandShape(points=((10, 10), (50, 10)), style=style)
        result = render_to_numpy(60, 60, lambda ctx: render_shape(ctx, shape))
        # a shadow would paint below-right of the stroke; nothing should
        # be there since FreehandContainer.Draw never calls DrawShadow
        assert result[15:20, 10:50, 3].max() == 0


def noisy_base_image(width=50, height=50, seed=7):
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    return image


class TestRenderObfuscate:
    def test_pixelize_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.PIXELIZE, amount=6)

        result = render_to_numpy(
            50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image, rng=ZeroRng())
        )

        expected = pixelize(base_image, bounds, 6, rng=ZeroRng())
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_blur_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.BLUR, amount=4)

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = box_blur(base_image, bounds, 4)
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_pixels_outside_bounds_are_left_untouched_by_rendering(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.BLUR, amount=4)

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        # nothing is painted outside bounds - the surface started blank
        assert result[0:5, :, 3].max() == 0
        assert result[:, 0:5, 3].max() == 0

    def test_raises_a_clear_error_without_a_base_image(self):
        shape = ObfuscateShape(Rect(0, 0, 10, 10))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        ctx = cairo.Context(surface)
        with pytest.raises(ValueError):
            render_shape(ctx, shape)


class TestRenderLayer:
    def test_draws_shapes_in_z_order_so_later_ones_win_on_overlap(self):
        bottom = RectangleShape(Rect(10, 10, 50, 50), ShapeStyle(line_thickness=0, fill_color=(255, 0, 0, 255), shadow=False))
        top = RectangleShape(Rect(20, 20, 60, 60), ShapeStyle(line_thickness=0, fill_color=(0, 0, 255, 255), shadow=False))
        layer = Layer()
        layer.add(bottom)
        layer.add(top)

        result = render_to_numpy(70, 70, lambda ctx: render_layer(ctx, layer))

        assert tuple(result[30, 30]) == (0, 0, 255, 255)  # overlap: top wins
        assert tuple(result[15, 15]) == (255, 0, 0, 255)  # bottom-only area

    def test_threads_base_image_through_to_obfuscate_shapes(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        # the rectangle overlaps only the top-left corner of the blur
        # region, so the two shapes' effects can be checked at disjoint
        # sample points without one masking the other.
        layer = Layer()
        layer.add(ObfuscateShape(bounds, mode=ObfuscateMode.BLUR, amount=4))
        layer.add(RectangleShape(Rect(0, 0, 10, 10), ShapeStyle(line_thickness=0, fill_color=(1, 2, 3, 255), shadow=False)))

        result = render_to_numpy(50, 50, lambda ctx: render_layer(ctx, layer, base_image=base_image))

        expected = box_blur(base_image, bounds, 4)
        assert tuple(result[25, 25]) == tuple(expected[25, 25])  # blurred, outside the rectangle
        assert tuple(result[5, 5]) == (1, 2, 3, 255)  # rectangle drawn on top, inside its own bounds

    def test_empty_layer_draws_nothing(self):
        layer = Layer()
        result = render_to_numpy(20, 20, lambda ctx: render_layer(ctx, layer))
        assert result[:, :, 3].max() == 0


def test_render_shape_raises_for_a_shape_type_with_no_renderer():
    # A shape type render.py's dispatch table has never heard of (not
    # one of the real, still-unimplemented shapes, which would need
    # updating here every time another one gains a renderer) - the
    # point is the fallback itself: an explicit error rather than
    # silently drawing nothing for any unrecognized shape type.
    class NotARealShape:
        pass

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
    ctx = cairo.Context(surface)
    try:
        render_shape(ctx, NotARealShape())
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass
