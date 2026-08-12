"""Cairo rendering of SpeechBubbleShape.

Behavioral port of SpeechbubbleContainer.Draw: a rounded-rectangle
bubble (CreateBubble: corner radius up to 30, adapted to the smaller
side and line thickness) plus a triangular tail (reusing
SpeechBubbleShape._tail_triangle - the exact same geometry the shape's
own hit test already uses, kept in one place rather than duplicated),
then text via the shared _draw_text_block helper.

The source's GDI+ clip-region trick (SetClip + CombineMode.Exclude, so
each border only shows where the *other* shape doesn't cover it,
avoiding a seam where they meet) is reproduced via Cairo's even-odd
fill rule instead (render_speech_bubble's own docstring/_clip_excluding)
- an earlier version of this port just drew the tail first and let the
bubble's opaque fill paper over the overlap, which looked fine with a
visible fill but left the bubble's own border running straight across
the tail's base with a transparent fill (see
test_bubble_border_has_no_seam_across_the_tail_base below).

Also simplified: the source's shadow uses a cumulative Matrix.Translate
(1, 1) applied to the *same* path object on every DrawShadow iteration,
giving offsets of 1..5px rather than the 0..4px every other shape here
uses (Rectangle/Ellipse/Line/Arrow all index shadow offset by
DrawShadow's own currentStep). That's treated as a source quirk, not
reproduced - render_speech_bubble uses the same 0..4px step convention
as everything else for consistency.

The bubble's own text shadow is *not* gated on fill transparency the
way TextShape's is: SpeechbubbleContainer.Draw calls
TextContainer.DrawText directly with the raw shadow field, bypassing
TextContainer.Draw's own "only if fill is transparent" condition.
"""

import cairo
import numpy as np

from orcshot.core.geometry import Rect
from orcshot.core.shapes import ShapeStyle, SpeechBubbleShape, TRANSPARENT
from orcshot.ui.cairo_convert import cairo_surface_to_numpy
from orcshot.ui.render import render_shape


def render_to_numpy(width, height, draw):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    draw(ctx)
    surface.flush()
    return cairo_surface_to_numpy(surface)


class TestRenderSpeechBubble:
    def test_fills_the_bubble_interior(self):
        style = ShapeStyle(line_thickness=0, fill_color=(10, 20, 30, 255), shadow=False)
        shape = SpeechBubbleShape(Rect(10, 10, 90, 60), target=(50, 200), text="", style=style)
        result = render_to_numpy(150, 150, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[35, 50][:3]) == (10, 20, 30)

    def test_draws_a_tail_reaching_toward_the_target(self):
        style = ShapeStyle(line_thickness=0, fill_color=(10, 20, 30, 255), shadow=False)
        # target well below the bubble - the tail should paint fill-
        # colored pixels below bubble_bounds.bottom (60).
        shape = SpeechBubbleShape(Rect(10, 10, 90, 60), target=(50, 200), text="", style=style)
        result = render_to_numpy(150, 220, lambda ctx: render_shape(ctx, shape))
        below_bubble = result[65:120, :, :3]
        matches = np.all(np.abs(below_bubble.astype(int) - np.array([10, 20, 30])) <= 5, axis=-1)
        assert matches.any()

    def test_draws_text_inside_the_bubble(self):
        style = ShapeStyle(line_thickness=0, line_color=(0, 200, 0, 255), fill_color=TRANSPARENT, shadow=False)
        shape = SpeechBubbleShape(Rect(0, 0, 120, 60), target=(200, 200), text="Hi", font_size=16, style=style)
        result = render_to_numpy(120, 60, lambda ctx: render_shape(ctx, shape))
        diff = np.abs(result[:, :, :3].astype(int) - np.array([0, 200, 0]))
        assert bool(np.any(diff.max(axis=2) <= 20))

    def test_handles_target_coinciding_with_bubble_center_without_crashing(self):
        # A wide, short box: the centered "hi" text (default alignment)
        # sits in the horizontal middle, so a point near the left edge
        # (but past the rounded corner) is unaffected by it.
        style = ShapeStyle(line_thickness=0, fill_color=(10, 20, 30, 255), shadow=True)
        bounds = Rect(0, 0, 200, 100)
        center = (100, 50)
        shape = SpeechBubbleShape(bounds, target=center, text="hi", style=style)
        result = render_to_numpy(200, 100, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[50, 10][:3]) == (10, 20, 30)

    def test_text_shadow_is_not_suppressed_by_a_visible_fill(self):
        # Unlike TextShape, this must not raise/crash and must still
        # render the box + text with a visible fill and shadow=True
        # together (the combination render_text's _text_shadow_visible
        # would otherwise suppress the text shadow for).
        style = ShapeStyle(line_thickness=0, fill_color=(255, 255, 255, 255), line_color=(0, 0, 255, 255), shadow=True)
        bounds = Rect(0, 0, 200, 100)
        shape = SpeechBubbleShape(bounds, target=(100, 300), text="Hi", style=style)
        result = render_to_numpy(200, 100, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[50, 10][:3]) == (255, 255, 255)

    def test_bubble_border_has_no_seam_across_the_tail_base(self):
        # SpeechbubbleContainer.Draw clips each border to exclude the
        # *other* shape (SpeechbubbleContainer.cs:284-321) - the
        # bubble's own border doesn't run across the tail's base, it
        # leaves a gap there for the tail to emerge from. A straight-
        # down tail with a transparent fill (nothing to visually paper
        # over a bug with) makes this checkable pixel-by-pixel: with a
        # target directly below bounds' horizontal center, the tail's
        # base sits at the bubble's own vertical center (see
        # SpeechBubbleShape._tail_triangle - both base points are
        # bubble-center +/- tail_width, not on bounds' own edge), so
        # dead center of the bottom edge (100, 100) is inside the
        # tail's own triangle, not on either of its two slanted edges -
        # nothing should paint there at all.
        style = ShapeStyle(line_thickness=4, line_color=(0, 0, 255, 255), fill_color=TRANSPARENT, shadow=False)
        bounds = Rect(0, 0, 200, 100)
        shape = SpeechBubbleShape(bounds, target=(100, 250), text="", style=style)
        result = render_to_numpy(200, 260, lambda ctx: render_shape(ctx, shape))
        assert result[100, 100][3] == 0
        # Well clear of the tail (past its rounded corner too), the
        # bubble's own bottom border is untouched.
        assert result[100, 50][3] > 0
