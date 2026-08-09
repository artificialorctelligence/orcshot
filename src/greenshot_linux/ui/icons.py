"""Toolbar icons for the drawing tools: small Cairo-drawn icons, not a
downloaded/bundled icon pack - no icon theme has standardized names
for "rectangle annotation tool" etc. Where a tool already has a real
renderer (Rectangle/Ellipse/Line/Arrow/Freehand, see ui/render.py),
its icon reuses that exact render_* function on a miniature shape, so
the icon can never visually drift from what the tool actually draws.
Pixelize/Blur have no small-scale renderer to reuse (obfuscation needs
a base image to filter against), so those stay hand-drawn and
deliberately colorful - they represent colorful image content, not
line art, so the theme foreground color doesn't apply to them. Text
has no small-scale Pango layout worth reusing for a single glyph, so
it's hand-drawn too, but *is* theme-colored like the other line art.

Every line-art icon (Rectangle/Ellipse/Line/Arrow/Freehand/Text) takes
a ``color`` parameter rather than hardcoding one - a real bug, caught
live: the first version hardcoded a fixed dark gray, which was nearly
invisible against a dark toolbar theme (reported by screenshot, root-
caused to this file). editor_window.py queries the window's actual
style-context foreground color (Gtk.StateFlags.NORMAL - confirmed
empirically to resolve correctly even before the window is realized/
shown) and passes it in, so these icons follow light/dark theme the
same way the standard freedesktop theme icons already do.

The generic action buttons (Undo/Redo/Copy/Save/Print) don't go
through here at all - editor_window.py builds those straight from
standard freedesktop theme icon names (Gtk.Image.new_from_icon_name),
confirmed present via Gtk.IconTheme.has_icon before relying on them.
"""

from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gtk

from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import (
    ArrowShape, Color, EllipseShape, FreehandShape, LineShape, RectangleShape, ShapeStyle,
    SpeechBubbleShape, StepLabelShape,
)
from greenshot_linux.core.tools import Tool
from greenshot_linux.ui.render import (
    render_arrow, render_ellipse, render_freehand, render_line, render_rectangle,
    render_speech_bubble, render_step_label,
)

ICON_SIZE = 24
_MARGIN = 4
_DEFAULT_COLOR: Color = (60, 60, 60, 255)


def _blank_surface() -> cairo.ImageSurface:
    return cairo.ImageSurface(cairo.FORMAT_ARGB32, ICON_SIZE, ICON_SIZE)


def _line_art_style(color: Color) -> ShapeStyle:
    return ShapeStyle(line_thickness=2, line_color=color, fill_color=(0, 0, 0, 0), shadow=False)


def _rectangle_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    shape = RectangleShape(Rect(_MARGIN, _MARGIN, ICON_SIZE - _MARGIN, ICON_SIZE - _MARGIN), _line_art_style(color))
    render_rectangle(cairo.Context(surface), shape)
    return surface


def _ellipse_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    shape = EllipseShape(Rect(_MARGIN, _MARGIN, ICON_SIZE - _MARGIN, ICON_SIZE - _MARGIN), _line_art_style(color))
    render_ellipse(cairo.Context(surface), shape)
    return surface


def _line_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    shape = LineShape(start=(_MARGIN, ICON_SIZE - _MARGIN), end=(ICON_SIZE - _MARGIN, _MARGIN), style=_line_art_style(color))
    render_line(cairo.Context(surface), shape)
    return surface


def _arrow_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    shape = ArrowShape(start=(_MARGIN, ICON_SIZE - _MARGIN), end=(ICON_SIZE - _MARGIN, _MARGIN), style=_line_art_style(color))
    render_arrow(cairo.Context(surface), shape)
    return surface


def _freehand_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    points = (
        (_MARGIN, ICON_SIZE - _MARGIN),
        (ICON_SIZE * 0.4, _MARGIN),
        (ICON_SIZE * 0.6, ICON_SIZE - _MARGIN),
        (ICON_SIZE - _MARGIN, _MARGIN),
    )
    shape = FreehandShape(points=points, style=_line_art_style(color))
    render_freehand(cairo.Context(surface), shape)
    return surface


def _pixelize_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    block = (ICON_SIZE - 2 * _MARGIN) / 3
    colors = [(0.75, 0.3, 0.3), (0.3, 0.55, 0.75), (0.85, 0.7, 0.25)]
    for row in range(3):
        for col in range(3):
            ctx.set_source_rgb(*colors[(row + col) % 3])
            ctx.rectangle(_MARGIN + col * block, _MARGIN + row * block, block, block)
            ctx.fill()
    return surface


def _blur_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    # a few overlapping soft-alpha circles, standing in for "blur"
    for step, alpha in enumerate((0.15, 0.25, 0.45)):
        r = (ICON_SIZE / 2 - _MARGIN) - step * 2
        ctx.set_source_rgba(0.25, 0.35, 0.8, alpha)
        ctx.arc(cx, cy, r, 0, 2 * math.pi)
        ctx.fill()
    return surface


def _solid_fill_icon(color: Color) -> cairo.ImageSurface:
    # Ignores ``color`` like Pixelize/Blur - always drawn in a fixed
    # dark tone regardless of the current line/fill color, standing in
    # for Solid Fill's own default (opaque black) redaction color.
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.1, 0.1, 0.1)
    ctx.rectangle(_MARGIN, _MARGIN, ICON_SIZE - 2 * _MARGIN, ICON_SIZE - 2 * _MARGIN)
    ctx.fill()
    return surface


def _scramble_icon(color: Color) -> cairo.ImageSurface:
    # A fixed speckle pattern, not live randomness (icons must render
    # identically every time) - stands in for Color Scramble's own
    # synthesized noise, visually distinct from Pixelize's clean grid.
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    speckles = [
        (0.30, 0.28, 2.6, (0.75, 0.35, 0.55)),
        (0.55, 0.20, 2.0, (0.35, 0.65, 0.42)),
        (0.78, 0.40, 2.4, (0.30, 0.42, 0.68)),
        (0.40, 0.55, 2.2, (0.68, 0.60, 0.30)),
        (0.68, 0.62, 2.8, (0.42, 0.68, 0.65)),
        (0.22, 0.68, 2.0, (0.62, 0.32, 0.62)),
        (0.50, 0.78, 2.6, (0.55, 0.55, 0.35)),
        (0.85, 0.80, 2.0, (0.35, 0.55, 0.75)),
    ]
    for fx, fy, radius, (r, g, b) in speckles:
        ctx.set_source_rgb(r, g, b)
        ctx.arc(fx * ICON_SIZE, fy * ICON_SIZE, radius, 0, 2 * math.pi)
        ctx.fill()
    return surface


def _text_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    # Glyph antialiasing is controlled by font options, not
    # ctx.set_antialias() - without this, Cairo's toy text API inherits
    # the system's subpixel/LCD hinting and leaves a faint RGB fringe
    # along glyph edges at this size.
    font_options = ctx.get_font_options()
    font_options.set_antialias(cairo.ANTIALIAS_GRAY)
    ctx.set_font_options(font_options)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(ICON_SIZE * 0.75)
    extents = ctx.text_extents("A")
    ctx.move_to(
        ICON_SIZE / 2 - extents.width / 2 - extents.x_bearing,
        ICON_SIZE / 2 - extents.height / 2 - extents.y_bearing,
    )
    ctx.show_text("A")
    return surface


def _speech_bubble_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    bubble_bounds = Rect(_MARGIN, _MARGIN, ICON_SIZE - _MARGIN, ICON_SIZE * 0.6)
    shape = SpeechBubbleShape(
        bubble_bounds=bubble_bounds, target=(ICON_SIZE * 0.3, ICON_SIZE - _MARGIN), text="",
        style=_line_art_style(color),
    )
    render_speech_bubble(cairo.Context(surface), shape)
    return surface


def _step_label_icon(color: Color) -> cairo.ImageSurface:
    # Ignores ``color`` like Pixelize/Blur - a step label always
    # renders in its own fixed dark-red/white style (see
    # StepLabelShape's default in core/shapes.py), not the editor's
    # adjustable line/fill color, so the icon shouldn't pretend
    # otherwise.
    surface = _blank_surface()
    shape = StepLabelShape(Rect(_MARGIN, _MARGIN, ICON_SIZE - _MARGIN, ICON_SIZE - _MARGIN), number=1)
    render_step_label(cairo.Context(surface), shape)
    return surface


def _select_icon(color: Color) -> cairo.ImageSurface:
    """A classic mouse-pointer arrow, not the annotation Arrow tool's
    straight line-with-arrowhead (that one points *at* something in
    the image; this one represents "select/move" as a UI action, same
    idea as any OS pointer cursor)."""
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    points = [
        (_MARGIN + 1, _MARGIN),
        (_MARGIN + 1, ICON_SIZE - _MARGIN),
        (_MARGIN + 7, ICON_SIZE - _MARGIN - 6),
        (_MARGIN + 11, ICON_SIZE - _MARGIN + 1),
        (_MARGIN + 14, ICON_SIZE - _MARGIN - 2),
        (_MARGIN + 10, ICON_SIZE - _MARGIN - 8),
        (ICON_SIZE - _MARGIN, ICON_SIZE - _MARGIN - 8),
    ]
    ctx.move_to(*points[0])
    for point in points[1:]:
        ctx.line_to(*point)
    ctx.close_path()
    ctx.fill_preserve()
    ctx.set_source_rgba(0, 0, 0, 0.35)
    ctx.set_line_width(1)
    ctx.stroke()
    return surface


def _emoji_icon(color: Color) -> cairo.ImageSurface:
    # A hand-drawn smiley (circle + eyes + smile curve) rather than
    # relying on an emoji font glyph - Cairo's toy text API has no
    # reliable color-emoji-font support, and a hand-drawn glyph stays
    # consistent with every other line-art icon here (single color,
    # follows the theme) instead of looking like a mismatched color
    # sticker next to monochrome tool icons.
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    radius = ICON_SIZE / 2 - _MARGIN
    ctx.set_line_width(1.5)
    ctx.arc(cx, cy, radius, 0, 2 * math.pi)
    ctx.stroke()
    eye_r = 1.3
    for ex in (cx - radius * 0.45, cx + radius * 0.45):
        ctx.arc(ex, cy - radius * 0.25, eye_r, 0, 2 * math.pi)
        ctx.fill()
    ctx.arc(cx, cy + radius * 0.05, radius * 0.55, 0.15 * math.pi, 0.85 * math.pi)
    ctx.stroke()
    return surface


_TOOL_ICON_BUILDERS = {
    Tool.SELECT: _select_icon,
    Tool.RECTANGLE: _rectangle_icon,
    Tool.ELLIPSE: _ellipse_icon,
    Tool.LINE: _line_icon,
    Tool.ARROW: _arrow_icon,
    Tool.FREEHAND: _freehand_icon,
    Tool.PIXELIZE: _pixelize_icon,
    Tool.BLUR: _blur_icon,
    Tool.SOLID_FILL: _solid_fill_icon,
    Tool.SCRAMBLE: _scramble_icon,
    Tool.TEXT: _text_icon,
    Tool.SPEECH_BUBBLE: _speech_bubble_icon,
    Tool.STEP_LABEL: _step_label_icon,
    Tool.EMOJI: _emoji_icon,
}


def tool_icon_surface(tool: Tool, color: Color = _DEFAULT_COLOR) -> cairo.ImageSurface:
    return _TOOL_ICON_BUILDERS[tool](color)


def tool_icon_image(tool: Tool, color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    surface = tool_icon_surface(tool, color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)
