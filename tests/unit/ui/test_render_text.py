"""Cairo rendering of TextShape and StepLabelShape.

Behavioral port of TextContainer.Draw/DrawText and
StepLabelContainer.Draw. Text's box (fill/outline/shadow) is exactly
RectangleContainer's — reused via render_rectangle — with the text
itself laid out via Pango (PangoCairo), since Cairo's own toy text API
has no word-wrap or font-family/style resolution. Font metrics vary by
system font config, so these tests avoid asserting exact pixel
positions and instead check relative/structural properties (some text
was drawn, alignment shifts it left/right or up/down) that hold
regardless of the installed font.

StepLabelContainer draws its circle via EllipseContainer.DrawEllipse
(reused via render_ellipse) then centers a number via
TextContainer.DrawText with line_thickness=0 (no inset) and no shadow.
The auto-scaled font size (~0.7 * min(width, height) in the source, via
a measured-text aspect-ratio correction) is simplified here to a flat
0.7 * min(width, height) - the correction mostly matters for multi-
digit numbers in a non-square box, a rare case for a step counter.
"""

import cairo
import numpy as np

from orcshot.core.geometry import Rect
from orcshot.core.shapes import RectangleShape, ShapeStyle, StepLabelShape, TextShape, TRANSPARENT
from orcshot.ui.cairo_convert import cairo_surface_to_numpy
from orcshot.ui.render import _text_shadow_visible, render_shape


def render_to_numpy(width, height, draw):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    draw(ctx)
    surface.flush()
    return cairo_surface_to_numpy(surface)


def _colored_pixel_bounds(result, color, tolerance=30):
    """(min_x, min_y, max_x, max_y) of pixels close to ``color``, or
    None if there are none."""
    diff = np.abs(result[:, :, :3].astype(int) - np.array(color[:3]))
    mask = (diff.max(axis=2) <= tolerance) & (result[:, :, 3] > 0)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max(), ys.max()


class TestRenderText:
    def test_draws_the_box_like_a_rectangle(self):
        style = ShapeStyle(line_thickness=0, fill_color=(10, 20, 30, 255), shadow=False)
        shape = TextShape(Rect(5, 5, 55, 35), text="", style=style)
        result = render_to_numpy(60, 40, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[20, 30]) == (10, 20, 30, 255)

    def test_empty_text_draws_only_the_box_without_erroring(self):
        style = ShapeStyle(line_thickness=0, fill_color=TRANSPARENT, shadow=False)
        shape = TextShape(Rect(5, 5, 55, 35), text="", style=style)
        result = render_to_numpy(60, 40, lambda ctx: render_shape(ctx, shape))
        assert result[:, :, 3].max() == 0

    def test_draws_some_text_colored_pixels_within_bounds(self):
        style = ShapeStyle(line_thickness=0, line_color=(0, 200, 0, 255), fill_color=TRANSPARENT, shadow=False)
        shape = TextShape(Rect(0, 0, 100, 40), text="Hi", font_size=20, style=style)
        result = render_to_numpy(100, 40, lambda ctx: render_shape(ctx, shape))
        bounds = _colored_pixel_bounds(result, (0, 200, 0))
        assert bounds is not None

    def test_horizontal_near_alignment_puts_text_left_of_far_alignment(self):
        style = ShapeStyle(line_thickness=0, line_color=(0, 200, 0, 255), fill_color=TRANSPARENT, shadow=False)
        near = TextShape(Rect(0, 0, 200, 40), text="Hi", font_size=16, horizontal_alignment="near", style=style)
        far = TextShape(Rect(0, 0, 200, 40), text="Hi", font_size=16, horizontal_alignment="far", style=style)

        near_result = render_to_numpy(200, 40, lambda ctx: render_shape(ctx, near))
        far_result = render_to_numpy(200, 40, lambda ctx: render_shape(ctx, far))

        near_bounds = _colored_pixel_bounds(near_result, (0, 200, 0))
        far_bounds = _colored_pixel_bounds(far_result, (0, 200, 0))
        assert near_bounds[0] < far_bounds[0]  # near's leftmost text pixel is further left

    def test_vertical_near_alignment_puts_text_above_far_alignment(self):
        style = ShapeStyle(line_thickness=0, line_color=(0, 200, 0, 255), fill_color=TRANSPARENT, shadow=False)
        near = TextShape(Rect(0, 0, 100, 200), text="Hi", font_size=16, vertical_alignment="near", style=style)
        far = TextShape(Rect(0, 0, 100, 200), text="Hi", font_size=16, vertical_alignment="far", style=style)

        near_result = render_to_numpy(100, 200, lambda ctx: render_shape(ctx, near))
        far_result = render_to_numpy(100, 200, lambda ctx: render_shape(ctx, far))

        near_bounds = _colored_pixel_bounds(near_result, (0, 200, 0))
        far_bounds = _colored_pixel_bounds(far_result, (0, 200, 0))
        assert near_bounds[1] < far_bounds[1]  # near's topmost text pixel is higher up


class TestTextShadowVisible:
    # Direct test of the exact source condition (TextContainer.Draw:
    # drawShadow = shadow && fillColor is transparent), independent of
    # the box's own separate shadow condition - see render_text's box
    # shadow, handled entirely by the reused render_rectangle.
    def test_true_when_shadow_enabled_and_fill_transparent(self):
        assert _text_shadow_visible(ShapeStyle(fill_color=TRANSPARENT, shadow=True)) is True

    def test_false_when_shadow_disabled(self):
        assert _text_shadow_visible(ShapeStyle(fill_color=TRANSPARENT, shadow=False)) is False

    def test_false_when_fill_is_visible_even_with_shadow_enabled(self):
        assert _text_shadow_visible(ShapeStyle(fill_color=(1, 2, 3, 255), shadow=True)) is False


class TestRenderStepLabel:
    def test_draws_the_circle_like_an_ellipse(self):
        shape = StepLabelShape(Rect(0, 0, 40, 40), number=1)
        result = render_to_numpy(40, 40, lambda ctx: render_shape(ctx, shape))
        # sample away from dead center - a large centered digit glyph can
        # cover the exact middle pixel. Default fill is DarkRed (139,0,0).
        # Tolerant, not exact - confirmed live on a real Launchpad PPA
        # build farm chroot (different fontconfig/Cairo antialiasing
        # defaults than this dev machine): the white "1" glyph's
        # subpixel-antialiased edge reached this pixel and produced
        # (139, 3, 38), colored fringing from the AA mode difference,
        # not a real rendering bug - same class of environment
        # sensitivity test_draws_the_number_in_a_contrasting_color
        # below already tolerates via _colored_pixel_bounds's own
        # tolerance parameter.
        pixel = tuple(int(c) for c in result[10, 10][:3])
        assert max(abs(a - b) for a, b in zip(pixel, (139, 0, 0))) <= 40

    def test_draws_the_number_in_a_contrasting_color(self):
        shape = StepLabelShape(Rect(0, 0, 40, 40), number=7)
        result = render_to_numpy(40, 40, lambda ctx: render_shape(ctx, shape))
        # default line_color (used as the number's color) is White
        bounds = _colored_pixel_bounds(result, (255, 255, 255), tolerance=10)
        assert bounds is not None

    def test_default_style_casts_no_shadow(self):
        # The default style has shadow=False, so neither the circle
        # (EllipseContainer.DrawEllipse, which *does* respect the style's
        # shadow flag) nor the text (TextContainer.DrawText, called with
        # a hardcoded drawShadow=false regardless of the style) casts one.
        shape = StepLabelShape(Rect(10, 10, 50, 50), number=1)
        result = render_to_numpy(60, 60, lambda ctx: render_shape(ctx, shape))
        # a shadow would appear as near-black pixels beyond the circle's
        # own diagonal extent (bottom-right of bounds)
        band = result[52:58, 52:58]
        assert band[:, :, 3].max() == 0
