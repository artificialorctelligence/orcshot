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

from orcshot.core.geometry import Rect
from orcshot.core.shapes import (
    ArrowShape, Color, EllipseShape, FreehandShape, LineShape, RectangleShape, ShapeStyle,
    SpeechBubbleShape,
)
from orcshot.core.tools import Tool
from orcshot.ui.render import (
    render_arrow, render_ellipse, render_freehand, render_line, render_rectangle,
    render_speech_bubble,
)

ICON_SIZE = 24
_MARGIN = 4
_DEFAULT_COLOR: Color = (60, 60, 60, 255)


def _blank_surface() -> cairo.ImageSurface:
    return cairo.ImageSurface(cairo.FORMAT_ARGB32, ICON_SIZE, ICON_SIZE)


def _line_art_style(color: Color) -> ShapeStyle:
    return ShapeStyle(line_thickness=2, line_color=color, fill_color=(0, 0, 0, 0), shadow=False)


def _rounded_rect_path(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


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


def _text_highlight_icon(color: Color) -> cairo.ImageSurface:
    # Ignores color like every other mode icon here - a fixed yellow
    # highlighter swatch behind a dark "T", standing in for Text
    # Highlight's own default fill_color (yellow) regardless of the
    # current theme color, the same reasoning _solid_fill_icon gives
    # for always drawing in a fixed tone.
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(1.0, 0.9, 0.1)
    ctx.rectangle(_MARGIN, ICON_SIZE * 0.4, ICON_SIZE - 2 * _MARGIN, ICON_SIZE * 0.35)
    ctx.fill()
    ctx.set_source_rgb(0.15, 0.15, 0.15)
    ctx.set_line_width(2)
    ctx.move_to(ICON_SIZE * 0.3, ICON_SIZE * 0.3)
    ctx.line_to(ICON_SIZE * 0.7, ICON_SIZE * 0.3)
    ctx.move_to(ICON_SIZE / 2, ICON_SIZE * 0.3)
    ctx.line_to(ICON_SIZE / 2, ICON_SIZE * 0.75)
    ctx.stroke()
    return surface


def _area_highlight_icon(color: Color) -> cairo.ImageSurface:
    # A bright center with darkened corners - the "spotlight" look
    # Area Highlight actually produces (dims/blurs everywhere except
    # its own bounds), not a literal render of the filter itself.
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.15, 0.15, 0.15)
    ctx.rectangle(0, 0, ICON_SIZE, ICON_SIZE)
    ctx.fill()
    ctx.set_source_rgb(0.95, 0.9, 0.6)
    ctx.rectangle(ICON_SIZE * 0.3, ICON_SIZE * 0.3, ICON_SIZE * 0.4, ICON_SIZE * 0.4)
    ctx.fill()
    return surface


def _grayscale_highlight_icon(color: Color) -> cairo.ImageSurface:
    # Half color, half gray - a literal split demonstrating what the
    # filter does, distinct from Area Highlight's spotlight look even
    # though both are "invert" (outside-the-rect) modes.
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.35, 0.55, 0.75)
    ctx.rectangle(_MARGIN, _MARGIN, (ICON_SIZE - 2 * _MARGIN) / 2, ICON_SIZE - 2 * _MARGIN)
    ctx.fill()
    ctx.set_source_rgb(0.55, 0.55, 0.55)
    ctx.rectangle(ICON_SIZE / 2, _MARGIN, (ICON_SIZE - 2 * _MARGIN) / 2, ICON_SIZE - 2 * _MARGIN)
    ctx.fill()
    return surface


def _magnify_highlight_icon(color: Color) -> cairo.ImageSurface:
    # A literal magnifying glass - clearer than trying to depict the
    # zoomed-crop effect itself at icon scale.
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.25, 0.45, 0.7)
    cx, cy, r = ICON_SIZE * 0.42, ICON_SIZE * 0.42, ICON_SIZE * 0.28
    ctx.set_line_width(2.5)
    ctx.arc(cx, cy, r, 0, 2 * math.pi)
    ctx.stroke()
    handle_start = (cx + r * 0.7, cy + r * 0.7)
    handle_end = (ICON_SIZE - _MARGIN, ICON_SIZE - _MARGIN)
    ctx.move_to(*handle_start)
    ctx.line_to(*handle_end)
    ctx.stroke()
    return surface


def _highlight_icon(color: Color) -> cairo.ImageSurface:
    """A highlighter-marker glyph - what the single, Windows-style
    unified Highlight toolbar button actually shows (mirrors
    _obfuscate_icon's own approach exactly, see its docstring):
    represents the whole feature, not any one of its four modes (Text
    Highlight/Area Highlight/Grayscale/Magnification above), none of
    which are otherwise ever shown anywhere - the mode dropdown is
    text-only, same as Obfuscate's.

    A slanted marker pen (body + chiseled tip) over a short
    highlighted stroke - the familiar "highlighter" glyph most
    desktop/office apps use, hand-drawn in Cairo like every icon in
    this file, monochrome and theme-colored like every other tool
    icon rather than the fixed-color mode icons above.
    """
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)

    ctx.save()
    ctx.translate(ICON_SIZE * 0.62, ICON_SIZE * 0.42)
    ctx.rotate(math.radians(45))
    _rounded_rect_path(ctx, -3, -9, 6, 12, 1.5)
    ctx.fill()
    ctx.move_to(-3, 3)
    ctx.line_to(3, 3)
    ctx.line_to(0, 8)
    ctx.close_path()
    ctx.fill()
    ctx.restore()

    ctx.rectangle(4, ICON_SIZE - 6, ICON_SIZE - 8, 3)
    ctx.fill()
    return surface


def _obfuscate_icon(color: Color) -> cairo.ImageSurface:
    """A fedora-and-sunglasses "incognito" glyph - what the single,
    Windows-style unified Obfuscate toolbar button actually shows
    (task #54's _build_obfuscate_control calls obfuscate_icon_image
    below, not tool_icon_image(Tool.PIXELIZE, ...) like it used to).
    Represents the whole redaction feature, not any one mode - none of
    Pixelize/Blur/SolidFill/Scramble's own icons above are otherwise
    ever shown anywhere (the mode dropdown is text-only), so there's
    no "faithful to a specific mode" icon to lose by replacing it.

    Proportions loosely follow the familiar wide-brim/narrow-crown/
    two-lenses-and-a-bridge silhouette (Chrome's incognito icon, Font
    Awesome's "user-secret") - hand-drawn in Cairo like every icon in
    this file, not a downloaded/bundled asset (see this module's own
    docstring), and monochrome in the given ``color`` like every
    other tool icon, unlike the fixed-color mode icons above.
    """
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)

    # Crown: a narrower rounded rect sitting on top of the brim.
    _rounded_rect_path(ctx, 8, 5, 8, 6, 1.5)
    ctx.fill()

    # Brim: a wide, flattened ellipse spanning nearly the full width -
    # the standard "circle built from a scaled arc" Cairo idiom: the
    # arc is baked into device-space path coordinates at the transform
    # in effect when it's added, so restoring the CTM before fill()
    # doesn't undo the scale.
    ctx.save()
    ctx.translate(ICON_SIZE / 2, 11.5)
    ctx.scale(10, 2.2)
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()
    ctx.fill()

    # Sunglasses: two lenses plus a connecting bridge, below the brim.
    _rounded_rect_path(ctx, 4.5, 14, 6, 5, 1.5)
    ctx.fill()
    _rounded_rect_path(ctx, 13.5, 14, 6, 5, 1.5)
    ctx.fill()
    ctx.set_line_width(1.5)
    ctx.move_to(10.5, 16)
    ctx.line_to(13.5, 16)
    ctx.stroke()

    return surface


def _effects_icon(color: Color) -> cairo.ImageSurface:
    """A magic-wand-with-sparkle glyph - what the toolbar's Effects
    dropdown (task #89) shows. Real Windows' own toolStripSplitButton1
    (LanguageKey="editor_effects") uses a bundled wand-hat.png (Fugue
    icon set) for this same button; matched in spirit here, hand-drawn
    in Cairo like every icon in this file rather than a downloaded/
    bundled asset (see this module's own docstring). Represents the
    whole grouped dropdown (Border/Drop Shadow/Torn Edge/Grayscale/
    Invert/Remove Transparency), not any one specific effect - the
    same "one icon for the whole control" approach as
    _obfuscate_icon/_highlight_icon above.
    """
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)

    # Wand shaft: a thin rounded rect running diagonally from the
    # bottom-left toward the sparkle at the upper-right, the same
    # rotate-then-draw-centered idiom _highlight_icon uses for its
    # marker pen.
    ctx.save()
    ctx.translate(ICON_SIZE * 0.38, ICON_SIZE * 0.66)
    ctx.rotate(math.radians(-45))
    _rounded_rect_path(ctx, -2, -8, 4, 13, 2)
    ctx.fill()
    ctx.restore()

    # Sparkle: a 4-point star at the wand's tip, built from two long
    # thin diamonds crossed at 90 degrees around the same center.
    tip_x, tip_y = ICON_SIZE * 0.68, ICON_SIZE * 0.3

    def _diamond(length: float, width: float) -> None:
        ctx.move_to(tip_x, tip_y - length)
        ctx.line_to(tip_x + width, tip_y)
        ctx.line_to(tip_x, tip_y + length)
        ctx.line_to(tip_x - width, tip_y)
        ctx.close_path()
        ctx.fill()

    _diamond(6, 1.6)
    ctx.save()
    ctx.translate(tip_x, tip_y)
    ctx.rotate(math.radians(90))
    ctx.translate(-tip_x, -tip_y)
    _diamond(6, 1.6)
    ctx.restore()

    # Two smaller flourish dots, the familiar "magic effects" glyph.
    ctx.arc(ICON_SIZE * 0.85, ICON_SIZE * 0.52, 1.3, 0, 2 * math.pi)
    ctx.fill()
    ctx.arc(ICON_SIZE * 0.56, ICON_SIZE * 0.1, 1.0, 0, 2 * math.pi)
    ctx.fill()

    return surface


def _rotate_icon(color: Color, clockwise: bool) -> cairo.ImageSurface:
    """A circular arrow - what task #90's Rotate CW/CCW toolbar buttons
    show (Rotate Clockwise/Counterclockwise moved here from the Image
    menu, matching Windows' own separate rotateCwToolstripButton/
    rotateCcwToolstripButton, ImageEditorForm.Designer.cs:565-581).

    The base arc/arrowhead below is built once; clockwise is drawn by
    mirroring it horizontally rather than re-deriving separate trig for
    each direction - a left-right flip inverts rotational handedness,
    so this is exact, not just visually close. (Confirmed which way is
    which by rendering both and looking, not by eye-balling the trig -
    the base, unflipped construction reads as counterclockwise.)
    """
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2.2)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)

    if clockwise:
        ctx.translate(ICON_SIZE, 0)
        ctx.scale(-1, 1)

    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    radius = ICON_SIZE / 2 - 5.5
    start_angle = math.radians(-70)
    end_angle = math.radians(210)
    ctx.arc(cx, cy, radius, start_angle, end_angle)
    ctx.stroke()

    # Arrowhead at the arc's leading end, tangent to the direction of
    # travel (increasing angle here reads as clockwise on screen,
    # since Cairo/GTK's y axis grows downward).
    tip_x = cx + radius * math.cos(end_angle)
    tip_y = cy + radius * math.sin(end_angle)
    tangent = end_angle + math.pi / 2
    back = tangent + math.pi
    head_len = 5.5
    spread = math.radians(25)
    for sign in (-1, 1):
        wing = back + sign * spread
        ctx.move_to(tip_x, tip_y)
        ctx.line_to(tip_x + head_len * math.cos(wing), tip_y + head_len * math.sin(wing))
    ctx.stroke()

    return surface


def _resize_icon(color: Color) -> cairo.ImageSurface:
    """A frame with a diagonal double-headed arrow through its corner -
    the familiar "drag to resize" handle glyph. What task #90's Resize
    toolbar button shows (moved here from the Image menu, matching
    Windows' own separate btnResize, LanguageKey="editor_resize").
    """
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)

    ctx.set_line_width(1.8)
    _rounded_rect_path(ctx, _MARGIN, _MARGIN, ICON_SIZE - 2 * _MARGIN, ICON_SIZE - 2 * _MARGIN, 2)
    ctx.stroke()

    ctx.set_line_width(2.0)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    x1, y1 = ICON_SIZE * 0.34, ICON_SIZE * 0.34
    x2, y2 = ICON_SIZE * 0.82, ICON_SIZE * 0.82
    ctx.move_to(x1, y1)
    ctx.line_to(x2, y2)
    ctx.stroke()

    angle = math.atan2(y2 - y1, x2 - x1)
    head_len = 4.5
    spread = math.radians(28)
    for tip_x, tip_y, direction in ((x1, y1, angle + math.pi), (x2, y2, angle)):
        back = direction + math.pi
        for sign in (-1, 1):
            wing = back + sign * spread
            ctx.move_to(tip_x, tip_y)
            ctx.line_to(tip_x + head_len * math.cos(wing), tip_y + head_len * math.sin(wing))
    ctx.stroke()

    return surface


def _crop_default_icon(color: Color) -> cairo.ImageSurface:
    # Per-mode icon, never shown anywhere (same reasoning as the four
    # Highlight/Obfuscate mode icons above - the single unified Crop
    # toolbar button always shows _crop_icon instead, see its own
    # docstring) - kept only so every Tool enum member still has one,
    # matching this module's existing tool_icon_surface contract.
    return _crop_icon(color)


def _crop_vertical_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255 * 0.35)
    ctx.rectangle(ICON_SIZE * 0.4, _MARGIN, ICON_SIZE * 0.2, ICON_SIZE - 2 * _MARGIN)
    ctx.fill()
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2)
    ctx.move_to(ICON_SIZE * 0.4, _MARGIN)
    ctx.line_to(ICON_SIZE * 0.4, ICON_SIZE - _MARGIN)
    ctx.move_to(ICON_SIZE * 0.6, _MARGIN)
    ctx.line_to(ICON_SIZE * 0.6, ICON_SIZE - _MARGIN)
    ctx.stroke()
    return surface


def _crop_horizontal_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255 * 0.35)
    ctx.rectangle(_MARGIN, ICON_SIZE * 0.4, ICON_SIZE - 2 * _MARGIN, ICON_SIZE * 0.2)
    ctx.fill()
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2)
    ctx.move_to(_MARGIN, ICON_SIZE * 0.4)
    ctx.line_to(ICON_SIZE - _MARGIN, ICON_SIZE * 0.4)
    ctx.move_to(_MARGIN, ICON_SIZE * 0.6)
    ctx.line_to(ICON_SIZE - _MARGIN, ICON_SIZE * 0.6)
    ctx.stroke()
    return surface


def _crop_icon(color: Color) -> cairo.ImageSurface:
    """Two overlapping L-shaped corner brackets - the crop-tool glyph
    used across most image editors (Photoshop/GIMP/etc). What task
    #91's Crop toolbar button shows - Windows' own icon for this is a
    bundled ruler-crop.png (Fugue icon set); matched in spirit here,
    hand-drawn in Cairo like every icon in this file rather than a
    downloaded/bundled asset (see this module's own docstring).
    """
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2.2)
    ctx.set_line_cap(cairo.LINE_CAP_SQUARE)

    # Corners near the icon's own edges with a short arm, leaving a
    # clear gap in the middle - reads as "framing a region" rather
    # than two overlapping squares (a first attempt with a larger
    # inset/arm pair overlapped enough to look like nested squares
    # instead, caught by looking at a rendered zoom, not guessed).
    inset = 3
    arm = 7

    # Top-left bracket.
    ctx.move_to(inset, inset + arm)
    ctx.line_to(inset, inset)
    ctx.line_to(inset + arm, inset)
    ctx.stroke()

    # Bottom-right bracket.
    ctx.move_to(ICON_SIZE - inset, ICON_SIZE - inset - arm)
    ctx.line_to(ICON_SIZE - inset, ICON_SIZE - inset)
    ctx.line_to(ICON_SIZE - inset - arm, ICON_SIZE - inset)
    ctx.stroke()

    return surface

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
    """An outlined circle - reusing render_ellipse exactly like
    _ellipse_icon does, so it matches the Ellipse tool's own icon
    style - with a "1" centered inside, both in the given ``color``.
    Used to reuse render_step_label on a real StepLabelShape instead,
    which looked right as an on-canvas element (its own fixed dark-
    red/white style, see StepLabelShape's default in core/shapes.py)
    but wrong as a toolbar icon: it was the one hardcoded exception
    among every icon in this file that ignored the theme color.
    """
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    circle = EllipseShape(Rect(_MARGIN, _MARGIN, ICON_SIZE - _MARGIN, ICON_SIZE - _MARGIN), _line_art_style(color))
    render_ellipse(ctx, circle)

    font_options = ctx.get_font_options()
    font_options.set_antialias(cairo.ANTIALIAS_GRAY)
    ctx.set_font_options(font_options)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(ICON_SIZE * 0.5)
    extents = ctx.text_extents("1")
    # Horizontally centered on x_advance (the glyph's full logical
    # width, including the font's own side bearings), not pure ink-
    # bbox width like _text_icon's "A" - "1" is asymmetric (a thin
    # top-left flag against a full-height stem, confirmed by rendering
    # and inspecting the actual ink column-by-column), so bbox-
    # centering its ink leaves the visually-dominant stem sitting
    # right of center. The font's own side bearings already balance
    # that asymmetry for normal text flow, and reusing them here reads
    # as properly centered instead. Vertical centering stays ink-bbox
    # based (height/y_bearing) - "1" doesn't have the same asymmetry
    # top-to-bottom.
    ctx.move_to(
        ICON_SIZE / 2 - extents.x_advance / 2,
        ICON_SIZE / 2 - extents.height / 2 - extents.y_bearing,
    )
    ctx.show_text("1")
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
    Tool.HIGHLIGHT_TEXT: _text_highlight_icon,
    Tool.HIGHLIGHT_AREA: _area_highlight_icon,
    Tool.HIGHLIGHT_GRAYSCALE: _grayscale_highlight_icon,
    Tool.HIGHLIGHT_MAGNIFY: _magnify_highlight_icon,
    Tool.TEXT: _text_icon,
    Tool.SPEECH_BUBBLE: _speech_bubble_icon,
    Tool.STEP_LABEL: _step_label_icon,
    Tool.EMOJI: _emoji_icon,
    Tool.CROP_DEFAULT: _crop_default_icon,
    Tool.CROP_VERTICAL: _crop_vertical_icon,
    Tool.CROP_HORIZONTAL: _crop_horizontal_icon,
}


def tool_icon_surface(tool: Tool, color: Color = _DEFAULT_COLOR) -> cairo.ImageSurface:
    return _TOOL_ICON_BUILDERS[tool](color)


def tool_icon_image(tool: Tool, color: Color = _DEFAULT_COLOR, size: int = ICON_SIZE) -> Gtk.Image:
    """``size`` (task #95's Preferences>General "Icon size" setting,
    settings.get_icon_size) rescales the rendered pixbuf rather than
    redrawing at a different resolution - every _TOOL_ICON_BUILDERS
    function is written against the fixed ICON_SIZE module constant
    (dozens of hardcoded coordinates), and bitmap-scaling a vector-
    drawn icon after the fact is both far less code and how Windows'
    own IconSize setting works too (it scales bitmap resources, not
    a redraw). BILINEAR, not NEAREST - unlike orcshot.png's deliberately
    blocky dot-matrix logo, these are smooth vector line-art icons,
    where nearest-neighbor scaling would look chunky/aliased instead
    of crisp.
    """
    surface = tool_icon_surface(tool, color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    if size != ICON_SIZE:
        pixbuf = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
    return Gtk.Image.new_from_pixbuf(pixbuf)


def obfuscate_icon_image(color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    """Not keyed by Tool like tool_icon_image above - _obfuscate_icon
    represents the single unified Obfuscate button (task #54), not any
    one of the four selectable modes (Pixelize/Blur/SolidFill/Scramble
    all still have their own _TOOL_ICON_BUILDERS entries, just never
    shown anywhere - see _obfuscate_icon's own docstring).
    """
    surface = _obfuscate_icon(color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


def highlight_icon_image(color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    """Not keyed by Tool like tool_icon_image above - mirrors
    obfuscate_icon_image exactly: _highlight_icon represents the
    single unified Highlight button (task #88), not any one of the
    four selectable modes (all still have their own _TOOL_ICON_
    BUILDERS entries, just never shown anywhere - see _highlight_
    icon's own docstring).
    """
    surface = _highlight_icon(color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


def effects_icon_image(color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    """Not keyed by Tool like tool_icon_image above - mirrors
    obfuscate_icon_image/highlight_icon_image exactly: _effects_icon
    represents the whole Effects dropdown (task #89), which isn't a
    drawing tool at all (no Tool enum member - it's a one-shot action
    menu, like Windows' own toolStripSplitButton1).
    """
    surface = _effects_icon(color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


def rotate_cw_icon_image(color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    surface = _rotate_icon(color, clockwise=True)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


def rotate_ccw_icon_image(color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    surface = _rotate_icon(color, clockwise=False)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


def resize_icon_image(color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    surface = _resize_icon(color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


def crop_icon_image(color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    """Not keyed by Tool like tool_icon_image above - mirrors
    obfuscate_icon_image/highlight_icon_image: _crop_icon represents
    the single unified Crop button (task #91), not any one of its
    three selectable modes.
    """
    surface = _crop_icon(color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


# --- destination-picker icons (task #96) ---------------------------------

def _clipboard_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(1.8)
    _rounded_rect_path(ctx, _MARGIN + 1, _MARGIN + 3, ICON_SIZE - 2 * _MARGIN - 2, ICON_SIZE - 2 * _MARGIN - 4, 2)
    ctx.stroke()
    _rounded_rect_path(ctx, ICON_SIZE / 2 - 4, _MARGIN, 8, 5, 1.5)
    ctx.stroke()
    return surface


def _save_icon(color: Color) -> cairo.ImageSurface:
    """Floppy disk - also used for "Save As...", same as most apps
    don't bother with a second icon for it."""
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(1.8)
    _rounded_rect_path(ctx, _MARGIN, _MARGIN, ICON_SIZE - 2 * _MARGIN, ICON_SIZE - 2 * _MARGIN, 2)
    ctx.stroke()
    ctx.rectangle(ICON_SIZE * 0.55, _MARGIN, ICON_SIZE * 0.2, ICON_SIZE * 0.22)
    ctx.fill()
    ctx.rectangle(ICON_SIZE * 0.3, ICON_SIZE * 0.55, ICON_SIZE * 0.4, ICON_SIZE * 0.3)
    ctx.stroke()
    return surface


def _edit_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    x1, y1 = ICON_SIZE - _MARGIN, _MARGIN
    x2, y2 = _MARGIN + 3, ICON_SIZE - _MARGIN - 3
    ctx.move_to(x1, y1)
    ctx.line_to(x2, y2)
    ctx.stroke()
    ctx.move_to(x2, y2)
    ctx.line_to(x2 + 5, y2)
    ctx.line_to(x2, y2 - 5)
    ctx.close_path()
    ctx.fill()
    ctx.move_to(_MARGIN, ICON_SIZE - _MARGIN)
    ctx.line_to(ICON_SIZE * 0.45, ICON_SIZE - _MARGIN)
    ctx.stroke()
    return surface


def _print_icon(color: Color) -> cairo.ImageSurface:
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(1.8)
    ctx.rectangle(_MARGIN, ICON_SIZE * 0.4, ICON_SIZE - 2 * _MARGIN, ICON_SIZE * 0.32)
    ctx.stroke()
    ctx.rectangle(ICON_SIZE * 0.3, _MARGIN, ICON_SIZE * 0.4, ICON_SIZE * 0.3)
    ctx.stroke()
    ctx.rectangle(ICON_SIZE * 0.3, ICON_SIZE * 0.72, ICON_SIZE * 0.4, ICON_SIZE * 0.18)
    ctx.stroke()
    return surface


def _external_command_icon(color: Color) -> cairo.ImageSurface:
    """Generic icon for any configured ExternalCommand destination
    (task #110) - a terminal-prompt glyph, since these can run
    anything, not one specific action to depict."""
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(1.8)
    _rounded_rect_path(ctx, _MARGIN, _MARGIN, ICON_SIZE - 2 * _MARGIN, ICON_SIZE - 2 * _MARGIN, 2)
    ctx.stroke()
    ctx.set_line_width(2)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.move_to(ICON_SIZE * 0.3, ICON_SIZE * 0.35)
    ctx.line_to(ICON_SIZE * 0.46, ICON_SIZE * 0.5)
    ctx.line_to(ICON_SIZE * 0.3, ICON_SIZE * 0.65)
    ctx.stroke()
    ctx.move_to(ICON_SIZE * 0.52, ICON_SIZE * 0.68)
    ctx.line_to(ICON_SIZE * 0.72, ICON_SIZE * 0.68)
    ctx.stroke()
    return surface


_DESTINATION_ICON_BUILDERS = {
    "clipboard": _clipboard_icon,
    "save": _save_icon,
    "save_as": _save_icon,
    "edit": _edit_icon,
    "print": _print_icon,
}


def _capture_region_icon(color: Color) -> cairo.ImageSurface:
    """Dashed rectangle - the "marching ants" region-select metaphor.
    Dashed (not solid) deliberately matches _capture_window_picker_icon
    below - both represent an interactive "you choose" action, versus
    the solid shapes used for "the current/remembered one" (Active
    Window, Repeat Last Region)."""
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2)
    ctx.set_dash([3, 2])
    ctx.rectangle(_MARGIN, _MARGIN, ICON_SIZE - 2 * _MARGIN, ICON_SIZE - 2 * _MARGIN)
    ctx.stroke()
    return surface


def _capture_full_screen_icon(color: Color) -> cairo.ImageSurface:
    """A monitor: screen bezel plus a small stand - the standard
    "display" glyph shape."""
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    screen_bottom = ICON_SIZE * 0.66
    _rounded_rect_path(ctx, _MARGIN, _MARGIN, ICON_SIZE - 2 * _MARGIN, screen_bottom - _MARGIN, 2)
    ctx.stroke()
    ctx.move_to(ICON_SIZE / 2, screen_bottom)
    ctx.line_to(ICON_SIZE / 2, ICON_SIZE - _MARGIN)
    ctx.stroke()
    ctx.move_to(ICON_SIZE * 0.3, ICON_SIZE - _MARGIN)
    ctx.line_to(ICON_SIZE * 0.7, ICON_SIZE - _MARGIN)
    ctx.stroke()
    return surface


def _window_frame_icon(color: Color, *, dashed: bool) -> cairo.ImageSurface:
    """Shared by Active Window (solid) and Window Picker (dashed) -
    an application-window frame with a title-bar strip near the top."""
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2)
    if dashed:
        ctx.set_dash([3, 2])
    _rounded_rect_path(ctx, _MARGIN, _MARGIN, ICON_SIZE - 2 * _MARGIN, ICON_SIZE - 2 * _MARGIN, 2)
    ctx.stroke()
    ctx.set_dash([])
    title_bar_bottom = _MARGIN + (ICON_SIZE - 2 * _MARGIN) * 0.28
    ctx.move_to(_MARGIN, title_bar_bottom)
    ctx.line_to(ICON_SIZE - _MARGIN, title_bar_bottom)
    ctx.stroke()
    return surface


def _capture_active_window_icon(color: Color) -> cairo.ImageSurface:
    return _window_frame_icon(color, dashed=False)


def _capture_window_picker_icon(color: Color) -> cairo.ImageSurface:
    return _window_frame_icon(color, dashed=True)


def _capture_repeat_icon(color: Color) -> cairo.ImageSurface:
    """A solid rectangle (a remembered, concrete region - not an
    interactive selection, hence solid rather than dashed like
    _capture_region_icon) plus a small refresh/repeat arrow."""
    surface = _blank_surface()
    ctx = cairo.Context(surface)
    r, g, b, a = color
    ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
    ctx.set_line_width(2)
    inset = ICON_SIZE * 0.14
    ctx.rectangle(_MARGIN, _MARGIN + inset, ICON_SIZE - 2 * _MARGIN - inset, ICON_SIZE - 2 * _MARGIN - inset)
    ctx.stroke()
    cx, cy, radius = ICON_SIZE - _MARGIN - inset * 0.5, _MARGIN + inset * 0.5, inset * 1.15
    ctx.set_line_width(1.6)
    start, end = math.radians(20), math.radians(310)
    ctx.arc(cx, cy, radius, start, end)
    ctx.stroke()
    head_x, head_y = cx + radius * math.cos(end), cy + radius * math.sin(end)
    ctx.move_to(head_x, head_y)
    ctx.line_to(head_x - radius * 0.7, head_y)
    ctx.move_to(head_x, head_y)
    ctx.line_to(head_x, head_y + radius * 0.7)
    ctx.stroke()
    return surface


_CAPTURE_MODE_ICON_BUILDERS = {
    "region": _capture_region_icon,
    "full_screen": _capture_full_screen_icon,
    "active_window": _capture_active_window_icon,
    "window_picker": _capture_window_picker_icon,
    "repeat_region": _capture_repeat_icon,
}


def capture_mode_icon_image(mode: str, color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    """Icon for a tray-menu capture-mode item (task #137) - one of
    "region"/"full_screen"/"active_window"/"window_picker"/
    "repeat_region". This same geometry is independently reimplemented
    in JS/Cairo for orcshot-clipboard@orcshot.org's own Shell-native
    tray panel button (task #137 follow-up, see that extension's own
    _TRAY_ICON_DRAWERS) rather than shared with this function - GJS
    can't import this module, and drawing live (colored from
    St.ThemeNode.get_foreground_color() at paint time, the same value
    the row's own label text uses) is what makes that button's icons
    correctly legible under any theme, not just this app's own GTK
    windows. Keep the two geometries in sync by hand if either changes -
    same reasoning as [[feedback-shape-serialization-sync]] for the
    .orcshot/.greenshot export pair.
    """
    surface = _CAPTURE_MODE_ICON_BUILDERS[mode](color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)


def destination_icon_image(destination_id: str, color: Color = _DEFAULT_COLOR) -> Gtk.Image:
    """Icon for a destination-picker menu item (task #96) - falls back
    to the generic command glyph for dynamically-configured
    ExternalCommand destinations (ids like "external:My Command"),
    which have no fixed action to depict.
    """
    builder = _DESTINATION_ICON_BUILDERS.get(destination_id, _external_command_icon)
    surface = builder(color)
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())
    return Gtk.Image.new_from_pixbuf(pixbuf)
