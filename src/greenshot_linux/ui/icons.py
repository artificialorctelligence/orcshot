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
from greenshot_linux.core.shapes import ArrowShape, Color, EllipseShape, FreehandShape, LineShape, RectangleShape, ShapeStyle
from greenshot_linux.core.tools import Tool
from greenshot_linux.ui.render import render_arrow, render_ellipse, render_freehand, render_line, render_rectangle

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


_TOOL_ICON_BUILDERS = {
    Tool.RECTANGLE: _rectangle_icon,
    Tool.ELLIPSE: _ellipse_icon,
    Tool.LINE: _line_icon,
    Tool.ARROW: _arrow_icon,
    Tool.FREEHAND: _freehand_icon,
    Tool.PIXELIZE: _pixelize_icon,
    Tool.BLUR: _blur_icon,
    Tool.TEXT: _text_icon,
}


def tool_icon_surface(tool: Tool, color: Color = _DEFAULT_COLOR) -> cairo.ImageSurface:
    return _TOOL_ICON_BUILDERS[tool](color)


def tool_icon_image(tool: Tool, color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    surface = tool_icon_surface(tool, color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)
