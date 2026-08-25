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

from orcshot.core.filters import (
    box_blur, brightness_filter, grayscale_filter, highlight_filter, magnify_filter, pixelize, scramble, solid_fill,
)
from orcshot.core.geometry import Rect
from orcshot.core.shapes import (
    ArrowShape,
    EllipseShape,
    FreehandShape,
    HighlightMode,
    HighlightShape,
    LineShape,
    ObfuscateMode,
    ObfuscateShape,
    RectangleShape,
    ShapeStyle,
    TRANSPARENT,
)
from orcshot.core.drawing import Layer
from orcshot.ui.cairo_convert import cairo_surface_to_numpy
from orcshot.ui.render import render_layer, render_shape


class ZeroRng:
    """Stub RNG: no grid jitter, no noise — makes pixelize deterministic
    (same fake used in test_filters.py, redefined here to keep this
    test module self-contained)."""

    def integers(self, low, high=None, size=None):
        if size is None:
            return 0
        return np.zeros(size, dtype=np.int64)


class ZeroRng2D:
    """Stub RNG for scramble: Generator.normal(loc, scale, size) with no
    actual randomness (same fake used in test_filters.py, redefined
    here to keep this test module self-contained)."""

    def normal(self, loc, scale, size):
        return np.broadcast_to(loc, size).astype(np.float64)


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

    def test_pixelize_with_no_explicit_rng_is_stable_across_repeated_renders(self):
        # Without an explicit rng= override (the normal editor-redraw
        # path), the same unchanged shape must render identically every
        # time - it's driven by the shape's own pinned seed, not a
        # fresh random draw per render call. Previously this reshuffled
        # the jitter pattern on every redraw, which fired on *any*
        # canvas activity (moving an unrelated shape triggers a full
        # repaint), making the pixelization look like it was randomly
        # flickering.
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.PIXELIZE, amount=6)

        first = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))
        second = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        assert np.array_equal(first, second)

    def test_pixelize_with_no_explicit_rng_differs_between_distinct_shapes(self):
        # Not just a hardcoded/shared fallback seed - two independently
        # created shapes (each gets its own fresh seed - see
        # ObfuscateShape.seed) still render different noise.
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape_a = ObfuscateShape(bounds, mode=ObfuscateMode.PIXELIZE, amount=6)
        shape_b = ObfuscateShape(bounds, mode=ObfuscateMode.PIXELIZE, amount=6)

        result_a = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape_a, base_image=base_image))
        result_b = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape_b, base_image=base_image))

        assert not np.array_equal(result_a, result_b)

    def test_blur_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.BLUR, amount=4)

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = box_blur(base_image, bounds, 4)
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_solid_fill_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.SOLID_FILL, fill_color=(200, 100, 50, 255))

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = solid_fill(base_image, bounds, (200, 100, 50, 255))
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_solid_fill_with_no_text_matches_the_filters_module_exactly(self):
        # Blank fill_text (ObfuscateShape's own default) draws nothing
        # extra - same pixel-exact match as the no-text test above,
        # just explicit about *why* (empty string, not just "unset").
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.SOLID_FILL, fill_color=(0, 0, 0, 255), fill_text="")

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = solid_fill(base_image, bounds, (0, 0, 0, 255))
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_solid_fill_with_text_draws_something_besides_the_flat_fill(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 45, 45)
        shape = ObfuscateShape(
            bounds, mode=ObfuscateMode.SOLID_FILL, fill_color=(0, 0, 0, 255),
            fill_text="REDACTED", text_color=(255, 255, 255, 255),
        )

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        region = result[bounds.top:bounds.bottom, bounds.left:bounds.right]
        flat_fill = np.full(region.shape, (0, 0, 0, 255), dtype=np.uint8)
        assert not np.array_equal(region, flat_fill)
        # The text's own (white) color shows up somewhere in the box -
        # not an exact (255, 255, 255, 255) match, since the box is
        # small enough here that the fitted font size is tiny and every
        # glyph pixel is anti-aliased against the black fill rather
        # than solidly covered.
        assert np.any(region[:, :, :3].min(axis=-1) > 150)

    def test_solid_fill_text_stays_within_the_box_even_for_a_long_word_in_a_narrow_box(self):
        # A long preset word ("CONFIDENTIAL") in a box narrower than
        # its natural width must shrink to fit, not overflow past the
        # box or wrap onto a second line and bleed outside bounds.
        base_image = noisy_base_image(width=200, height=200)
        bounds = Rect(20, 80, 90, 120)  # a narrow, short box
        shape = ObfuscateShape(
            bounds, mode=ObfuscateMode.SOLID_FILL, fill_color=(0, 0, 0, 255),
            fill_text="CONFIDENTIAL", text_color=(255, 255, 255, 255),
        )

        result = render_to_numpy(200, 200, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        # Nothing white (the text color) appears outside the box - if
        # it overflowed, this fixture's black fill/dark base image
        # wouldn't otherwise produce white pixels anywhere else.
        outside_mask = np.ones((200, 200), dtype=bool)
        outside_mask[bounds.top:bounds.bottom, bounds.left:bounds.right] = False
        outside_region = result[outside_mask]
        assert not np.any(np.all(outside_region == (255, 255, 255, 255), axis=-1))

    def test_solid_fill_draws_the_translated_label_not_the_raw_stored_key(self):
        # fill_text is a stable, untranslated key (also a dict key and
        # a persisted .orcshot file field, so it must stay portable
        # across locales - see core/shapes.py's OBFUSCATE_FILL_TEXT_LABELS
        # docstring) - but what actually gets drawn onto the image
        # should be the *translated* label, not the raw key. Since
        # _() is inert under the test suite's fallback locale, the
        # label and the key are identical for a real preset like
        # "REDACTED" - so this monkeypatches the lookup table itself
        # to a value deliberately different from the key, the only
        # way to prove the render path is genuinely going through the
        # translation lookup rather than passing shape.fill_text
        # straight through (which would pass just as easily with an
        # identity mapping and give a false sense of coverage).
        import unittest.mock

        from orcshot.ui import render as render_module

        base_image = noisy_base_image()
        bounds = Rect(5, 5, 45, 45)
        shape = ObfuscateShape(
            bounds, mode=ObfuscateMode.SOLID_FILL, fill_color=(0, 0, 0, 255),
            fill_text="REDACTED", text_color=(255, 255, 255, 255),
        )

        with unittest.mock.patch.object(
            render_module, "OBFUSCATE_FILL_TEXT_LABELS", {"REDACTED": "TRANSLATED LABEL"},
        ), unittest.mock.patch.object(render_module, "_draw_fitted_centered_text") as mock_draw:
            render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        mock_draw.assert_called_once_with(
            unittest.mock.ANY, "TRANSLATED LABEL", shape.text_color, shape.bounds,
        )

    def test_scramble_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.SCRAMBLE)

        result = render_to_numpy(
            50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image, rng=ZeroRng2D())
        )

        expected = scramble(base_image, bounds, rng=ZeroRng2D())
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_scramble_with_no_explicit_rng_is_stable_across_repeated_renders(self):
        # Same pinned-seed contract as Pixelize (see that test's own
        # comment) - Scramble's noise must not reshuffle on every
        # unrelated repaint either.
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = ObfuscateShape(bounds, mode=ObfuscateMode.SCRAMBLE)

        first = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))
        second = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        assert np.array_equal(first, second)

    def test_scramble_with_no_explicit_rng_differs_between_distinct_shapes(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape_a = ObfuscateShape(bounds, mode=ObfuscateMode.SCRAMBLE)
        shape_b = ObfuscateShape(bounds, mode=ObfuscateMode.SCRAMBLE)

        result_a = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape_a, base_image=base_image))
        result_b = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape_b, base_image=base_image))

        assert not np.array_equal(result_a, result_b)

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


class TestRenderHighlight:
    def test_text_highlight_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = HighlightShape(bounds, mode=HighlightMode.TEXT_HIGHLIGHT, fill_color=(255, 255, 0, 255))

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = highlight_filter(base_image, bounds, (255, 255, 0, 255))
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_magnification_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = HighlightShape(bounds, mode=HighlightMode.MAGNIFICATION, magnification_factor=3)

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = magnify_filter(base_image, bounds, 3)
        region = expected[bounds.top:bounds.bottom, bounds.left:bounds.right]
        assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right], region)

    def test_text_highlight_and_magnification_paint_nothing_outside_bounds(self):
        # Like every ObfuscateMode (test_pixels_outside_bounds_are_left_
        # untouched_by_rendering above): render_shape never pre-paints
        # base_image onto the canvas itself, so "untouched" here means
        # nothing was painted at all - still transparent, not "matches
        # the original" (there's no original on a bare render_to_numpy
        # canvas to match against).
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)

        for shape in [
            HighlightShape(bounds, mode=HighlightMode.TEXT_HIGHLIGHT),
            HighlightShape(bounds, mode=HighlightMode.MAGNIFICATION),
        ]:
            result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))
            assert result[0:5, :, 3].max() == 0
            assert result[:, 0:5, 3].max() == 0

    def test_area_highlight_and_grayscale_paint_nothing_inside_bounds(self):
        # The "spotlight" modes affect everywhere *except* bounds - the
        # inverse of every other mode here, and of every ObfuscateMode -
        # so *inside* bounds is what stays unpainted/transparent for
        # these two, not outside.
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)

        for shape in [
            HighlightShape(bounds, mode=HighlightMode.AREA_HIGHLIGHT, brightness=0.5, blur_radius=3),
            HighlightShape(bounds, mode=HighlightMode.GRAYSCALE),
        ]:
            result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))
            inside = result[bounds.top:bounds.bottom, bounds.left:bounds.right]
            assert inside[:, :, 3].max() == 0

    def test_area_highlight_and_grayscale_paint_the_outside_of_bounds(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        outside_mask = np.ones((50, 50), dtype=bool)
        outside_mask[bounds.top:bounds.bottom, bounds.left:bounds.right] = False

        for shape in [
            HighlightShape(bounds, mode=HighlightMode.AREA_HIGHLIGHT, brightness=0.5, blur_radius=3),
            HighlightShape(bounds, mode=HighlightMode.GRAYSCALE),
        ]:
            result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))
            assert result[outside_mask][:, 3].min() == 255  # fully painted (opaque), not left transparent
            assert not np.array_equal(result[outside_mask], base_image[outside_mask])  # and actually filtered

    def test_area_highlight_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = HighlightShape(bounds, mode=HighlightMode.AREA_HIGHLIGHT, brightness=0.5, blur_radius=3)
        outside_mask = np.ones((50, 50), dtype=bool)
        outside_mask[bounds.top:bounds.bottom, bounds.left:bounds.right] = False

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = brightness_filter(base_image, bounds, 0.5, invert=True)
        expected = box_blur(expected, bounds, 3, invert=True)
        assert np.array_equal(result[outside_mask], expected[outside_mask])

    def test_grayscale_matches_the_filters_module_exactly(self):
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        shape = HighlightShape(bounds, mode=HighlightMode.GRAYSCALE)
        outside_mask = np.ones((50, 50), dtype=bool)
        outside_mask[bounds.top:bounds.bottom, bounds.left:bounds.right] = False

        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape, base_image=base_image))

        expected = grayscale_filter(base_image, bounds, invert=True)
        assert np.array_equal(result[outside_mask], expected[outside_mask])

    def test_a_shape_drawn_earlier_inside_bounds_survives_a_later_spotlight_highlight(self):
        # The clip-based "spotlight" paint must not blow away an
        # earlier-drawn shape sitting *inside* the highlight's own
        # bounds - only the region outside bounds should ever get
        # overpainted by the darkened/grayscaled content.
        base_image = noisy_base_image()
        bounds = Rect(5, 5, 35, 35)
        inner_rect = RectangleShape(
            Rect(10, 10, 20, 20), ShapeStyle(line_thickness=0, fill_color=(0, 255, 0, 255), shadow=False),
        )
        highlight = HighlightShape(bounds, mode=HighlightMode.GRAYSCALE)
        layer = Layer()
        layer.add(inner_rect)
        layer.add(highlight)

        result = render_to_numpy(50, 50, lambda ctx: render_layer(ctx, layer, base_image=base_image))

        assert np.array_equal(result[10:20, 10:20], np.full((10, 10, 4), (0, 255, 0, 255), dtype=np.uint8))

    def test_raises_a_clear_error_without_a_base_image(self):
        shape = HighlightShape(Rect(0, 0, 10, 10))
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
