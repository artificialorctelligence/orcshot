"""Cairo rendering for annotation shapes.

Behavioral port of RectangleContainer/EllipseContainer/LineContainer/
ArrowContainer/FreehandContainer's Draw methods, and the shared
DrawShadow helper (DrawableContainer.cs): 5 steps, alpha 100 down to 20
in steps of 20 (out of 255), each a black stroke of the shape's own
outline offset diagonally by 0..4px, drawn before the real shape.
FreehandContainer's Draw never calls DrawShadow - freehand strokes
never cast one, ported faithfully rather than added for consistency.

ArrowContainer defaults to ArrowHeadCombination.END_POINT, and
ArrowShape (core/shapes.py) has no field for the other combinations,
so only a single end-point arrowhead is drawn. Its exact geometry is a
deliberate simplification: GDI+'s AdjustableArrowCap(4, 6) has no
direct Cairo equivalent, so a filled triangle proportional to
line_thickness is used instead of reproducing that construction.

Text rendering (render_text) reuses render_rectangle for the box (same
line/fill/shadow fields as RectangleContainer) and lays the text out
via Pango/PangoCairo, since Cairo's own toy text API has no word-wrap
or font-family/style resolution. StepLabel rendering (render_step_label)
reuses render_ellipse for the circle and Pango for the centered,
auto-scaled number. SpeechBubble rendering (render_speech_bubble)
reuses the same Pango text-block helper for its text, a rounded-rect
path for the bubble, and the shape's own _tail_triangle() for the tail;
see render_speech_bubble's docstring for how its border drawing
reproduces the source's GDI+ exclude-clip trick via Cairo's even-odd
fill rule instead, and for the one remaining deliberate simplification
(the shadow step's cumulative-darkening quirk at the tail/bubble seam,
which the source has too - DrawShadow never clips either).

Icon/Cursor/Image rendering (render_icon/render_cursor/render_image)
just paint the shape's stored (H,W,4) numpy image scaled to fill
bounds; ImageShape's optional shadow is a tinted-silhouette
simplification, documented on render_image. Svg rendering (render_svg)
uses librsvg's render_document(ctx, viewport) directly - no
intermediate cached bitmap the way VectorGraphicsContainer keeps one,
since Cairo/librsvg can render straight onto the target context.

Every real shape type in core/shapes.py has a renderer now;
render_shape's NotImplementedError branch exists only as a fallback
for something outside that set (verified in tests with a dummy shape
type render.py has never heard of, not a real not-yet-done shape).

ObfuscateShape is unlike every other shape here: it has no visual
content of its own, so rendering it means re-filtering the region of
the *original captured image* under its bounds (via filters.py's
box_blur/pixelize) rather than drawing paths. That means render_shape
and render_layer need the base image passed in for it - an optional
``base_image`` parameter, unused by every other shape, that raises a
clear ValueError if an ObfuscateShape is rendered without one rather
than silently doing nothing.
"""

from __future__ import annotations

import math
from typing import Callable

import cairo
import gi
import numpy as np

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Rsvg", "2.0")
from gi.repository import Pango, PangoCairo, Rsvg

from greenshot_linux.core.drawing import Layer
from greenshot_linux.core.filters import box_blur, pixelize, scramble, solid_fill
from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import (
    ArrowShape,
    Color,
    CursorShape,
    EllipseShape,
    FreehandShape,
    IconShape,
    ImageShape,
    LineShape,
    ObfuscateMode,
    ObfuscateShape,
    RectangleShape,
    ShapeStyle,
    SpeechBubbleShape,
    StepLabelShape,
    SvgShape,
    TextShape,
    is_visible,
)
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface

_PANGO_ALIGNMENT = {
    "near": Pango.Alignment.LEFT,
    "center": Pango.Alignment.CENTER,
    "far": Pango.Alignment.RIGHT,
}

_SHADOW_START_ALPHA = 100
_SHADOW_ALPHA_STEP = 20


def _set_color(ctx: cairo.Context, color: Color) -> None:
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)


def _draw_shadow(
    ctx: cairo.Context, paint_step: Callable[[cairo.Context, int, int, int], None]
) -> None:
    """Ported from DrawableContainer.DrawShadow: calls ``paint_step``
    five times with decreasing black alpha (100 down to 20, in steps of
    20, out of 255) and increasing diagonal offset (0..4px). Each call
    is fully responsible for setting its own source color (using the
    given 0-255 alpha) and painting - stroking a path, filling text,
    or painting a tinted image - since what "casts a shadow" varies by
    shape.
    """
    alpha = _SHADOW_START_ALPHA
    step = 0
    while alpha >= 1:
        ctx.save()
        paint_step(ctx, step, step, alpha)
        ctx.restore()
        alpha -= _SHADOW_ALPHA_STEP
        step += 1


def _rectangle_path(ctx: cairo.Context, shape: RectangleShape, dx: int = 0, dy: int = 0) -> None:
    b = shape.bounds
    ctx.rectangle(b.left + dx, b.top + dy, b.width, b.height)


def render_rectangle(ctx: cairo.Context, shape: RectangleShape) -> None:
    style = shape.style
    line_visible = style.line_thickness > 0 and is_visible(style.line_color)
    fill_visible = is_visible(style.fill_color)

    if style.shadow and (line_visible or fill_visible):
        width = max(style.line_thickness, 1)

        def shadow_step(c, dx, dy, alpha):
            c.set_source_rgba(0, 0, 0, alpha / 255)
            c.set_line_width(width)
            _rectangle_path(c, shape, dx, dy)
            c.stroke()

        _draw_shadow(ctx, shadow_step)

    if fill_visible:
        ctx.save()
        _rectangle_path(ctx, shape)
        _set_color(ctx, style.fill_color)
        ctx.fill()
        ctx.restore()

    if line_visible:
        ctx.save()
        _rectangle_path(ctx, shape)
        _set_color(ctx, style.line_color)
        ctx.set_line_width(style.line_thickness)
        ctx.stroke()
        ctx.restore()


def _ellipse_path(ctx: cairo.Context, shape: EllipseShape, dx: int = 0, dy: int = 0) -> None:
    b = shape.bounds
    if b.width <= 0 or b.height <= 0:
        return
    cx, cy = b.left + b.width / 2 + dx, b.top + b.height / 2 + dy
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(b.width / 2, b.height / 2)
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()


def render_ellipse(ctx: cairo.Context, shape: EllipseShape) -> None:
    style = shape.style
    line_visible = style.line_thickness > 0 and is_visible(style.line_color)
    fill_visible = is_visible(style.fill_color)

    if style.shadow and (line_visible or fill_visible):
        width = max(style.line_thickness, 1)

        def shadow_step(c, dx, dy, alpha):
            c.set_source_rgba(0, 0, 0, alpha / 255)
            c.set_line_width(width)
            _ellipse_path(c, shape, dx, dy)
            c.stroke()

        _draw_shadow(ctx, shadow_step)

    if fill_visible:
        ctx.save()
        _ellipse_path(ctx, shape)
        _set_color(ctx, style.fill_color)
        ctx.fill()
        ctx.restore()

    if line_visible:
        ctx.save()
        _ellipse_path(ctx, shape)
        _set_color(ctx, style.line_color)
        ctx.set_line_width(style.line_thickness)
        ctx.stroke()
        ctx.restore()


def _line_path(ctx: cairo.Context, shape: LineShape, dx: int = 0, dy: int = 0) -> None:
    (x1, y1), (x2, y2) = shape.start, shape.end
    ctx.move_to(x1 + dx, y1 + dy)
    ctx.line_to(x2 + dx, y2 + dy)


def render_line(ctx: cairo.Context, shape: LineShape) -> None:
    style = shape.style
    if style.line_thickness <= 0:
        return

    if style.shadow:
        def shadow_step(c, dx, dy, alpha):
            c.set_source_rgba(0, 0, 0, alpha / 255)
            c.set_line_width(style.line_thickness)
            _line_path(c, shape, dx, dy)
            c.stroke()

        _draw_shadow(ctx, shadow_step)

    ctx.save()
    _line_path(ctx, shape)
    _set_color(ctx, style.line_color)
    ctx.set_line_width(style.line_thickness)
    ctx.stroke()
    ctx.restore()


def _arrowhead_path(ctx: cairo.Context, shape: ArrowShape, dx: int = 0, dy: int = 0) -> None:
    (x1, y1), (x2, y2) = shape.start, shape.end
    angle = math.atan2(y2 - y1, x2 - x1)
    length = shape.style.line_thickness * 3
    half_width = shape.style.line_thickness * 2

    tip = (x2 + dx, y2 + dy)
    back_x = tip[0] - length * math.cos(angle)
    back_y = tip[1] - length * math.sin(angle)
    perp = angle + math.pi / 2
    left = (back_x + half_width * math.cos(perp), back_y + half_width * math.sin(perp))
    right = (back_x - half_width * math.cos(perp), back_y - half_width * math.sin(perp))

    ctx.move_to(*tip)
    ctx.line_to(*left)
    ctx.line_to(*right)
    ctx.close_path()


def render_arrow(ctx: cairo.Context, shape: ArrowShape) -> None:
    style = shape.style
    if style.line_thickness <= 0:
        return

    if style.shadow:
        # Mirrors the main draw below: line stroked, arrowhead filled
        # separately - not a single combined path/stroke, since a
        # stroked-only closed triangle would render as a hollow outline
        # instead of the solid arrowhead the real (non-shadow) draw has.
        def shadow_step(c, dx, dy, alpha):
            c.set_source_rgba(0, 0, 0, alpha / 255)
            c.set_line_width(style.line_thickness)
            _line_path(c, shape, dx, dy)
            c.stroke()
            _arrowhead_path(c, shape, dx, dy)
            c.fill()

        _draw_shadow(ctx, shadow_step)

    ctx.save()
    _line_path(ctx, shape)
    _set_color(ctx, style.line_color)
    ctx.set_line_width(style.line_thickness)
    ctx.stroke()
    ctx.restore()

    ctx.save()
    _arrowhead_path(ctx, shape)
    _set_color(ctx, style.line_color)
    ctx.fill()
    ctx.restore()


def render_freehand(ctx: cairo.Context, shape: FreehandShape) -> None:
    style = shape.style
    if style.line_thickness <= 0 or len(shape.points) < 2:
        return

    ctx.save()
    ctx.move_to(*shape.points[0])
    for x, y in shape.points[1:]:
        ctx.line_to(x, y)
    _set_color(ctx, style.line_color)
    ctx.set_line_width(style.line_thickness)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()
    ctx.restore()


def _pango_layout(ctx: cairo.Context, text: str, family: str, size: float, bold: bool, italic: bool,
                   alignment: str, width_px: float) -> Pango.Layout:
    layout = PangoCairo.create_layout(ctx)
    weight = "Bold " if bold else ""
    slant = "Italic " if italic else ""
    layout.set_font_description(Pango.FontDescription.from_string(f"{family} {weight}{slant}{size}"))
    layout.set_text(text, -1)
    layout.set_alignment(_PANGO_ALIGNMENT[alignment])
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    layout.set_width(max(0, int(width_px * Pango.SCALE)))
    return layout


def vertical_text_offset(vertical_alignment: str, box_height: float, text_height: float) -> float:
    if vertical_alignment == "center":
        return (box_height - text_height) / 2
    if vertical_alignment == "far":
        return box_height - text_height
    return 0


def _text_shadow_visible(style: ShapeStyle) -> bool:
    """Matches TextContainer.Draw: drawShadow = shadow && fill is
    transparent - independent of the box's own shadow condition
    (fillVisible || lineVisible), which render_rectangle already
    handles for the box drawn underneath the text.
    """
    return style.shadow and not is_visible(style.fill_color)


def _draw_text_block(
    ctx: cairo.Context, rect: Rect, text: str, font_family: str, font_size: float, bold: bool, italic: bool,
    horizontal_alignment: str, vertical_alignment: str, line_thickness: int, color: Color, draw_shadow: bool,
) -> None:
    """Shared by render_text and render_speech_bubble: both inset the
    given rect by ceil(line_thickness / 2), lay out text via Pango, and
    optionally cast the same 5-step DrawShadow. They differ only in
    which rect and shadow-visibility condition apply - render_text's
    shadow is gated on the box's fill being transparent
    (_text_shadow_visible), render_speech_bubble's isn't (it passes the
    raw ``shadow`` field straight through, matching
    SpeechbubbleContainer.Draw calling TextContainer.DrawText itself
    rather than going through TextContainer.Draw's own gating).
    """
    if not text:
        return

    text_offset = math.ceil(line_thickness / 2) if line_thickness > 0 else 0
    inner = Rect(rect.left + text_offset, rect.top + text_offset, rect.right - text_offset, rect.bottom - text_offset)

    layout = _pango_layout(ctx, text, font_family, font_size, bold, italic, horizontal_alignment, inner.width)
    _, text_height = layout.get_pixel_size()
    y = inner.top + vertical_text_offset(vertical_alignment, inner.height, text_height)

    if draw_shadow:
        def shadow_step(c, dx, dy, alpha):
            c.set_source_rgba(0, 0, 0, alpha / 255)
            c.move_to(inner.left + dx, y + dy)
            PangoCairo.show_layout(c, layout)

        _draw_shadow(ctx, shadow_step)

    ctx.save()
    _set_color(ctx, color)
    ctx.move_to(inner.left, y)
    PangoCairo.show_layout(ctx, layout)
    ctx.restore()


def render_text(ctx: cairo.Context, shape: TextShape) -> None:
    render_rectangle(ctx, RectangleShape(shape.bounds, shape.style))
    style = shape.style
    _draw_text_block(
        ctx, shape.bounds, shape.text, shape.font_family, shape.font_size, shape.bold, shape.italic,
        shape.horizontal_alignment, shape.vertical_alignment,
        style.line_thickness, style.line_color, _text_shadow_visible(style),
    )


def render_step_label(ctx: cairo.Context, shape: StepLabelShape) -> None:
    render_ellipse(ctx, EllipseShape(shape.bounds, shape.style))

    b = shape.bounds
    if b.width <= 0 or b.height <= 0:
        return

    text = str(shape.number)
    font_size = 0.7 * min(b.width, b.height)
    layout = _pango_layout(ctx, text, "sans-serif", font_size, True, False, "center", b.width)
    _, text_height = layout.get_pixel_size()

    ctx.save()
    _set_color(ctx, shape.style.line_color)
    ctx.move_to(b.left, b.top + (b.height - text_height) / 2)
    PangoCairo.show_layout(ctx, layout)
    ctx.restore()


def _rounded_rect_path(ctx: cairo.Context, rect: Rect, radius: float, dx: int = 0, dy: int = 0) -> None:
    x, y, w, h, r = rect.left + dx, rect.top + dy, rect.width, rect.height, radius
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def bubble_corner_radius(shape: SpeechBubbleShape) -> float:
    # Ported from CreateBubble: capped at 30, adapted down for small
    # boxes and thick borders.
    b = shape.bubble_bounds
    return min(30, min(b.width, b.height) / 2 - shape.style.line_thickness)


def _bubble_path(ctx: cairo.Context, shape: SpeechBubbleShape, dx: int = 0, dy: int = 0) -> None:
    b = shape.bubble_bounds
    radius = bubble_corner_radius(shape)
    if radius > 0:
        _rounded_rect_path(ctx, b, radius, dx, dy)
    else:
        ctx.rectangle(b.left + dx, b.top + dy, b.width, b.height)


def _tail_path(ctx: cairo.Context, shape: SpeechBubbleShape, dx: int = 0, dy: int = 0) -> bool:
    # Reuses the shape's own tail geometry (also used for hit-testing)
    # rather than a second, potentially-divergent implementation here.
    triangle = shape._tail_triangle()
    if triangle is None:
        return False
    (x1, y1), (x2, y2), (x3, y3) = triangle
    ctx.move_to(x1 + dx, y1 + dy)
    ctx.line_to(x2 + dx, y2 + dy)
    ctx.line_to(x3 + dx, y3 + dy)
    ctx.close_path()
    return True


def _clip_excluding(ctx: cairo.Context, exclude_path_fn, outer: Rect) -> None:
    """Clips to ``outer`` minus whatever path ``exclude_path_fn`` adds -
    Cairo has no CombineMode.Exclude, but an even-odd-filled rectangle
    with a second subpath punched into it (region_select.py's own "dim
    everything but the selection" trick) clips out that subpath just
    the same. ``outer`` needs to comfortably cover every pixel either
    shape's own stroke could touch - a too-tight rectangle would clip
    away part of the *visible* edge, not just the excluded region.
    """
    ctx.new_path()
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(outer.left, outer.top, outer.width, outer.height)
    exclude_path_fn(ctx)
    ctx.clip()


def render_speech_bubble(ctx: cairo.Context, shape: SpeechBubbleShape) -> None:
    """SpeechbubbleContainer.Draw (SpeechbubbleContainer.cs:236-333):
    tail border, bubble fill, bubble border, tail fill, in that order -
    both borders are drawn full-strength but *clipped to exclude the
    other shape* (bubble border excludes the tail's own area and vice
    versa), so the tail's two edges and the bubble's rounded outline
    meet as one continuous seam instead of either double-stroking or
    (this port's previous behavior) just letting the bubble's opaque
    fill paper over whatever part of the tail's border fell inside it,
    which left no border at all along the seam. CombineMode.Exclude has
    no direct Cairo equivalent; _clip_excluding reproduces it via an
    even-odd fill rule instead (see its own docstring).

    One faithful-but-odd detail kept as-is: the source draws the tail's
    border unconditionally, without the ``lineVisible`` guard the
    bubble's own border draw has just below it (SpeechbubbleContainer.
    cs:284-291 vs. 307-321) - almost certainly an oversight rather than
    a deliberate effect (a zero-width GDI+ Pen still draws a hairline),
    but replicating a lineThickness=0-yet-still-drawn tail border would
    be a stranger, more surprising deviation from this shape's own
    line_visible gating (and from every other shape's) than just not
    reproducing it - so both border draws here are gated on
    line_visible the same way.
    """
    style = shape.style
    line_visible = style.line_thickness > 0 and is_visible(style.line_color)
    fill_visible = is_visible(style.fill_color)
    has_tail = shape._tail_triangle() is not None

    if style.shadow and (line_visible or fill_visible):
        def shadow_step(c, dx, dy, alpha):
            c.set_source_rgba(0, 0, 0, alpha / 255)
            c.set_line_width(max(style.line_thickness, 1))
            if _tail_path(c, shape, dx, dy):
                c.stroke()
            _bubble_path(c, shape, dx, dy)
            c.stroke()

        _draw_shadow(ctx, shadow_step)

    # Padded past both the bubble and the tail's own bounds (shape.bounds
    # already unions them) so the exclude-clip's own rectangle edge
    # never cuts into a stroke that's actually meant to be visible.
    outer = shape.bounds
    pad = style.line_thickness + 4
    outer = Rect(outer.left - pad, outer.top - pad, outer.right + pad, outer.bottom + pad)

    if line_visible and has_tail:
        ctx.save()
        _clip_excluding(ctx, lambda c: _bubble_path(c, shape), outer)
        _tail_path(ctx, shape)
        _set_color(ctx, style.line_color)
        ctx.set_line_width(style.line_thickness)
        ctx.stroke()
        ctx.restore()

    if fill_visible:
        ctx.save()
        _bubble_path(ctx, shape)
        _set_color(ctx, style.fill_color)
        ctx.fill()
        ctx.restore()

    if line_visible:
        ctx.save()
        if has_tail:
            _clip_excluding(ctx, lambda c: _tail_path(c, shape), outer)
        _bubble_path(ctx, shape)
        _set_color(ctx, style.line_color)
        ctx.set_line_width(style.line_thickness)
        ctx.stroke()
        ctx.restore()

    if fill_visible and has_tail:
        ctx.save()
        _tail_path(ctx, shape)
        _set_color(ctx, style.fill_color)
        ctx.fill()
        ctx.restore()

    _draw_text_block(
        ctx, shape.bubble_bounds, shape.text, shape.font_family, shape.font_size, shape.bold, shape.italic,
        shape.horizontal_alignment, shape.vertical_alignment,
        style.line_thickness, style.line_color, style.shadow,
    )


def _paint_image_scaled(ctx: cairo.Context, image, rect: Rect, dx: int = 0, dy: int = 0) -> None:
    if rect.width <= 0 or rect.height <= 0:
        return
    img_h, img_w = image.shape[:2]
    surface = numpy_to_cairo_surface(image)
    ctx.save()
    ctx.translate(rect.left + dx, rect.top + dy)
    ctx.scale(rect.width / img_w, rect.height / img_h)
    ctx.set_source_surface(surface, 0, 0)
    ctx.paint()
    ctx.restore()


def render_icon(ctx: cairo.Context, shape: IconShape) -> None:
    _paint_image_scaled(ctx, shape.image, shape.bounds)


def render_cursor(ctx: cairo.Context, shape: CursorShape) -> None:
    _paint_image_scaled(ctx, shape.image, shape.bounds)


def render_image(ctx: cairo.Context, shape: ImageShape) -> None:
    if shape.shadow:
        # Deliberate simplification vs. CheckShadow's separate
        # _shadowBitmap: tint the image's own RGB to black, keep its
        # alpha channel as the silhouette shape, and paint that with
        # per-step alpha - same 5-step offsets as everywhere else, plus
        # the source's own literal +1 "shadowOffset" on top of them.
        silhouette = shape.image.copy()
        silhouette[:, :, :3] = 0
        img_h, img_w = shape.image.shape[:2]
        surface = numpy_to_cairo_surface(silhouette)
        b = shape.bounds

        def shadow_step(c, dx, dy, alpha):
            c.save()
            c.translate(b.left + dx + 1, b.top + dy + 1)
            c.scale(b.width / img_w, b.height / img_h)
            c.set_source_surface(surface, 0, 0)
            c.paint_with_alpha(alpha / 255)
            c.restore()

        _draw_shadow(ctx, shadow_step)

    _paint_image_scaled(ctx, shape.image, shape.bounds)


def render_svg(ctx: cairo.Context, shape: SvgShape) -> None:
    b = shape.bounds
    if b.width <= 0 or b.height <= 0:
        return

    handle = Rsvg.Handle.new_from_data(shape.svg_data.encode("utf-8"))
    viewport = Rsvg.Rectangle()
    viewport.x, viewport.y, viewport.width, viewport.height = b.left, b.top, b.width, b.height

    ctx.save()
    handle.render_document(ctx, viewport)
    ctx.restore()


def render_obfuscate(ctx: cairo.Context, shape: ObfuscateShape, base_image, rng=None) -> None:
    image_bounds = Rect(0, 0, base_image.shape[1], base_image.shape[0])
    apply_rect = shape.bounds.intersect(image_bounds)
    if apply_rect is None:
        return

    # No explicit rng override (the normal, non-test path): derive from
    # the shape's own pinned seed rather than pixelize/scramble's
    # default fresh-random-every-call behavior, so repeated redraws of
    # the same unchanged shape don't visibly reshuffle the noise - see
    # ObfuscateShape.seed's docstring for why this is still safe.
    if shape.mode is ObfuscateMode.BLUR:
        filtered = box_blur(base_image, shape.bounds, shape.amount)
    elif shape.mode is ObfuscateMode.PIXELIZE:
        pixelize_rng = rng if rng is not None else np.random.default_rng(shape.seed)
        filtered = pixelize(base_image, shape.bounds, shape.amount, rng=pixelize_rng)
    elif shape.mode is ObfuscateMode.SOLID_FILL:
        filtered = solid_fill(base_image, shape.bounds, shape.fill_color)
    else:  # ObfuscateMode.SCRAMBLE
        scramble_rng = rng if rng is not None else np.random.default_rng(shape.seed)
        filtered = scramble(base_image, shape.bounds, rng=scramble_rng)

    region = filtered[apply_rect.top : apply_rect.bottom, apply_rect.left : apply_rect.right]
    surface = numpy_to_cairo_surface(region)
    ctx.save()
    ctx.set_source_surface(surface, apply_rect.left, apply_rect.top)
    ctx.paint()
    ctx.restore()


_RENDERERS = {
    RectangleShape: render_rectangle,
    EllipseShape: render_ellipse,
    LineShape: render_line,
    ArrowShape: render_arrow,
    FreehandShape: render_freehand,
    TextShape: render_text,
    StepLabelShape: render_step_label,
    SpeechBubbleShape: render_speech_bubble,
    IconShape: render_icon,
    CursorShape: render_cursor,
    ImageShape: render_image,
    SvgShape: render_svg,
}


def render_shape(ctx: cairo.Context, shape, base_image=None, rng=None) -> None:
    if isinstance(shape, ObfuscateShape):
        if base_image is None:
            raise ValueError("rendering an ObfuscateShape requires base_image")
        render_obfuscate(ctx, shape, base_image, rng=rng)
        return

    renderer = _RENDERERS.get(type(shape))
    if renderer is None:
        raise NotImplementedError(f"no renderer yet for {type(shape).__name__}")
    renderer(ctx, shape)


def render_layer(ctx: cairo.Context, layer: Layer, base_image=None, rng=None) -> None:
    for shape in layer:
        render_shape(ctx, shape, base_image=base_image, rng=rng)
