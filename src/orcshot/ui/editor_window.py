"""The editor window: shows a captured image with the annotation Layer
drawn on top, and wires mouse interaction to create/move/resize shapes
plus Ctrl+Z/Ctrl+Y to undo/redo through UndoRedoStack.

This module is deliberately not unit tested the way core/ is — it's
GTK glue code driving a live event loop and an on-screen window, which
has no meaningful headless test. Verified instead by actually running
it and inspecting a real screenshot, the same way "does the X11 capture
backend work" was verified against real hardware earlier in this
project rather than asserted from reading the API docs. The logic that
CAN be unit tested (which shape a drag produces, how a shape moves or
resizes) is factored out into core/tools.py and tested there.

Interaction model: clicking on empty space starts a drag-to-create
gesture in the current tool, selected either via the toolbar along the
top or number keys 1-0 (Rectangle, Ellipse, Line, Arrow, Freehand,
Pixelize, Blur, Text, Speech Bubble, Step Label) - both stay in sync,
each updates the other.
Clicking on an existing shape selects it (drawing small square handles
at its corners/edges, or its two endpoints for Line/Arrow) and starts
dragging it; clicking one of those handles resizes/reshapes instead.
Selection persists after a click (not just for the duration of a drag)
so the handles stay visible and grabbable on a later, separate click.
The toolbar also has Undo/Redo buttons alongside Ctrl+Z/Ctrl+Y, and
Copy/Save/Print buttons alongside Ctrl+C/Ctrl+S/Ctrl+P - all three
composite the base image with the current Layer (ui/composite.py)
into one flat image, matching exactly what's on screen, then hand it
to a ClipboardBackend, ui/file_export.py, or a Gtk.PrintOperation (the
OS print dialog, no page-setup/multi-page/DPI options beyond fit-to-
page-centered - "basic print" per REQUIREMENTS.md). Icon-only buttons
with tooltips (Gtk.ToolbarStyle.ICONS), paint/Photoshop-style rather
than text labels: the drawing tools use small hand-drawn Cairo icons
(ui/icons.py, reusing ui/render.py's actual renderers where one
exists, so an icon can never visually drift from what the tool draws
- no icon theme has standardized names for "rectangle annotation
tool"), the generic actions use standard freedesktop theme icon names
(edit-undo-symbolic etc., confirmed present via Gtk.IconTheme.has_icon
before relying on them) so they follow the system icon theme/dark-
light mode automatically, same as everything else in this app.

The Text tool drags out a box same as Rectangle, then enters an
editing mode backed by a real Gtk.TextView overlaid on the canvas via
Gtk.Overlay (matching Greenshot.Editor's own TextContainer.cs, which
overlays a native System.Windows.Forms.TextBox rather than drawing a
caret by hand) - positioned/sized/font-matched to the shape's box each
time editing starts, with its buffer's "changed" signal live-updating
the shape (and thus the normal Cairo-rendered preview underneath) on
every keystroke. Plain Enter commits, Shift+Enter inserts a newline
(native TextView behavior), Escape cancels, losing focus commits -
all mirroring textBox_KeyDown/TextBox_LostFocus. Being a real widget,
it gets a native blinking caret, text selection, and clipboard/undo
key bindings for free; while it's focused, keys other than Escape/
Enter go to it directly rather than this window's own shortcut
handler, so typing "z" doesn't trigger undo.

Double-clicking an *existing* TextShape re-enters editing mode on it
too (self._editing_original_shape tracks which case applies - None for
a brand-new shape, the pre-edit instance for a re-edit - since the
correct undo/cancel behavior differs: cancelling a fresh shape discards
it with nothing to undo, cancelling a re-edit reverts the text with
nothing to undo either, but *committing* a re-edit pushes
ElementChangeMemento/DeleteElementMemento instead of AddElementMemento,
since the shape already existed in committed history). GTK fires a
normal single-click press before a double-click's second press, so
that first press already runs the ordinary select-and-start-moving
branch below; the double-click branch explicitly cancels that
in-progress move. A related fix that came out of tracing through this:
a click that ends without any drag (dx=dy=0) no longer pushes a no-op
move ElementChangeMemento - it was cluttering undo history even for a
plain single click that just selects a shape.

A second row below the toolbar (line color, fill color, thickness,
shadow) edits self._active_style() - each tool has its own independent
"last used" style (self._tool_styles, seeded per-type from core/tools.
py's default_style_for_tool, faithfully porting EditorConfiguration
Helper's per-container-type LastUsedFieldValues cache rather than one
value shared across every tool), affecting shapes created *after* a
change; if a shape is currently selected when a control changes, it
gets restyled too (one ElementChangeMemento per control change) and
that update goes to *its own* type's memory (style_key_for_shape),
regardless of which tool happens to be active - except Obfuscate/Icon/
Cursor/Image/Svg, none of which have a style field to change. The
panel also syncs *from* a selection or a tool switch (_refresh_style_
panel) - clicking an existing shape, or switching tools, updates the
controls to show the relevant style. A separate "Obfuscate Amount"
spinner (blur radius / pixel size, self._default_obfuscate_amount)
works similarly but only applies to Pixelize/Blur shapes, and (unlike
the per-tool style memory) is still one value shared between both -
it's threaded through create_shape_from_drag's amount parameter
regardless of the current tool (ignored for every other tool), and
retroactively updates a selected ObfuscateShape the same way the style
controls retroactively restyle.

Every shape type with rendering support (see ui/render.py) has resize
handles too - core/tools.py's shape_handles/resize_shape special-case
SpeechBubbleShape (handles track bubble_bounds, not the wider .bounds
that includes the tail; the tail's target point is left alone so it
keeps pointing at the same spot) and FreehandShape (no bounds field to
swap, so its points are scaled proportionally from the old tight
bounding box into the new one). Shapes without a renderer still have
no handles - shape_handles returns {} for them.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import time
import webbrowser
from dataclasses import replace as dataclass_replace
from datetime import datetime
from fractions import Fraction
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("Rsvg", "2.0")

import numpy as np
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, Rsvg

from orcshot.autostart import install_autostart_entry, is_autostart_enabled, remove_autostart_entry
from orcshot.capture.clipboard import ClipboardBackend
from orcshot.core.crop import (
    autocrop_rect, crop_out_horizontal_strip, crop_out_vertical_strip, crop_to_rect,
)
from orcshot.core.drawing import Layer
from orcshot.core.filename_pattern import MODE_GREENSHOT, MODE_STRFTIME, resolve_filename_pattern
from orcshot.core.geometry import Rect
from orcshot.core.effects import (
    add_border_image,
    clear_image,
    drop_shadow_image,
    enlarge_canvas_image,
    grayscale_image,
    invert_image,
    remove_transparency_image,
    rotate_90_image,
)
from orcshot.core.history import (
    AddElementMemento,
    BackgroundChangeMemento,
    CompositeMemento,
    DeleteElementMemento,
    ElementChangeMemento,
    UndoRedoStack,
)
from orcshot.core.shapes import (
    HighlightMode, HighlightShape, ImageShape, ObfuscateMode, ObfuscateShape, ShapeStyle, SpeechBubbleShape,
    StepLabelShape, SvgShape, TextShape,
)
from orcshot.settings import (
    EXTERNAL_EDITOR_AUTO,
    OutputSettings,
    consume_filename_counter,
    get_capture_mouse_cursor,
    get_excluded_destinations,
    get_external_editor_preference,
    get_filename_counter,
    get_footer_pattern,
    get_icon_size,
    get_output_directory,
    get_output_settings,
    get_print_options,
    get_show_magnifier_while_selecting,
    get_suppress_save_dialog_at_close,
    get_update_check_interval_days,
    get_use_default_proxy,
    set_capture_mouse_cursor,
    set_excluded_destinations,
    set_external_editor_preference,
    set_filename_counter,
    set_footer_pattern,
    set_icon_size,
    set_output_directory,
    set_output_settings,
    set_print_options,
    set_show_magnifier_while_selecting,
    set_suppress_save_dialog_at_close,
    set_update_check_interval_days,
    set_use_default_proxy,
)
from orcshot.resources import LOGO_PATH
from orcshot.core.tools import (
    STYLE_FIELD_CROP_MODE,
    STYLE_FIELD_FILL_COLOR,
    STYLE_FIELD_HIGHLIGHT_BLUR_RADIUS,
    STYLE_FIELD_HIGHLIGHT_BRIGHTNESS,
    STYLE_FIELD_HIGHLIGHT_FILL_COLOR,
    STYLE_FIELD_HIGHLIGHT_MAGNIFICATION,
    STYLE_FIELD_HIGHLIGHT_MODE,
    STYLE_FIELD_LINE_COLOR,
    STYLE_FIELD_LINE_THICKNESS,
    STYLE_FIELD_OBFUSCATE_AMOUNT,
    STYLE_FIELD_OBFUSCATE_FILL_COLOR,
    STYLE_FIELD_OBFUSCATE_FILL_TEXT,
    STYLE_FIELD_OBFUSCATE_MODE,
    STYLE_FIELD_OBFUSCATE_TEXT_COLOR,
    STYLE_FIELD_SHADOW,
    Tool,
    create_freehand_shape,
    create_shape_from_drag,
    default_insert_bounds,
    default_style_for_tool,
    handle_at,
    resize_shape,
    rotate_shape_90,
    scale_shape,
    shape_handles,
    style_key_for_shape,
    translate_shape,
    visible_style_fields,
)
from orcshot.core.zoom import (
    ACTUAL_SIZE_ZOOM,
    ZOOM_LEVELS,
    best_fit_zoom,
    optimal_window_size,
    zoom_in,
    zoom_out,
    zoom_percent_label,
)
from orcshot.ui.cairo_convert import numpy_to_cairo_surface
from orcshot.ui.color_dialog import show_color_picker
from orcshot.ui.composite import composite_to_numpy
from orcshot.ui.effects import resize_image, torn_edge_image
from orcshot.ui.gdk_convert import pixbuf_to_numpy
from orcshot.ui.file_export import orcshot_cache_dir, save_image_to_file
from orcshot.ui.orcshot_file import (
    InvalidOrcshotFileError,
    load_objects_file,
    load_orcshot_file,
    save_objects_file,
    save_orcshot_file,
)
from orcshot.ui.icons import (
    crop_icon_image, effects_icon_image, highlight_icon_image, obfuscate_icon_image, resize_icon_image,
    rotate_ccw_icon_image, rotate_cw_icon_image, tool_icon_image,
)
from orcshot.ui.printing import print_image
from orcshot.ui.render import bubble_corner_radius, render_shape, vertical_text_offset
from orcshot.ui.text_obfuscation_dialog import DEFAULT_TEXT_OBFUSCATION_SETTINGS, do_obfuscate_text

# ZoomSetValue's 100ms Ctrl+wheel throttle (ImageEditorForm.cs:96,1185-1187)
_ZOOM_WHEEL_THROTTLE_SECONDS = 0.1
# ImageEditorForm's MinimumSize (ImageEditorForm.Designer.cs)
_MIN_WINDOW_WIDTH = 650
_MIN_WINDOW_HEIGHT = 530

_TOOL_KEYS = {
    # Real Windows letter-mnemonic scheme (task #92), replacing this
    # port's own earlier invented backtick+1-0 layout - confirmed
    # directly from ImageEditorFormKeyDown (ImageEditorForm.cs:1055-
    # 1107), the actual KeyDown handler, not the empty Designer.cs
    # ShortcutKeys properties an earlier pass in this project mistook
    # for "no shortcut exists" evidence. Escape *does* have a real
    # Windows precedent after all (case Keys.Escape: BtnCursorClick) -
    # correcting that same earlier claim. Both cased keyvals are bound
    # for every letter (GDK reports a distinct keyval per case, unlike
    # the numeric row) - not a strict replica of Windows' own
    # Modifiers.Equals(Keys.None) check, which would exclude Shift+
    # letter entirely, but consistent with how this file already
    # treats every Ctrl-combo shortcut below (e.g. Gdk.KEY_z/Gdk.KEY_Z
    # both trigger undo) rather than introducing a second, stricter
    # convention just for these.
    Gdk.KEY_Escape: Tool.SELECT,
    Gdk.KEY_r: Tool.RECTANGLE,
    Gdk.KEY_R: Tool.RECTANGLE,
    Gdk.KEY_e: Tool.ELLIPSE,
    Gdk.KEY_E: Tool.ELLIPSE,
    Gdk.KEY_l: Tool.LINE,
    Gdk.KEY_L: Tool.LINE,
    Gdk.KEY_f: Tool.FREEHAND,
    Gdk.KEY_F: Tool.FREEHAND,
    Gdk.KEY_a: Tool.ARROW,
    Gdk.KEY_A: Tool.ARROW,
    Gdk.KEY_t: Tool.TEXT,
    Gdk.KEY_T: Tool.TEXT,
    Gdk.KEY_s: Tool.SPEECH_BUBBLE,
    Gdk.KEY_S: Tool.SPEECH_BUBBLE,
    Gdk.KEY_i: Tool.STEP_LABEL,
    Gdk.KEY_I: Tool.STEP_LABEL,
    Gdk.KEY_m: Tool.EMOJI,
    Gdk.KEY_M: Tool.EMOJI,
    # H/O/C (Highlight/Obfuscate/Crop) and Z (Resize) aren't 1:1 Tool
    # mappings / aren't a Tool at all, so they're handled by their own
    # branches in _on_key_press instead of this dict - see those
    # branches' own comments for why.
}

# Matches the real Windows editor's left-toolbar grouping
# (ImageEditorForm.Designer.cs's toolsToolStrip.Items): Select alone,
# then every drawing/annotation tool together. None=a separator after
# this tool - Highlight/Effects (task #36/#42) and Crop/Rotate/Resize
# (task #36) are the next two groups in the real toolbar but aren't
# built yet, so there's nothing to list for them here yet.
#
# _OBFUSCATE_GROUP is a sentinel, not a (Tool, label) pair: Windows has
# one "Obfuscate" toolbar button (btnObfuscate) plus a small attached
# dropdown (obfuscateModeButton) to pick which filter it currently
# applies - Blur or Pixelize (ImageEditorForm.Designer.cs:481-486,
# 1111-1121; ObfuscateContainer.cs:34 - "a FilterContainer for the
# obfuscator filters like blur and pixelate"). Tool.PIXELIZE/Tool.BLUR
# themselves are unchanged (core/tools.py still dispatches on them
# directly) - this only changes how the palette *presents* choosing
# between them; see _build_tool_palette's handling of this sentinel.
_OBFUSCATE_GROUP = "obfuscate_group"

# Task #89: the Effects toolbar dropdown - not a drawing tool at all
# (no Tool enum member, doesn't touch self.tool), so it isn't part of
# the Gtk.RadioButton group the other _TOOL_LABELS entries build -
# see _build_tool_palette's handling of this sentinel and
# _build_effects_control.
_EFFECTS_GROUP = "effects_group"

# Task #90: Rotate CW/CCW and Resize, moved out of the Image menu -
# plain one-shot action buttons like _EFFECTS_GROUP above (no Tool
# enum member, no RadioButton membership), but unlike Effects each is
# its own single click-to-run action rather than a grouped dropdown,
# matching Windows' own separate rotateCwToolstripButton/
# rotateCcwToolstripButton/btnResize. See _build_tool_palette's
# handling of these sentinels and _build_action_button.
_ROTATE_CW_ACTION = "rotate_cw_action"
_ROTATE_CCW_ACTION = "rotate_ccw_action"
_RESIZE_ACTION = "resize_action"

# Task #60: two modes added alongside Blur/Pixelize, no Windows
# equivalent for either - see core/shapes.py's ObfuscateMode docstring
# and REQUIREMENTS.md's task #60 writeup for the security research this
# was built from (Blur/Pixelize are both documented-reversible via
# public tools like Depix/unredacter, even with Pixelize's own noise
# hardening; Solid Fill is the only mode with a provable zero-leak
# guarantee, Color Scramble a middle ground that resists those specific
# attacks but still leaks coarse color statistics).
_TOOL_TO_OBFUSCATE_MODE = {
    Tool.BLUR: ObfuscateMode.BLUR,
    Tool.PIXELIZE: ObfuscateMode.PIXELIZE,
    Tool.SOLID_FILL: ObfuscateMode.SOLID_FILL,
    Tool.SCRAMBLE: ObfuscateMode.SCRAMBLE,
}
_OBFUSCATE_MODE_TO_TOOL = {mode: tool for tool, mode in _TOOL_TO_OBFUSCATE_MODE.items()}

# Compact names for the always-visible mode button - full security
# rating/reasoning lives in _OBFUSCATE_MODE_SECURITY_SUFFIX/_TOOLTIPS
# below instead, shown only in the dropdown menu where someone's
# actually comparing modes, not on every render of the style panel.
_OBFUSCATE_MODE_LABELS = {
    Tool.SOLID_FILL: "Solid Fill",
    Tool.SCRAMBLE: "Color Scramble",
    Tool.PIXELIZE: "Pixelize",
    Tool.BLUR: "Blur",
}

# A 3-tier rating (solid fill > color scramble > blur/pixelize), not
# just a binary secure/insecure flag - reflects that Color Scramble is
# a real, distinct middle ground rather than lumping it in with either
# extreme.
_OBFUSCATE_MODE_SECURITY_SUFFIX = {
    Tool.SOLID_FILL: "most secure",
    Tool.SCRAMBLE: "moderately secure",
    Tool.PIXELIZE: "not secure",
    Tool.BLUR: "not secure",
}

_OBFUSCATE_MODE_TOOLTIPS = {
    Tool.SOLID_FILL: (
        "Completely replaces the covered area with a solid color. Nothing about the "
        "original content can be recovered - the recommended choice for anything sensitive."
    ),
    Tool.SCRAMBLE: (
        "Replaces the area with synthetic noise matched to its overall color. Resists "
        "known reconstruction attacks (e.g. Depix), but a dominant hue may still be inferable."
    ),
    Tool.PIXELIZE: (
        "Reconstructable with publicly available tools (e.g. Depix, unredacter), even with "
        "this port's own noise hardening. Do not use for sensitive information."
    ),
    Tool.BLUR: (
        "Reconstructable with publicly available tools (e.g. Depix, unredacter). Do not use "
        "for sensitive information."
    ),
}

# Dropdown order: most to least secure, so the recommended choices sort
# first rather than matching Blur/Pixelize's original left-to-right
# order from before task #60.
_OBFUSCATE_MODE_ORDER = (Tool.SOLID_FILL, Tool.SCRAMBLE, Tool.PIXELIZE, Tool.BLUR)

# Highlight (task #88) mirrors Obfuscate's entire palette/dropdown
# pattern above - one toolbar button standing in for four modes, a
# style-panel Mode dropdown to choose between them, same reasoning as
# _OBFUSCATE_GROUP's own docstring (real Windows: highlightModeButton
# lives in propertiesToolStrip too, not attached to btnHighlight).
_HIGHLIGHT_GROUP = "highlight_group"
_TOOL_TO_HIGHLIGHT_MODE = {
    Tool.HIGHLIGHT_TEXT: HighlightMode.TEXT_HIGHLIGHT,
    Tool.HIGHLIGHT_AREA: HighlightMode.AREA_HIGHLIGHT,
    Tool.HIGHLIGHT_GRAYSCALE: HighlightMode.GRAYSCALE,
    Tool.HIGHLIGHT_MAGNIFY: HighlightMode.MAGNIFICATION,
}
_HIGHLIGHT_MODE_TO_TOOL = {mode: tool for tool, mode in _TOOL_TO_HIGHLIGHT_MODE.items()}

# No security-tier suffix the way _OBFUSCATE_MODE_SECURITY_SUFFIX has -
# Highlight isn't a redaction/security feature, these are just visual
# style choices, so the dropdown just shows plain names, matching the
# real highlightModeButton's own dropdown items (ImageEditorForm.
# Designer.cs:1191-1196 - plain LanguageKey-driven labels, no rating).
#
# Task #106 port-local renames (user's own call, not a Windows label
# change - real Windows still calls these TEXT_HIGHTLIGHT/AREA_
# HIGHLIGHT/GRAYSCALE): "Text Highlight" -> "Highlight" - the filter
# doesn't detect or relate to text at all (see task #107's resolved
# writeup), just a per-channel min-clamp against the fill color, so
# the old name implied a capability that doesn't exist. "Area
# Highlight"/"Grayscale" -> "Spotlight Focus"/"Spotlight Colorize" -
# working names for the two invert-mode filters (darken/desaturate
# everywhere *outside* the shape, leaving the inside untouched) that
# the user explicitly flagged as not fully satisfying ("not sure that
# captures what it does") - open to a better pair of words later,
# not treated as final. Magnification's own name needed no change.
_HIGHLIGHT_MODE_LABELS = {
    Tool.HIGHLIGHT_TEXT: "Highlight",
    Tool.HIGHLIGHT_AREA: "Spotlight Focus",
    Tool.HIGHLIGHT_GRAYSCALE: "Spotlight Colorize",
    Tool.HIGHLIGHT_MAGNIFY: "Magnification",
}

# Dropdown order matches the real Windows enum/dropdown declaration
# order (FilterContainer.PreparedFilter: TEXT_HIGHTLIGHT, AREA_
# HIGHLIGHT, GRAYSCALE, MAGNIFICATION) - no secure-to-insecure ranking
# to sort by the way Obfuscate's own order has.
_HIGHLIGHT_MODE_ORDER = (Tool.HIGHLIGHT_TEXT, Tool.HIGHLIGHT_AREA, Tool.HIGHLIGHT_GRAYSCALE, Tool.HIGHLIGHT_MAGNIFY)

# Task #106: Highlight mode's own fill color is deliberately restricted
# to this fixed set, unlike every other color field in the style panel
# (_build_color_button's arbitrary Greenshot-style palette dialog) -
# user's own words: "not looking for weird color tricks. this isn't
# photoshop." highlight_filter (core/filters.py) is a per-channel
# min-clamp against the fill color, so a color that keeps at least one
# channel at full 255 always leaves *something* unclamped underneath -
# a dark/low-brightness fill instead collapses the whole effect into a
# flat translucent box (task #107's resolved finding, reported live).
# Every color below satisfies that "at least one full channel" property
# and reads as a classic highlighter-pen color, not an arbitrary choice.
_HIGHLIGHT_FILL_COLORS = [
    ("Yellow", (255, 255, 0, 255)),
    ("Green", (0, 255, 0, 255)),
    ("Pink", (255, 20, 147, 255)),
    ("Orange", (255, 140, 0, 255)),
    ("Blue", (30, 144, 255, 255)),
]

# Crop (task #91) - three Tool values sharing one toolbar button, same
# shape as Highlight/Obfuscate above, but no separate Tool<->Mode
# mapping dance is needed: unlike ObfuscateShape/HighlightShape, no
# Shape (and so no shape.mode field of a different enum type) ever
# exists for Crop, so Tool.CROP_DEFAULT/VERTICAL/HORIZONTAL directly
# *are* the modes core/crop.py's crop_to_rect/crop_out_vertical_strip/
# crop_out_horizontal_strip dispatch on - see _confirm_crop.
_CROP_GROUP = "crop_group"
_CROP_MODE_ORDER = (Tool.CROP_DEFAULT, Tool.CROP_VERTICAL, Tool.CROP_HORIZONTAL)
# Dropdown order matches the real Windows declaration order
# (cropModeButton.DropDownItems, ImageEditorForm.Designer.cs:1143-
# 1145): Default, Vertical, Horizontal, then Auto - Auto isn't in
# _CROP_MODE_ORDER above since it's a one-time seed action, not a
# persistent mode (see _do_auto_crop's own docstring).
_CROP_MODE_LABELS = {
    Tool.CROP_DEFAULT: "Default",
    Tool.CROP_VERTICAL: "Vertical",
    Tool.CROP_HORIZONTAL: "Horizontal",
}

# Solid Fill's own preset redaction labels (task #60 follow-up) - "" is
# "None" (plain box, no text, ObfuscateShape.fill_text's own default).
# Deliberately a fixed list, not free text entry - anyone wanting a
# custom label already has the separate Text tool (see this dropdown's
# own tooltip / REQUIREMENTS.md for the reasoning).
_OBFUSCATE_FILL_TEXT_PRESETS = ("", "REDACTED", "CENSORED", "CLASSIFIED", "CONFIDENTIAL", "SECRET")
_OBFUSCATE_FILL_TEXT_LABELS = {"": "None", **{preset: preset for preset in _OBFUSCATE_FILL_TEXT_PRESETS[1:]}}

# A floor, not a fixed height - Gtk.Widget.set_size_request sets a
# minimum the box can still grow past if it genuinely needs to, so
# this only kicks in for the empty case (Select, nothing selected: no
# style-panel cells are visible at all, see visible_style_fields).
# Without it, an empty row collapses to ~1px (just its own border
# padding) instead, so switching to/from Select visibly yanks the
# whole toolbar+canvas up or down by ~30px - reported live ("this
# causes the whole toolbar to jump down... it made me think something
# was broken").
#
# 42, not 34: a live, fully-laid-out window with a populated row
# (Rectangle's Line/Fill/Thickness/Shadow, and separately Solid
# Fill's own 4-cell row) both allocate to 34px - but
# set_size_request's height applies to the box's own content area,
# while box.set_border_width(4) above pads *outside* that on both
# top and bottom, so asking for exactly 34 still only allocates 26
# (34 - 2*4) once the border padding is added back on top. Confirmed
# empirically (34 -> 26px actual, then 42 -> 34px actual, matching
# every populated row exactly) rather than reasoned out purely from
# GTK's box-model docs.
_STYLE_PANEL_MIN_HEIGHT = 42

_TOOL_LABELS = [
    (Tool.SELECT, "Select"),
    None,
    (Tool.RECTANGLE, "Rectangle"),
    (Tool.ELLIPSE, "Ellipse"),
    (Tool.LINE, "Line"),
    (Tool.ARROW, "Arrow"),
    (Tool.FREEHAND, "Freehand"),
    (Tool.TEXT, "Text"),
    (Tool.SPEECH_BUBBLE, "Speech Bubble"),
    (Tool.STEP_LABEL, "Step Label"),
    (Tool.EMOJI, "Emoji"),
    None,
    # Real Windows order (ImageEditorForm.Designer.cs's toolsToolStrip.
    # Items): ...Emoji, [separator], Highlight, Obfuscate, Effects,
    # [separator], Crop, RotateCW, RotateCCW, Resize - Obfuscate used
    # to sit *before* Text/SpeechBubble/StepLabel/Emoji here, which
    # didn't match; corrected while placing Highlight (task #88) in
    # its own real position, since leaving Obfuscate wrong while
    # placing Highlight right next to it would only be more confusing.
    _HIGHLIGHT_GROUP,
    _OBFUSCATE_GROUP,
    _EFFECTS_GROUP,
    None,
    _CROP_GROUP,
    _ROTATE_CW_ACTION,
    _ROTATE_CCW_ACTION,
    _RESIZE_ACTION,
]

# Appended to a tooltip in parentheses wherever a real keyboard
# shortcut exists (by request) - keyed by the exact tool label used
# in _TOOL_LABELS above, so it's read alongside the same _TOOL_KEYS
# mapping the tooltip is describing rather than duplicating it by
# hand. Tools/actions with no dedicated key (Effects, Preferences,
# Cut/Copy Shape/Paste Shape - the last three deliberately have none,
# since Ctrl+C is already claimed by whole-image copy) simply have no
# entry here and keep their plain label.
_TOOL_TOOLTIP_SHORTCUTS = {
    "Select": "Esc",
    "Rectangle": "R",
    "Ellipse": "E",
    "Line": "L",
    "Arrow": "A",
    "Freehand": "F",
    "Text": "T",
    "Speech Bubble": "S",
    "Step Label": "I",
    "Emoji": "M",
}


def _with_shortcut(label: str, shortcut: str | None) -> str:
    return f"{label} ({shortcut})" if shortcut else label


_HANDLE_SIZE = 6
_HANDLE_FILL = (1.0, 1.0, 1.0)
_HANDLE_STROKE = (0.1, 0.4, 0.9)

# Matches render.py's _PANGO_ALIGNMENT keys/mapping, just onto
# Gtk.Justification (what Gtk.TextView takes) instead of Pango.Alignment.
_TEXT_EDITOR_JUSTIFICATION = {
    "near": Gtk.Justification.LEFT,
    "center": Gtk.Justification.CENTER,
    "far": Gtk.Justification.RIGHT,
}

def _rgba_to_color(rgba: Gdk.RGBA):
    return (
        round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255), round(rgba.alpha * 255),
    )


def _css_rgba(color) -> str:
    r, g, b, a = color
    return f"rgba({r}, {g}, {b}, {a / 255})"


# Real Windows' SaveImageFileDialog "Save as type" options
# (SaveImageFileDialog.cs) - jxr (WMPhoto) is deliberately excluded;
# ico is a legitimate GdkPixbuf save type this port's own
# file_export.py already supports but is a poor fit for a screenshot
# tool's Save As list (no real use case), so left off rather than
# added just because it's technically possible. "orcshot" (task #123)
# is a real option in EditorWindow._do_save's own Save As dialog, just
# appended there separately rather than added to this list - see that
# method's own comment for why. Module-level (not an EditorWindow
# class attribute) since it's also shared by _build_output_settings_tab
# below, which task #119 made reachable without a live editor.
_SAVE_AS_FORMATS = [("png", "PNG"), ("jpg", "JPEG"), ("bmp", "BMP"), ("tiff", "TIFF"), ("gif", "GIF")]

# Not a Windows feature - Windows has no "open in an external editor"
# destination. A new addition, not a port, per explicit request.
# Krita is tried first since it was specifically requested, with GIMP
# as a fallback (overridable - see settings.get_external_editor_preference
# and _build_general_settings_tab below). (name, PATH command, Flatpak
# app ID) - checks both, since Flatpak is how at least one of these is
# commonly installed on Mint (confirmed live: this dev machine has
# Krita only via Flatpak, not on PATH - a plain shutil.which("krita")
# check alone would have missed it). Module-level for the same reason
# as _SAVE_AS_FORMATS above - shared with the settings-tab builder.
_EXTERNAL_EDITOR_CANDIDATES = (
    ("Krita", "krita", "org.kde.krita"),
    ("GIMP", "gimp", "org.gimp.GIMP"),
)


class EditorWindow(Gtk.Window):
    def __init__(self, image: np.ndarray, clipboard_backend: ClipboardBackend = None):
        super().__init__(title="Orcshot image editor")
        self._base_image = image
        self._surface = numpy_to_cairo_surface(image)
        height, width = image.shape[:2]

        if clipboard_backend is None:
            from orcshot.capture.backend_select import default_clipboard_backend

            clipboard_backend = default_clipboard_backend()
        self._clipboard = clipboard_backend

        self.layer = Layer()
        self.undo_redo = UndoRedoStack()
        # The undo_redo.generation as of the last successful save - see
        # the is_modified property below (Surface.Modified port).
        self._saved_generation = 0
        # Faithful port of ImageEditorForm/Surface's zoom (see
        # core/zoom.py's module docstring for citations). Actual Size
        # (100%) is Windows' own initial ZoomFactor too.
        self._zoom = ACTUAL_SIZE_ZOOM
        self._last_wheel_zoom_time = 0.0
        # Per-tool "last used" style (EditorConfigurationHelper.cs:
        # 48-76 - each container type has its own independent style
        # memory, seeded from that type's own preferred default, not
        # one value shared across every tool - see core/tools.py's
        # default_style_for_tool/style_key_for_shape). Built lazily via
        # dict.setdefault as each tool is actually used, rather than
        # eagerly for every Tool up front.
        self._tool_styles = {}
        # Guards _refresh_style_panel's own programmatic .set_value()/
        # .set_active() calls on the thickness/shadow controls from
        # being mistaken for a user edit by _on_thickness_changed/
        # _on_shadow_toggled (their "value-changed"/"toggled" signals
        # don't distinguish who set them).
        self._syncing_style_panel = False
        # Bypasses the tool property below - same reason
        # self._selected_shapes just below sets its own backing field
        # directly: the setter calls _refresh_style_panel, which
        # references style-panel widgets that don't exist yet this
        # early in construction.
        #
        # Matches the Windows source's default (ImageEditorForm.
        # Designer.cs: btnCursor.Checked = true) - the editor opens
        # with Select active, not a drawing tool, so the first click
        # on a fresh capture doesn't accidentally start drawing.
        self._tool = Tool.SELECT
        self._default_obfuscate_amount = 5  # matches ObfuscateShape's own default
        # The color Solid Fill paints with - matches ObfuscateShape's
        # own fill_color default (opaque black, the standard redaction
        # convention).
        self._default_obfuscate_fill_color = (0, 0, 0, 255)
        # Solid Fill's own optional preset label and its color (task #60
        # follow-up). The editor's own policy default is "REDACTED" -
        # the most common real-world use case - a deliberate deviation
        # from ObfuscateShape.fill_text's own neutral "" dataclass
        # default (there's no Windows source to be faithful to here,
        # unlike _default_obfuscate_mode/ObfuscateMode.PIXELIZE above,
        # so bare model construction stays opinion-free while the
        # editor's UI picks a sensible starting point). text_color
        # stays white, legible against the black default fill above.
        self._default_obfuscate_fill_text = "REDACTED"
        self._default_obfuscate_text_color = (255, 255, 255, 255)
        # Which filter the single Obfuscate toolbar button currently
        # applies. Deliberately Solid Fill, not Pixelize - a deviation
        # from ObfuscateContainer.InitializeFields's own default
        # (PreparedFilter.PIXELIZE, still ObfuscateShape's own mode
        # default at the model level, see that class's docstring) -
        # this is the one place this port intentionally diverges from
        # the Windows source's own default rather than just porting it,
        # since Pixelize/Blur are both documented-reversible via public
        # tools (task #60's own REQUIREMENTS.md writeup has the full
        # research trail) and Solid Fill is the only mode with a
        # provable zero-leak guarantee.
        self._default_obfuscate_mode = Tool.SOLID_FILL
        # Highlight's own defaults (task #88) - unlike Obfuscate above,
        # no security reasoning to deviate from Windows for, so these
        # match the real source exactly: highlightModeButton's own
        # SelectedTag/Tag default (ImageEditorForm.Designer.cs:1200-
        # 1201) is PreparedFilter.TEXT_HIGHTLIGHT, and each filter's own
        # AddField default (HighlightFilter's FILL_COLOR=Yellow,
        # BrightnessFilter's BRIGHTNESS=0.9, BlurFilter's BLUR_RADIUS=3,
        # MagnifierFilter's MAGNIFICATION_FACTOR=2 - Filters.cs, cited
        # in full in HighlightShape's own docstring, core/shapes.py).
        self._default_highlight_mode = Tool.HIGHLIGHT_TEXT
        self._default_highlight_fill_color = (255, 255, 0, 255)
        self._default_highlight_brightness = 0.9
        self._default_highlight_blur_radius = 3
        self._default_highlight_magnification = 2
        # Crop's own defaults (task #91) - matches Windows'
        # cropModeButton.SelectedTag/Tag default (ImageEditorForm.
        # Designer.cs:1152-1153), CropModes.Default.
        self._default_crop_mode = Tool.CROP_DEFAULT
        # The in-progress crop selection - not a Shape/Layer entry at
        # all (see core/crop.py's own module docstring on why Crop
        # isn't Layer-participating), just a plain Rect the user is
        # dragging/resizing, confirmed or cancelled via the style
        # panel's own Confirm/Cancel buttons (_build_crop_confirm_
        # buttons), matching Windows' CONFIRMABLE-flag-driven
        # btnConfirm/btnCancel (ImageEditorForm.cs:1399).
        self._crop_selection = None
        self._crop_resize_handle = None
        # Bypasses the selected_shape property below - same reason the
        # base_image property's docstring gives for __init__ setting
        # self._base_image directly: its setter refreshes the
        # obfuscate-amount label, but _obfuscate_amount_label doesn't
        # exist yet this early in construction.
        #
        # The list backing both selected_shape (singular) and
        # selected_shapes (plural, task #125) - ordered, no duplicates,
        # last entry is the "primary" shape (style panel display,
        # resize handles - multi-shape resize is out of scope, matching
        # real Windows' own Adorners, which only ever show on one
        # element's own selection handles even during a multi-select).
        self._selected_shapes = []
        # Last-used whole-image effect settings (DropShadowEffectSettings/
        # TornEdgeEffectSettings, IEditorConfiguration.cs:86-90) - a
        # left-click/keyboard-shortcut re-applies these, a right-click
        # opens the settings dialog to change them first. Session-only
        # here (not persisted across app restarts via settings.py) -
        # a deliberate scope reduction, unlike Windows' ini-backed
        # persistence. Defaults match Windows' own (DropShadowEffect.cs:48-53,
        # TornEdgeEffect.cs defaults).
        self._drop_shadow_settings = {"darkness": 0.6, "size": 7, "offset": (-1, -1)}
        self._torn_edge_settings = {
            "tooth_height": 12, "horizontal_tooth_range": 20, "vertical_tooth_range": 20,
            "edges": (True, True, True, True), "generate_shadow": True,
            "shadow_size": 7, "darkness": 0.6, "offset": (-1, -1),
        }
        # Task #100's Obfuscate Text - same session-only settings
        # precedent as drop_shadow/torn_edge above (see
        # ui/text_obfuscation_dialog.py's DEFAULT_TEXT_OBFUSCATION_
        # SETTINGS for the defaults' own citation).
        self._text_obfuscation_settings = dict(DEFAULT_TEXT_OBFUSCATION_SETTINGS)
        # ObfuscateTextToolStripMenuItemClick's own OCR cache
        # (_surface.CaptureDetails.OcrInformation, ImageEditorForm.cs:
        # 1732) - re-running OCR every time the dialog opens would be
        # slow and pointless if nothing's changed. Invalidated by the
        # base_image setter below whenever the image itself changes
        # (undo/redo, any whole-image effect) - Windows doesn't appear
        # to do this (CaptureDetails is never reset there), but stale
        # OCR word/line bounds after e.g. a resize or rotate would
        # silently misalign every match, which is worse than a
        # redundant re-run.
        self._ocr_result = None
        # The cut/copied shape(s) - a list since task #125's multi-
        # select (Windows' per-shape Cut/Copy/Paste, distinct from
        # _do_copy's whole-image-to-system-clipboard) - not the system
        # clipboard, just in-editor state. None means nothing copied,
        # matching the pre-task-#125 sentinel.
        self._shape_clipboard = None

        # Rubber-band/marquee drag-select (task #125) - an Orcshot-only
        # addition beyond the real port, since real Windows' own
        # Surface.cs has no such feature at all (confirmed via its
        # SurfaceMouseDown/Move handlers - only shift-click toggle and
        # Select All exist there). _rubber_band_origin is the drag's
        # starting (x, y); _rubber_band_rect is the live Rect while
        # dragging, for both the overlay draw and the release-time hit
        # test (core/geometry.py's own Rect.contains_rect - a shape's
        # bounds must be *fully* inside the rectangle to be picked up,
        # not just overlapping, matching Illustrator/Inkscape-style
        # marquee select rather than the "any overlap" convention some
        # other apps use).
        self._rubber_band_origin = None
        self._rubber_band_rect = None
        # Whether shift was held when the current drag/rubber-band
        # started - additive (preserves the existing selection) rather
        # than replacing it, matching shift-click's own toggle
        # semantics.
        self._rubber_band_additive = False

        # drag-to-create state
        self._drag_origin = None
        self._drag_points = None
        self._drag_shape = None

        # click-to-move state - always a list since task #125 (moving a
        # whole multi-selection together, matching real Windows' own
        # SurfaceMouseMove: "dragged element has been selected before
        # -> move all", Surface.cs:1707-1708), even for the single-
        # shape case (a one-element list) - one code path, not two.
        # _move_previews is a parallel list (by position, not a dict
        # keyed by shape) deliberately: these are frozen dataclasses
        # with structural equality, so two coincidentally-identical
        # shapes would collide as the same dict key.
        self._move_shapes = []
        self._move_origin = None
        self._move_previews = []

        # drag-a-handle-to-resize state
        self._resize_shape = None
        self._resize_handle = None
        self._resize_preview = None

        # type-to-edit-text state
        self._editing_text_shape = None
        # None while editing a brand-new shape (discard on cancel/empty
        # commit, nothing to undo since it was never added to history);
        # the pre-edit shape instance while re-editing an existing one
        # (revert to it on cancel, ElementChangeMemento/DeleteElementMemento
        # on commit instead of Add, since it already existed).
        self._editing_original_shape = None

        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_size_request(width, height)
        self._drawing_area.set_can_focus(True)
        self._drawing_area.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK
        )
        self._drawing_area.connect("draw", self._on_draw)
        self._drawing_area.connect("button-press-event", self._on_button_press)
        self._drawing_area.connect("motion-notify-event", self._on_motion)
        self._drawing_area.connect("button-release-event", self._on_button_release)
        self._drawing_area.connect("scroll-event", self._on_scroll)

        # The text-editing overlay (TextContainer.cs's ShowTextBox/
        # HideTextBox) - one reusable Gtk.TextView positioned over
        # whichever shape is being edited via Gtk.Overlay's
        # get-child-position, rather than a separate popup window (a
        # child widget composes correctly with _canvas_scroller's
        # scrolling/zoom for free, which a separate top-level window
        # positioned in screen coordinates would not).
        self._text_editor = Gtk.TextView()
        self._text_editor.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_editor.set_left_margin(0)
        self._text_editor.set_right_margin(0)
        self._text_editor.set_top_margin(0)
        self._text_editor.set_bottom_margin(0)
        self._text_editor.set_no_show_all(True)
        # override_color/override_background_color (used elsewhere in
        # this file, e.g. color_dialog.py's swatches) don't reliably
        # win against this GTK theme's own CSS for a TextView's actual
        # text/caret drawing - confirmed live (a correctly-applied
        # white override_background_color showed, but override_color'd
        # text and the caret never did). A per-widget CssProvider at
        # PRIORITY_USER, targeting the "text" subnode GtkTextView's
        # own CSS docs describe, reliably wins instead.
        self._text_editor_css_provider = Gtk.CssProvider()
        self._text_editor.get_style_context().add_provider(
            self._text_editor_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self._text_editor.get_buffer().connect("changed", self._on_text_editor_changed)
        self._text_editor.connect("key-press-event", self._on_text_editor_key_press)
        self._text_editor.connect("focus-out-event", self._on_text_editor_focus_out)

        self._canvas_overlay = Gtk.Overlay()
        self._canvas_overlay.add(self._drawing_area)
        self._canvas_overlay.add_overlay(self._text_editor)
        self._canvas_overlay.connect("get-child-position", self._on_canvas_overlay_get_child_position)

        # Wraps the canvas so an over-max-window-size zoom level (see
        # _set_zoom) is still reachable via scrolling - matches
        # Windows' own panel1 (a NonJumpingPanel), which is always a
        # scrollable container even though _set_zoom normally resizes
        # the window instead of relying on it.
        self._canvas_scroller = Gtk.ScrolledWindow()
        self._canvas_scroller.add(self._canvas_overlay)

        content_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_row.pack_start(self._build_tool_palette(), False, False, 0)
        content_row.pack_start(self._canvas_scroller, True, True, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(self._build_menu_bar(), False, False, 0)
        box.pack_start(self._build_action_toolbar(), False, False, 0)
        box.pack_start(self._build_style_panel(), False, False, 0)
        box.pack_start(content_row, True, True, 0)
        box.pack_start(self._build_status_bar(), False, False, 0)
        self.add(box)

        self.connect("key-press-event", self._on_key_press)
        # Registers with the running OrcshotApplication (if any) so
        # it can decline to start an overlapping capture while this
        # editor is open - see app.py's _block_if_editor_open. This
        # replaces a stale `self.connect("destroy", Gtk.main_quit)`
        # left over from early standalone-script testing (a plain
        # Gtk.main() loop, not the real Gtk.Application) - confirmed
        # live that call was already a harmless no-op against the real
        # app (Gtk.main_quit has nothing to quit when Gtk.Application.
        # run() is what's actually driving the loop), but a no-op that
        # printed a scary Gtk-CRITICAL warning on every editor close.
        app = Gio.Application.get_default()
        if app is not None:
            app.register_editor_window(self)
        self.connect("destroy", self._on_destroy)
        # Faithful port of ImageEditorFormFormClosing (ImageEditorForm.
        # cs:1004-1033) - see _on_delete_event. Covers both the window
        # manager's own close button and File > Close (self.close(),
        # which Gtk.Window.close() turns into the same delete-event).
        self.connect("delete-event", self._on_delete_event)

    def show_all(self) -> None:
        """Overridden because Gtk.Widget.show_all() unconditionally
        shows every descendant, including the style-panel cells
        _refresh_style_panel already hid during __init__ (nothing is
        selected and Select is the active tool at construction time, so
        every cell starts hidden) - undoing that hide the moment the
        real app (ui/destination_picker.py's _open_editor) calls
        editor.show_all() to actually display the window. Confirmed
        live: without this override, every style-panel control showed
        at once regardless of active tool/selection, silently defeating
        tasks #57/#58's whole point. Re-running _refresh_style_panel
        after the real show_all() re-applies the correct hidden set.

        Also the hook for the initial GetOptimalWindowSize-equivalent
        resize (task #97) - Windows fires this from SurfaceSizeChanged
        as soon as MatchSizeToCapture's default-on image-load resize
        runs (ImageEditorForm.cs:599-604), but __init__ can't call
        _resize_canvas_and_window itself (its docstring on the
        base_image setter explains why: no real GdkWindow/allocation
        exists until the window is shown). _canvas_scroller (a
        Gtk.ScrolledWindow) doesn't propagate the canvas's size_request
        to the top-level window the way Windows' own panel1 does, so
        without this the window opened at a fixed toolbar/menu-driven
        size regardless of the captured image's dimensions - confirmed
        live, a 3000x2000 and a 40x40 capture produced the identical
        initial window size. GLib.idle_add defers past GTK's own
        pending resize queue (GTK_PRIORITY_RESIZE runs before default-
        priority idle), so the allocations _resize_canvas_and_window
        reads are real ones from the just-completed initial layout,
        not stale pre-realize zeros.
        """
        super().show_all()
        self._refresh_style_panel()
        GLib.idle_add(self._resize_canvas_and_window)

    @property
    def is_modified(self) -> bool:
        """Faithful port of Surface.Modified (ISurface.cs:193) - true
        whenever anything has changed since the last successful save
        (including via undo/redo, which real Greenshot also counts as
        a modification - see core/history.py's UndoRedoStack.generation
        docstring). Checked by _on_delete_event before closing, matching
        ImageEditorFormFormClosing's own `_surface.Modified` check
        (ImageEditorForm.cs:1006).
        """
        return self.undo_redo.generation != self._saved_generation

    @property
    def selected_shape(self):
        """The "primary" selected shape - the most recently selected
        one, or the sole one when exactly one is selected. None when
        zero (or, ambiguously, when the primary itself is what matters
        for a single-shape operation on a multi-selection - callers
        that need to act on the *whole* selection use selected_shapes
        below instead).
        """
        return self._selected_shapes[-1] if self._selected_shapes else None

    @selected_shape.setter
    def selected_shape(self, shape) -> None:
        """Keeps the style panel in sync with whichever shape/tool is
        actually relevant right now - see _refresh_style_panel.
        Centralizing this in the property setter (rather than a call
        at each of the many call sites that assign self.selected_shape
        throughout this file) means it can't be missed by a future
        one. Bypassed by __init__ - see self._selected_shapes's own
        comment there.

        Replaces the *whole* selection with just ``shape`` (or clears
        it for None) - task #125's own multi-select additions
        (shift-click, rubber-band, Select All) go through
        _set_selected_shapes instead, which this delegates to so both
        paths share one place that calls _refresh_style_panel.
        """
        self._set_selected_shapes([shape] if shape is not None else [])

    @property
    def selected_shapes(self) -> list:
        """Every currently-selected shape, in selection order (last
        entry is the "primary" one - see selected_shape above). A
        copy, not a live view - callers mutate the selection through
        _set_selected_shapes, not by editing this list in place.
        """
        return list(self._selected_shapes)

    def _set_selected_shapes(self, shapes: list) -> None:
        """The one place that actually replaces the selection list and
        refreshes the style panel - both selected_shape's setter
        (single-shape callers, task #95 and earlier) and task #125's
        own multi-select logic (shift-click toggle, rubber-band,
        Select All) funnel through here.
        """
        self._selected_shapes = list(shapes)
        self._refresh_style_panel()

    @property
    def tool(self):
        return self._tool

    @tool.setter
    def tool(self, value) -> None:
        """Keeps the style panel in sync with the newly active tool's
        own per-type style memory - see _refresh_style_panel/
        _active_style. Centralized here for the same reason
        selected_shape's setter is. Bypassed by __init__ - see
        self._tool's own comment there.

        Also discards any in-progress crop selection when switching to
        a non-Crop tool - the single choke point every tool switch
        passes through (palette clicks, keyboard shortcuts, Crop's own
        mode-dropdown), so this is the one place that needs to enforce
        it rather than every caller remembering to. Matches Windows:
        picking a different tool implicitly abandons an unconfirmed
        CropContainer the same way InitCropMode's own RemoveCropContainer
        call does on an explicit mode change (see _set_crop_mode).
        """
        if value not in _CROP_MODE_ORDER:
            self._crop_selection = None
            self._crop_resize_handle = None
        self._tool = value
        self._refresh_style_panel()

    def _style_for_tool(self, tool: Tool) -> ShapeStyle:
        """A tool's own current style, seeding it from its faithful
        per-type default (core/tools.py's default_style_for_tool) the
        first time it's ever asked for - see self._tool_styles's own
        comment in __init__.
        """
        return self._tool_styles.setdefault(tool, default_style_for_tool(tool))

    def _active_style(self) -> ShapeStyle:
        """Which ShapeStyle the style panel is currently showing/
        editing: the selected shape's own live style if one is
        selected and has one (so the panel reflects its real current
        colors, and restyling updates that exact shape's own type's
        memory - see _apply_style_change), else the active tool's own
        remembered style (what the *next* shape drawn with it starts
        out as). Always returns something, even when neither really
        applies (Tool.SELECT, nothing selected) - the style-panel
        controls just aren't visible then (visible_style_fields), so
        it's never actually shown.
        """
        shape = self.selected_shape
        if shape is not None and hasattr(shape, "style"):
            return shape.style
        return self._style_for_tool(self.tool)

    def _refresh_style_panel(self) -> None:
        """Three things that all depend on the same (active tool,
        selected shape) pair, refreshed together:

        1. The obfuscate-amount spinner's label reflects the
           *selected* ObfuscateShape's own mode when there is one - so
           re-selecting an existing Blur box shows "Blur Radius:" even
           if some other tool is currently active - falling back to
           the active tool's mode otherwise.
        2. Which style-panel controls are even visible
           (visible_style_fields, core/tools.py) - faithful port of
           RefreshFieldControls (ImageEditorForm.cs:1375): a Rectangle
           shows Line/Fill/Thickness/Shadow but not Amount; Pixelize
           shows Amount but nothing else; Select with nothing selected
           shows nothing at all. Each field's label+control live
           together in one Gtk.Box "cell" (self._style_field_widgets,
           built in _build_style_panel) so hiding a field hides both
           at once.
        3. The controls' own displayed values track _active_style() -
           each tool has its own independent style memory now (see
           self._tool_styles in __init__), so switching tools (or
           selecting a differently-styled shape) needs to visibly
           update the swatches/thickness/shadow controls too, not just
           their visibility. The line/fill swatches already re-read
           their color via a lambda on every repaint (_build_color_
           button), so a queue_draw() is enough for them; the spinner/
           checkbox are plain stateful GTK widgets that need an actual
           .set_value()/.set_active() call - guarded against re-
           entering _on_thickness_changed/_on_shadow_toggled, which
           would otherwise treat this programmatic sync as a user edit
           and push a redundant memento.
        """
        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            amount_tool = _OBFUSCATE_MODE_TO_TOOL[shape.mode]
        else:
            amount_tool = self.tool
        self._obfuscate_amount_label.set_text(self._obfuscate_amount_label_text(amount_tool))

        visible_fields = visible_style_fields(self.tool, shape)
        for field_name, cell in self._style_field_widgets.items():
            cell.set_visible(field_name in visible_fields)
        # The separator only makes sense while Amount is showing (style
        # fields and obfuscate_amount are never visible at the same
        # time - see visible_style_fields - so it'd otherwise just
        # dangle before an empty style-fields cluster).
        self._style_separator.set_visible(STYLE_FIELD_OBFUSCATE_AMOUNT in visible_fields)

        style = self._active_style()
        self._syncing_style_panel = True
        try:
            self._thickness_spin.set_value(style.line_thickness)
            self._shadow_check.set_active(style.shadow)
        finally:
            self._syncing_style_panel = False
        self._line_color_swatch.queue_draw()
        self._fill_color_swatch.queue_draw()
        self._obfuscate_fill_swatch.queue_draw()
        self._obfuscate_text_color_swatch.queue_draw()

        fill_text = shape.fill_text if isinstance(shape, ObfuscateShape) else self._default_obfuscate_fill_text
        self._obfuscate_fill_text_button.set_label(self._obfuscate_fill_text_label(fill_text))
        if not self._obfuscate_fill_text_items[fill_text].get_active():
            self._obfuscate_fill_text_items[fill_text].set_active(True)

        # Mode dropdown button labels weren't previously kept in sync
        # here either (only _set_obfuscate_mode itself updated them,
        # so selecting an *existing* shape whose mode differs from
        # whatever was last prepared left the button showing the wrong
        # mode) - a real, pre-existing gap, fixed here alongside adding
        # Highlight's own equivalent rather than copying the same bug
        # into new code (same reasoning as the swatch queue_draw()
        # calls above).
        obfuscate_mode_tool = _OBFUSCATE_MODE_TO_TOOL[shape.mode] if isinstance(shape, ObfuscateShape) \
            else self._default_obfuscate_mode
        self._obfuscate_mode_button.set_label(self._obfuscate_mode_label(obfuscate_mode_tool))
        if not self._obfuscate_mode_items[obfuscate_mode_tool].get_active():
            self._obfuscate_mode_items[obfuscate_mode_tool].set_active(True)

        self._highlight_fill_swatch.queue_draw()
        highlight_mode_tool = _HIGHLIGHT_MODE_TO_TOOL[shape.mode] if isinstance(shape, HighlightShape) \
            else self._default_highlight_mode
        self._highlight_mode_button.set_label(self._highlight_mode_label(highlight_mode_tool))
        if not self._highlight_mode_items[highlight_mode_tool].get_active():
            self._highlight_mode_items[highlight_mode_tool].set_active(True)

        self._syncing_style_panel = True
        try:
            if isinstance(shape, HighlightShape):
                self._highlight_brightness_spin.set_value(shape.brightness)
                self._highlight_blur_radius_spin.set_value(shape.blur_radius)
                self._highlight_magnification_spin.set_value(shape.magnification_factor)
            else:
                self._highlight_brightness_spin.set_value(self._default_highlight_brightness)
                self._highlight_blur_radius_spin.set_value(self._default_highlight_blur_radius)
                self._highlight_magnification_spin.set_value(self._default_highlight_magnification)
        finally:
            self._syncing_style_panel = False

        # Crop (task #91) has no selected-shape state to fall back to
        # (see _build_crop_control's own docstring on why) - the Mode
        # label always just reflects self._default_crop_mode.
        self._crop_mode_button.set_label(_CROP_MODE_LABELS[self._default_crop_mode])
        if not self._crop_mode_items[self._default_crop_mode].get_active():
            self._crop_mode_items[self._default_crop_mode].set_active(True)
        self._crop_confirm_cell.set_visible(self._crop_selection is not None)

    @property
    def base_image(self) -> np.ndarray:
        return self._base_image

    @base_image.setter
    def base_image(self, image: np.ndarray) -> None:
        """The only place _surface (the composited-onto Cairo surface)
        gets rebuilt from a new base image, and the canvas/window
        resized to match - so BackgroundChangeMemento (core/history.py)
        restoring a previous (possibly differently-sized) image on
        undo/redo gets correct resizing "for free" just by assigning
        here, the same as every whole-image effect below. Bypassed by
        __init__, which sets self._base_image directly before
        _drawing_area/_canvas_scroller exist to resize.
        """
        self._base_image = image
        self._surface = numpy_to_cairo_surface(image)
        self._resize_canvas_and_window()
        img_h, img_w = image.shape[:2]
        self._dimensions_label.set_text(f"{img_w} x {img_h}")
        self._refresh_remove_transparency_visibility()
        # Task #100 - stale OCR word/line bounds from before this
        # change would silently misalign Obfuscate Text's matches, see
        # self._ocr_result's own __init__ comment.
        self._ocr_result = None

    def _build_menu_bar(self) -> Gtk.MenuBar:
        """File/Edit/Object/Zoom/Help, matching real Windows Greenshot's
        actual editor menu structure (ImageEditorForm.Designer.cs:589-
        595's menuStrip1.Items - File/Edit/Object/Plugin[hidden]/Zoom/
        Help; no top-level Image menu exists there at all, and Zoom
        really is a top-level menu, not just the status-bar dropdown -
        see _build_zoom_menu). Duplicates the toolbar/keyboard-shortcut
        actions rather than replacing them - matching Windows, which
        has both. Icons mirror the toolbar's own (menu and toolbar
        share one icon set in Windows too - e.g. copyToolStripMenuItem.
        Image is literally the same bitmap as its toolbar button).

        """
        menu_bar = Gtk.MenuBar()
        # Query self's style context, not menu_bar's own - a freshly
        # constructed, not-yet-parented Gtk.MenuBar() has no inherited
        # CSS context yet and resolves to a wrong/transparent color
        # (confirmed live: rendered every Object menu tool icon
        # invisible). The top-level window's own context resolves
        # correctly even pre-realize - same pattern _build_tool_palette
        # already uses for its own hand-drawn icons, see its comment.
        icon_color = _rgba_to_color(self.get_style_context().get_color(Gtk.StateFlags.NORMAL))

        def add_menu(label: str) -> Gtk.Menu:
            menu = Gtk.Menu()
            item = Gtk.MenuItem(label=label)
            item.set_submenu(menu)
            menu_bar.append(item)
            return menu

        def menu_item(label: str, handler, *, icon_name: str = None, icon_image: Gtk.Image = None) -> Gtk.MenuItem:
            item = Gtk.MenuItem()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            if icon_image is not None:
                box.pack_start(icon_image, False, False, 0)
            elif icon_name is not None:
                box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
            box.pack_start(Gtk.Label(label=label), False, False, 0)
            item.add(box)
            item.connect("activate", lambda _i: handler())
            return item

        def add_item(menu: Gtk.Menu, label: str, handler, *, icon_name: str = None, icon_image: Gtk.Image = None) -> None:
            menu.append(menu_item(label, handler, icon_name=icon_name, icon_image=icon_image))

        def add_submenu(menu: Gtk.Menu, label: str, *, icon_name: str = None) -> Gtk.Menu:
            submenu = Gtk.Menu()
            item = Gtk.MenuItem()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            if icon_name is not None:
                box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
            box.pack_start(Gtk.Label(label=label), False, False, 0)
            item.add(box)
            item.set_submenu(submenu)
            menu.append(item)
            return submenu

        file_menu = add_menu("File")
        # Open... (task #129) has no real Windows equivalent - its own
        # File menu has no "Open" item at all; the closest analogue,
        # LoadElementsToolStripMenuItemClick (this port's own Object >
        # Load Objects), loads a shape-only template onto the
        # *current* surface rather than opening a saved capture as a
        # new document. Placed first, ahead of Save, matching the
        # conventional Open-before-Save ordering most apps use even
        # though real Windows has nothing here to match against.
        add_item(file_menu, "Open...", self._do_open, icon_name="document-open-symbolic")
        file_menu.append(Gtk.SeparatorMenuItem())
        # Save = silent quick-save (preferred location, auto filename,
        # no dialog) vs. Save As... = always dialog-driven - real
        # Windows distinguishes these too (SaveToolStripMenuItem vs.
        # SaveAsToolStripMenuItem is actually the *destination list*
        # populated into fileStripMenuItem at runtime, see
        # FileMenuDropDownOpening in the real source; this port's own
        # "Save" toolbar button/destination-picker entry was already
        # this exact quick-save mechanism, task #95 just menu-ifies it
        # and gives dialog-driven saving its own honestly-named item
        # rather than overloading "Save...").
        add_item(file_menu, "Save", self._do_quick_save, icon_name="document-save-symbolic")
        add_item(file_menu, "Save As...", self._do_save, icon_name="document-save-as-symbolic")
        add_item(file_menu, "Copy to Clipboard", self._do_copy, icon_name="edit-copy-symbolic")
        add_item(file_menu, "Print...", self._do_print, icon_name="document-print-symbolic")
        file_menu.append(Gtk.SeparatorMenuItem())
        add_item(file_menu, "Insert Image...", self._do_insert_image, icon_name="insert-image-symbolic")
        add_item(file_menu, "Insert SVG...", self._do_insert_svg, icon_name="insert-image-symbolic")
        file_menu.append(Gtk.SeparatorMenuItem())
        add_item(file_menu, "Screenshot Save Location...", self._do_choose_save_location, icon_name="folder-symbolic")
        file_menu.append(Gtk.SeparatorMenuItem())
        add_item(file_menu, "Close", self.close, icon_name="window-close-symbolic")

        edit_menu = add_menu("Edit")
        add_item(edit_menu, "Undo", self._do_undo, icon_name="edit-undo-symbolic")
        add_item(edit_menu, "Redo", self._do_redo, icon_name="edit-redo-symbolic")
        edit_menu.append(Gtk.SeparatorMenuItem())
        # Cut/Copy/Paste here act on the selected *shape*, matching
        # real Windows' cutToolStripMenuItem/copyToolStripMenuItem/
        # pasteToolStripMenuItem (grouped with Undo/Redo, all
        # Enabled=false until something's selected) - the whole-image
        # "Copy Image to Clipboard" destination lives in File instead,
        # since that one's always available regardless of selection.
        # Our previous Edit>Copy wrongly called the whole-image copy
        # (_do_copy) - fixed here while rebuilding this menu.
        add_item(edit_menu, "Cut", self._do_cut_shape, icon_name="edit-cut-symbolic")
        add_item(edit_menu, "Copy", self._do_copy_shape, icon_name="edit-copy-symbolic")
        add_item(edit_menu, "Paste", self._do_paste_shape, icon_name="edit-paste-symbolic")
        edit_menu.append(Gtk.SeparatorMenuItem())
        add_item(edit_menu, "Duplicate", self._do_duplicate, icon_name="edit-copy-symbolic")
        edit_menu.append(Gtk.SeparatorMenuItem())
        add_item(edit_menu, "Preferences...", self._do_show_settings, icon_name="preferences-system-symbolic")
        edit_menu.append(Gtk.SeparatorMenuItem())
        add_item(edit_menu, "Insert Window...", self._do_insert_window, icon_name="list-add-symbolic")
        edit_menu.append(Gtk.SeparatorMenuItem())
        add_item(edit_menu, "Clear All", self._do_clear, icon_name="edit-clear-all-symbolic")

        object_menu = add_menu("Object")
        # Mirrors the tool palette's own shape tools (real Windows does
        # the same - addRectangleToolStripMenuItem etc. duplicate the
        # toolStrip1 buttons exactly). Reuses set_active(True) on the
        # same RadioToolButtons the palette itself owns (not
        # self.tool = ... directly) so the toolbar's own pressed state
        # stays in sync - the identical pattern _on_key_press's letter
        # shortcuts already use. Icons scale with the same "Icon size"
        # Preferences setting as the toolbar (settings.get_icon_size) -
        # matches real Windows, whose menuStrip1.ImageScalingSize is
        # literally set to the same coreConfiguration.IconSize its
        # toolbar uses (ImageEditorForm.Designer.cs:586), not a
        # separate menu-specific size.
        for tool, label in (
            (Tool.RECTANGLE, "Rectangle"),
            (Tool.ELLIPSE, "Ellipse"),
            (Tool.LINE, "Line"),
            (Tool.ARROW, "Arrow"),
            (Tool.FREEHAND, "Freehand"),
            (Tool.TEXT, "Text"),
            (Tool.SPEECH_BUBBLE, "Speech Bubble"),
            (Tool.STEP_LABEL, "Counter"),
        ):
            add_item(
                object_menu, label,
                lambda tool=tool: self._tool_buttons[tool].set_active(True),
                icon_image=tool_icon_image(tool, icon_color, size=get_icon_size()),
            )
        object_menu.append(Gtk.SeparatorMenuItem())
        # Select All sits directly before Delete, same group, no
        # separator between them - matches real Windows' own
        # objectToolStripMenuItem.DropDownItems order exactly
        # (selectAllToolStripMenuItem, removeObjectToolStripMenuItem,
        # ImageEditorForm.Designer.cs:731-732). Task #125 - needed real
        # multi-selection to exist first (see EditorWindow.
        # selected_shapes/_set_selected_shapes).
        add_item(object_menu, "Select All", self._do_select_all, icon_name="edit-select-all-symbolic")
        add_item(object_menu, "Delete", self._do_delete, icon_name="edit-delete-symbolic")
        object_menu.append(Gtk.SeparatorMenuItem())
        # icon_name was missing entirely here (unlike every sibling in
        # this menu - Delete, Save/Load Objects) - live-verified as a
        # real visual inconsistency (task #127/#128 feedback): flush-
        # left "Arrange" sitting between icon-indented rows looked like
        # a spacing bug. Reuses "Bring to Top"'s own icon rather than
        # inventing an unrelated one for the submenu header.
        arrange_menu = add_submenu(object_menu, "Arrange", icon_name="go-top-symbolic")
        add_item(arrange_menu, "Bring to Top", self._do_bring_to_front, icon_name="go-top-symbolic")
        add_item(arrange_menu, "Up One Level", self._do_bring_forward, icon_name="go-up-symbolic")
        add_item(arrange_menu, "Down One Level", self._do_send_backward, icon_name="go-down-symbolic")
        add_item(arrange_menu, "Send to Bottom", self._do_send_to_back, icon_name="go-bottom-symbolic")
        # No separator here - real Windows' own objectToolStripMenuItem
        # DropDownItems.AddRange puts saveElementsToolStripMenuItem/
        # loadElementsToolStripMenuItem directly after arrangeToolStripMenuItem
        # too (ImageEditorForm.Designer.cs:734-736).
        add_item(object_menu, "Save Objects...", self._do_save_objects, icon_name="document-save-symbolic")
        add_item(object_menu, "Load Objects...", self._do_load_objects, icon_name="document-open-symbolic")

        zoom_menu = add_menu("Zoom")
        self._populate_zoom_menu(zoom_menu)

        help_menu = add_menu("Help")
        add_item(help_menu, "Online Help", self._do_open_online_help, icon_name="help-browser-symbolic")
        # Orcshot-only addition (task #103) - real Windows has no menu
        # item here at all, its own update check is purely a silent
        # background timer (UpdateService.cs, see REQUIREMENTS.md).
        add_item(
            help_menu, "Check for Updates...", self._do_check_for_updates,
            icon_name="software-update-available-symbolic",
        )
        add_item(help_menu, "About Orcshot", self._do_show_about, icon_name="help-about-symbolic")

        return menu_bar

    def _populate_zoom_menu(self, menu: Gtk.Menu) -> None:
        """Shared by the top-level Zoom menu (above) and the status
        bar's zoom dropdown (_build_status_bar) - real Windows does the
        same, zoomMainMenuItem and zoomStatusDropDownBtn both open the
        exact same zoomMenuStrip (ImageEditorForm.Designer.cs:594,1735,
        1891) rather than each owning a separate copy. Icons only on
        Zoom In/Out, matching real Windows - the percentage/Best Fit/
        Actual Size entries have no .Image set there either.
        """

        def add(label: str, handler, *, icon_name: str = None) -> None:
            item = Gtk.MenuItem()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            if icon_name is not None:
                box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
            box.pack_start(Gtk.Label(label=label), False, False, 0)
            item.add(box)
            item.connect("activate", lambda _i: handler())
            menu.append(item)

        add("Zoom In", self._do_zoom_in, icon_name="zoom-in-symbolic")
        add("Zoom Out", self._do_zoom_out, icon_name="zoom-out-symbolic")
        add("Best Fit", self._do_zoom_best_fit)
        menu.append(Gtk.SeparatorMenuItem())
        for level in ZOOM_LEVELS:
            label = zoom_percent_label(level) + (" - Actual Size" if level == ACTUAL_SIZE_ZOOM else "")
            add(label, lambda level=level: self._set_zoom(level))
        menu.show_all()

    def _do_open_online_help(self) -> None:
        """Placeholder target - real help-page content (probably a
        GitHub wiki page) doesn't exist yet, tracked separately from
        this menu-wiring task since it's content-writing, not code.
        Opens the repo root in the meantime rather than a dead link.
        """
        webbrowser.open("https://github.com/orcshot/orcshot")

    def _do_quick_save(self) -> None:
        """Real Windows' silent "Save" - writes immediately to the
        preferred output location with an auto-generated filename, no
        dialog for the filename/location itself - distinct from
        "Save As..." (_do_save below, always dialog-driven).

        Now genuinely uses "preferred file settings" (task #95's
        Output tab, settings.OutputSettings) instead of the fixed
        pattern/`.png` this used before that tab existed - filename
        pattern (core/filename_pattern.py), primary format, JPEG
        quality, and copy-path-to-clipboard are all real now.

        The quality dialog below can still interrupt this "quick"
        save - confirmed faithful, not a bug: real Windows'
        FileDestination.cs (its own quick-save-to-file destination)
        shows QualityDialog under the identical
        CoreConfig.OutputFilePromptQuality gate this port's own
        _maybe_show_quality_dialog uses, format-independent, exactly
        like the Save As path does. Off by default, so most users
        never see it either way.
        """
        self._commit_text_editing_if_active()
        settings = get_output_settings()
        self._maybe_show_quality_dialog(settings.primary_format)
        settings = get_output_settings()  # re-read - the dialog may have changed jpeg_quality
        directory = get_output_directory()
        counter = consume_filename_counter()
        filename = (
            resolve_filename_pattern(settings.filename_pattern, datetime.now(), counter, mode=settings.filename_pattern_mode)
            + "." + settings.primary_format
        )
        path = directory / filename
        save_image_to_file(self._composited_image(), path, jpeg_quality=settings.jpeg_quality)
        self._saved_generation = self.undo_redo.generation
        if settings.copy_path_to_clipboard:
            Gtk.Clipboard.get_default(self.get_display()).set_text(str(path), -1)

    def _maybe_show_quality_dialog(self, output_format: str) -> None:
        """Faithful port of QualityDialog (Greenshot.Base/Controls/
        QualityDialog.cs) - a JPEG quality slider, shown before a save
        completes when "Always show quality dialog" (settings.
        OutputSettings.always_show_quality_dialog) is on. Format-
        independent gate matching Windows exactly (the slider is only
        *interactive* for jpg, but the dialog itself shows regardless -
        ImageIO.cs:422/FileDestination.cs:80 gate purely on the
        setting, not on format). A no-op when the setting is off,
        which is the default - most users never see this.
        """
        settings = get_output_settings()
        if not settings.always_show_quality_dialog:
            return
        self._commit_text_editing_if_active()
        dialog = Gtk.Dialog(title="JPEG Quality", transient_for=self)
        dialog.add_buttons("Continue", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_value(settings.jpeg_quality)
        scale.set_digits(0)
        scale.set_sensitive(output_format == "jpg")
        content.pack_start(Gtk.Label(label="JPEG quality:"), False, False, 0)
        content.pack_start(scale, True, True, 0)

        dialog.show_all()
        dialog.run()
        set_output_settings(dataclass_replace(settings, jpeg_quality=int(scale.get_value())))
        dialog.destroy()

    def _do_show_setup(self) -> None:
        """Task #104: re-runs the first-run hotkey/autostart dialog on
        demand instead of only once at first launch. Also the fix for
        hotkeys silently breaking after a rename (task #105's Greenshot
        -> Orcshot rebrand did exactly this on the dev machine) - a
        stale binding still occupying e.g. Print shows up here as a
        normal conflict to overwrite, the same as any pre-existing
        binding would.
        """
        from orcshot.ui.first_run_setup import run_setup_dialog

        run_setup_dialog(self)

    def _do_check_for_updates(self) -> None:
        app = Gio.Application.get_default()
        if app is not None:
            app.check_for_updates_now(self)

    def _do_show_about(self) -> None:
        dialog = Gtk.AboutDialog(transient_for=self)
        dialog.set_program_name("Orcshot")
        dialog.set_comments("A Linux port of Greenshot - not affiliated with or endorsed by the Greenshot project")
        dialog.set_logo_icon_name(None)
        try:
            dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file(str(LOGO_PATH)))
        except GLib.Error:
            pass
        dialog.run()
        dialog.destroy()

    def _build_tool_palette(self) -> Gtk.Box:
        """The drawing tools, in a vertical column on the left -
        matching Windows Greenshot's editor layout, and separate from
        _build_action_toolbar's horizontal row of document/edit
        actions (Windows keeps those distinct too).

        Plain Gtk.RadioButtons in a Gtk.Box, not Gtk.RadioToolButton in
        a Gtk.Toolbar(orientation=VERTICAL) - the more common pattern
        for a vertical icon palette anyway (same idea as GIMP/
        Inkscape's toolbox). This wasn't chasing a real bug: a first
        pass looked clipped in a screenshot (the last of 10 buttons
        seemed to be missing), but per-button allocation checks showed
        every one correctly sized and mapped - it was just flush
        against the window's bottom edge with zero padding, easy to
        miss at a glance. The border_width below is the actual fix;
        the widget swap just happened first and turned out harmless,
        so it stayed.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_border_width(4)

        # Hand-drawn icons don't get theme colors for free the way the
        # standard "-symbolic" icon names below do - query the window's
        # actual foreground color (resolves correctly even pre-realize,
        # confirmed empirically) so they follow light/dark theme too.
        icon_color = _rgba_to_color(self.get_style_context().get_color(Gtk.StateFlags.NORMAL))

        self._tool_buttons = {}
        group_leader = None
        for entry in _TOOL_LABELS:
            if entry is None:
                box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)
                continue
            if entry is _OBFUSCATE_GROUP:
                group_leader = self._build_obfuscate_control(box, group_leader, icon_color)
                continue
            if entry is _HIGHLIGHT_GROUP:
                group_leader = self._build_highlight_control(box, group_leader, icon_color)
                continue
            if entry is _EFFECTS_GROUP:
                self._build_effects_control(box, icon_color)
                continue
            if entry is _CROP_GROUP:
                group_leader = self._build_crop_control(box, group_leader, icon_color)
                continue
            if entry is _ROTATE_CW_ACTION:
                self._build_action_button(
                    box, rotate_cw_icon_image(icon_color), "Rotate Clockwise (Ctrl+.)", self._do_rotate_cw,
                )
                continue
            if entry is _ROTATE_CCW_ACTION:
                self._build_action_button(
                    box, rotate_ccw_icon_image(icon_color), "Rotate Counterclockwise (Ctrl+,)",
                    self._do_rotate_ccw,
                )
                continue
            if entry is _RESIZE_ACTION:
                self._build_action_button(box, resize_icon_image(icon_color), "Resize... (Z)", self._do_resize)
                continue
            tool, label = entry
            button = Gtk.RadioButton.new_from_widget(group_leader)
            if group_leader is None:
                group_leader = button
            button.set_mode(False)  # flat icon toggle, not a radio-circle-plus-label
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_image(tool_icon_image(tool, color=icon_color, size=get_icon_size()))
            button.set_tooltip_text(_with_shortcut(label, _TOOL_TOOLTIP_SHORTCUTS.get(label)))
            button.set_active(tool is self.tool)
            button.connect("toggled", self._on_tool_button_toggled, tool)
            box.pack_start(button, False, False, 0)
            self._tool_buttons[tool] = button

        return box

    def _build_obfuscate_control(self, box: Gtk.Box, group_leader, icon_color) -> Gtk.RadioButton:
        """The single "Obfuscate" palette entry: a plain radio-toggle
        button, just like every other tool button, that activates
        whichever mode is currently prepared (self._default_obfuscate_mode)
        when clicked. All four obfuscate Tools (PIXELIZE/BLUR/SOLID_FILL/
        SCRAMBLE - task #60 added the latter two) map to this same
        button in self._tool_buttons, so anything that looks a tool up
        by value (keyboard shortcuts, _on_tool_button_toggled's
        callers) still finds a real widget for any of them.

        The mode picker itself is *not* here - Windows' real
        obfuscateModeButton lives in propertiesToolStrip (this port's
        style panel, see _build_style_panel's STYLE_FIELD_OBFUSCATE_MODE
        cell), not attached to btnObfuscate in the tools toolbar
        (confirmed from ImageEditorForm.Designer.cs's own
        toolsToolStrip.Items/propertiesToolStrip.Items lists - they're
        two separate toolbars). An earlier version of this control
        attached a dropdown directly here, which was closer to a guess
        than a citation; moved once the real layout was confirmed.

        Icon fixed at the Pixelize glyph (the default prepared mode)
        rather than swapping with the mode - Windows' own
        btnObfuscate.Image is likewise a single static icon, never
        reassigned anywhere in the source; only obfuscateModeButton's
        icon swaps, which is where this port's dynamic feedback lives
        too now (the style panel's mode-picker button label).

        Returns the (possibly newly-established) group leader, same
        contract as the main loop in _build_tool_palette.
        """
        button = Gtk.RadioButton.new_from_widget(group_leader)
        if group_leader is None:
            group_leader = button
        button.set_mode(False)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_image(obfuscate_icon_image(icon_color))
        button.set_tooltip_text("Obfuscate (O)")
        button.set_active(self.tool in _OBFUSCATE_MODE_ORDER)
        button.connect("toggled", self._on_obfuscate_button_toggled)
        box.pack_start(button, False, False, 0)
        self._obfuscate_button = button
        for mode in _OBFUSCATE_MODE_ORDER:
            self._tool_buttons[mode] = button
        return group_leader

    @staticmethod
    def _obfuscate_mode_label(mode: Tool) -> str:
        return _OBFUSCATE_MODE_LABELS[mode]

    def _build_highlight_control(self, box: Gtk.Box, group_leader, icon_color) -> Gtk.RadioButton:
        """The single "Highlight" palette entry - mirrors
        _build_obfuscate_control exactly, see its own docstring for
        the full reasoning (same real-Windows layout: highlightModeButton
        lives in propertiesToolStrip, not attached to btnHighlight).
        """
        button = Gtk.RadioButton.new_from_widget(group_leader)
        if group_leader is None:
            group_leader = button
        button.set_mode(False)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_image(highlight_icon_image(icon_color))
        button.set_tooltip_text("Highlight (H)")
        button.set_active(self.tool in _HIGHLIGHT_MODE_ORDER)
        button.connect("toggled", self._on_highlight_button_toggled)
        box.pack_start(button, False, False, 0)
        self._highlight_button = button
        for mode in _HIGHLIGHT_MODE_ORDER:
            self._tool_buttons[mode] = button
        return group_leader

    @staticmethod
    def _highlight_mode_label(mode: Tool) -> str:
        return _HIGHLIGHT_MODE_LABELS[mode]

    def _build_obfuscate_mode_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        self._obfuscate_mode_items = {}
        item_group_leader = None
        for mode in _OBFUSCATE_MODE_ORDER:
            label = f"{_OBFUSCATE_MODE_LABELS[mode]} ({_OBFUSCATE_MODE_SECURITY_SUFFIX[mode]})"
            item = Gtk.RadioMenuItem.new_with_label_from_widget(item_group_leader, label)
            if item_group_leader is None:
                item_group_leader = item
            item.set_active(mode is self._default_obfuscate_mode)
            item.set_tooltip_text(_OBFUSCATE_MODE_TOOLTIPS[mode])
            item.connect("toggled", self._on_obfuscate_mode_item_toggled, mode)
            menu.append(item)
            self._obfuscate_mode_items[mode] = item
        menu.show_all()
        return menu

    def _on_obfuscate_button_toggled(self, button: Gtk.RadioButton) -> None:
        if button.get_active():
            self.tool = self._default_obfuscate_mode
            self._refresh_style_panel()

    def _on_obfuscate_mode_item_toggled(self, item: Gtk.RadioMenuItem, mode: Tool) -> None:
        if item.get_active():
            self._set_obfuscate_mode(mode)

    def _set_obfuscate_mode(self, mode: Tool) -> None:
        """Changes which filter Obfuscate will use next - does NOT
        activate the tool. Faithful to the real Windows editor: the
        mode dropdown (obfuscateModeButton) is bidirectionally bound
        only to the prepared-filter value (ImageEditorForm.cs:1366,
        `new BidirectionalBinding(obfuscateModeButton, "SelectedTag",
        ..., "Value")`), and BindableToolStripDropDownButton.
        OnDropDownItemClicked just swaps its own tag/icon - neither
        ever touches DrawingMode. Only the main button (or, in this
        port, a keyboard shortcut - see _select_and_activate_
        obfuscate_mode) actually starts drawing.

        A selected ObfuscateShape's own mode is retroactively updated
        too, the same way every other style-panel control already
        restyles the current selection (_apply_style_change,
        _on_obfuscate_amount_changed) - matches Windows' FieldAggregator,
        which reads and writes back through the *selected* element's
        own field when there is one, not just a "next new shape"
        preference (missed when this control was first split out;
        the amount spinner already did this correctly).

        If Obfuscate is *also* already the active tool, self.tool is
        kept in sync with the new mode too - independently of the
        shape-retroactive-update above, not as an alternative to it.
        Originally these were mutually exclusive (an if/elif), on the
        assumption that "something's selected" and "Obfuscate is the
        active drawing tool" couldn't both matter at once - but they
        very much can: drawing a shape leaves it selected, so picking
        a new mode from the dropdown right after finishing a drag hits
        exactly this case. Without also updating self.tool here, it
        stays pointed at the *old* mode, and the very next shape drawn
        - without first explicitly reactivating Obfuscate - silently
        uses that stale mode instead of the one just picked. Reported
        live by testing the identical pattern while building Highlight
        (task #88, same shared logic) - confirmed this already-shipped
        Obfuscate code had the same bug, just never exercised in quite
        this sequence before.
        """
        self._default_obfuscate_mode = mode
        self._obfuscate_mode_button.set_label(self._obfuscate_mode_label(mode))
        if not self._obfuscate_mode_items[mode].get_active():
            self._obfuscate_mode_items[mode].set_active(True)

        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            obfuscate_mode = _TOOL_TO_OBFUSCATE_MODE[mode]
            updated = dataclass_replace(shape, mode=obfuscate_mode)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated  # setter already calls _refresh_style_panel
            self._drawing_area.queue_draw()
        if self.tool in _OBFUSCATE_MODE_ORDER:
            self.tool = mode
            self._refresh_style_panel()
            self._drawing_area.queue_draw()

    def _activate_obfuscate_tool(self) -> None:
        """What clicking the main Obfuscate button does - starts
        drawing with whichever mode is currently prepared
        (self._default_obfuscate_mode). Mirrors BtnObfuscateClick
        (ImageEditorForm.cs) exactly: only this (never the mode
        dropdown - see _set_obfuscate_mode) changes DrawingMode.
        """
        if self._obfuscate_button.get_active():
            # Already the active tool - "toggled" won't refire (GTK
            # only emits it on an actual state change), so do directly
            # what _on_obfuscate_button_toggled would have.
            self.tool = self._default_obfuscate_mode
            self._refresh_style_panel()
        else:
            self._obfuscate_button.set_active(True)  # fires "toggled" -> _on_obfuscate_button_toggled

    def _build_highlight_mode_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        self._highlight_mode_items = {}
        item_group_leader = None
        for mode in _HIGHLIGHT_MODE_ORDER:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(item_group_leader, _HIGHLIGHT_MODE_LABELS[mode])
            if item_group_leader is None:
                item_group_leader = item
            item.set_active(mode is self._default_highlight_mode)
            item.connect("toggled", self._on_highlight_mode_item_toggled, mode)
            menu.append(item)
            self._highlight_mode_items[mode] = item
        menu.show_all()
        return menu

    def _on_highlight_button_toggled(self, button: Gtk.RadioButton) -> None:
        if button.get_active():
            self.tool = self._default_highlight_mode
            self._refresh_style_panel()

    def _on_highlight_mode_item_toggled(self, item: Gtk.RadioMenuItem, mode: Tool) -> None:
        if item.get_active():
            self._set_highlight_mode(mode)

    def _set_highlight_mode(self, mode: Tool) -> None:
        """Changes which filter Highlight will use next - mirrors
        _set_obfuscate_mode exactly, see its own docstring for the
        full reasoning (does not activate the tool; retroactively
        updates a selected HighlightShape's own mode; live-updates
        the style panel if Highlight is already the active tool).
        """
        self._default_highlight_mode = mode
        self._highlight_mode_button.set_label(self._highlight_mode_label(mode))
        if not self._highlight_mode_items[mode].get_active():
            self._highlight_mode_items[mode].set_active(True)

        shape = self.selected_shape
        if isinstance(shape, HighlightShape):
            highlight_mode = _TOOL_TO_HIGHLIGHT_MODE[mode]
            updated = dataclass_replace(shape, mode=highlight_mode)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated  # setter already calls _refresh_style_panel
            self._drawing_area.queue_draw()
        # Not an elif - see _set_obfuscate_mode's own docstring for why
        # this needs to run independently of the retroactive-shape-
        # update above, not as an alternative to it.
        if self.tool in _HIGHLIGHT_MODE_ORDER:
            self.tool = mode
            self._refresh_style_panel()
            self._drawing_area.queue_draw()

    def _activate_highlight_tool(self) -> None:
        """What clicking the main Highlight button does - mirrors
        _activate_obfuscate_tool exactly, see its own docstring.
        """
        if self._highlight_button.get_active():
            self.tool = self._default_highlight_mode
            self._refresh_style_panel()
        else:
            self._highlight_button.set_active(True)  # fires "toggled" -> _on_highlight_button_toggled

    def _build_crop_control(self, box: Gtk.Box, group_leader, icon_color) -> Gtk.RadioButton:
        """The single "Crop" palette entry - mirrors _build_highlight_
        control's shape exactly (one button standing in for three Tool
        values, real cropModeButton lives in propertiesToolStrip, not
        attached to btnCrop) - but Crop never creates a Shape, so
        there's no shape.mode field to retroactively update in
        _set_crop_mode below, unlike Highlight/Obfuscate.
        """
        button = Gtk.RadioButton.new_from_widget(group_leader)
        if group_leader is None:
            group_leader = button
        button.set_mode(False)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_image(crop_icon_image(icon_color))
        button.set_tooltip_text("Crop (C)")
        button.set_active(self.tool in _CROP_MODE_ORDER)
        button.connect("toggled", self._on_crop_button_toggled)
        box.pack_start(button, False, False, 0)
        self._crop_button = button
        for mode in _CROP_MODE_ORDER:
            self._tool_buttons[mode] = button
        return group_leader

    def _build_crop_mode_menu(self) -> Gtk.Menu:
        """Real Windows dropdown order (cropModeButton.DropDownItems,
        ImageEditorForm.Designer.cs:1143-1145): Default, Vertical,
        Horizontal, then Auto. A brief port-local rename to "Follow
        Border" was tried and reverted (user's own call: the rename
        didn't reduce confusion enough to be worth diverging from
        Windows' own label) - back to the real Windows name. The first
        three are mutually exclusive persistent modes (RadioMenuItems,
        like Highlight/Obfuscate's own mode dropdowns); Auto is a plain
        one-shot trigger item, not part of that radio group - see
        _do_auto_crop's own docstring for why it isn't a fourth
        _CROP_MODE_ORDER entry.
        """
        menu = Gtk.Menu()
        self._crop_mode_items = {}
        item_group_leader = None
        for mode in _CROP_MODE_ORDER:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(item_group_leader, _CROP_MODE_LABELS[mode])
            if item_group_leader is None:
                item_group_leader = item
            item.set_active(mode is self._default_crop_mode)
            item.connect("toggled", self._on_crop_mode_item_toggled, mode)
            menu.append(item)
            self._crop_mode_items[mode] = item
        auto_item = Gtk.MenuItem(label="Auto")
        auto_item.connect("activate", lambda _i: self._do_auto_crop())
        menu.append(auto_item)
        menu.show_all()
        return menu

    def _on_crop_button_toggled(self, button: Gtk.RadioButton) -> None:
        if button.get_active():
            self.tool = self._default_crop_mode
            self._refresh_style_panel()

    def _on_crop_mode_item_toggled(self, item: Gtk.RadioMenuItem, mode: Tool) -> None:
        if item.get_active():
            self._set_crop_mode(mode)

    def _set_crop_mode(self, mode: Tool) -> None:
        """Changes which crop mode is prepared next. Discards any
        in-progress crop selection - faithful to Windows' own
        InitCropMode (ImageEditorForm.cs:1674-1696), which always calls
        Surface.RemoveCropContainer() before re-entering crop mode on
        every mode change, not just some of them (AutoCrop is the one
        exception, and even that only reuses the *old* selection's
        bounds as a search hint for the new auto-detected one, not by
        keeping the container itself - see _do_auto_crop).
        """
        self._default_crop_mode = mode
        self._crop_mode_button.set_label(_CROP_MODE_LABELS[mode])
        if not self._crop_mode_items[mode].get_active():
            self._crop_mode_items[mode].set_active(True)
        self._crop_selection = None
        self._crop_resize_handle = None
        if self.tool in _CROP_MODE_ORDER:
            self.tool = mode
            self._refresh_style_panel()
        self._drawing_area.queue_draw()

    def _activate_crop_tool(self) -> None:
        """What clicking the main Crop button does - mirrors
        _activate_highlight_tool exactly.
        """
        if self._crop_button.get_active():
            self.tool = self._default_crop_mode
            self._refresh_style_panel()
        else:
            self._crop_button.set_active(True)  # fires "toggled" -> _on_crop_button_toggled

    def _do_auto_crop(self) -> None:
        """The Mode dropdown's "Auto" item - a one-time seed action,
        not a persistent mode (Windows' own CropModes.AutoCrop is
        handled the same way: InitCropMode calls
        Surface.AutoCrop(), which auto-detects a rect and creates a
        *Default*-mode CropContainer already sized to it, rather than
        tracking "AutoCrop" as an ongoing UI state anywhere). If no
        crop is possible (autocrop_rect finds nothing to trim), Windows
        falls back to plain empty Default mode with a status message
        (editor_autocrop_not_possible) - matched here by just staying
        in empty Default mode, since this port has no toolbar status-
        message mechanism to route real text through.
        """
        self._default_crop_mode = Tool.CROP_DEFAULT
        self._crop_mode_button.set_label(_CROP_MODE_LABELS[Tool.CROP_DEFAULT])
        if not self._crop_mode_items[Tool.CROP_DEFAULT].get_active():
            self._crop_mode_items[Tool.CROP_DEFAULT].set_active(True)
        rect = autocrop_rect(self._base_image)
        self._crop_selection = rect
        self._crop_resize_handle = None
        self.tool = Tool.CROP_DEFAULT
        if not self._crop_button.get_active():
            self._crop_button.set_active(True)
        self._refresh_style_panel()
        self._drawing_area.queue_draw()

    def _crop_handles(self, rect: Rect) -> dict:
        """The resize handles for the in-progress crop selection - 4
        corners for Default mode (CreateDefaultAdorners), or 2 edge
        handles for Vertical/Horizontal (CreateLeftRightAdorners/
        CreateTopBottomAdorners, CropContainer.cs) - only the axis that
        mode's own drag actually varies gets a handle, matching the
        real adorner sets exactly.
        """
        if self.tool is Tool.CROP_VERTICAL:
            mid_y = (rect.top + rect.bottom) // 2
            return {"left": (rect.left, mid_y), "right": (rect.right, mid_y)}
        if self.tool is Tool.CROP_HORIZONTAL:
            mid_x = (rect.left + rect.right) // 2
            return {"top": (mid_x, rect.top), "bottom": (mid_x, rect.bottom)}
        return {
            "top_left": (rect.left, rect.top), "top_right": (rect.right, rect.top),
            "bottom_left": (rect.left, rect.bottom), "bottom_right": (rect.right, rect.bottom),
        }

    def _crop_handle_at(self, rect: Rect, x: int, y: int, margin: int = 6) -> str | None:
        for name, (hx, hy) in self._crop_handles(rect).items():
            if abs(x - hx) <= margin and abs(y - hy) <= margin:
                return name
        return None

    @staticmethod
    def _resize_crop_rect(rect: Rect, handle: str, x: int, y: int) -> Rect:
        """Not a reuse of core/tools.py's own _resized_rect (same
        "top"/"bottom"/"left"/"right" substring-matching idea, small
        enough to duplicate here rather than exporting a private
        helper across modules for one caller).
        """
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        if "top" in handle:
            top = y
        if "bottom" in handle:
            bottom = y
        if "left" in handle:
            left = x
        if "right" in handle:
            right = x
        return Rect.from_points(left, top, right, bottom)

    def _crop_selection_from_drag(self, origin, x: int, y: int) -> Rect:
        """The in-progress selection rect for a drag from ``origin`` to
        (x, y) - Default mode is a normal from_points rect; Vertical/
        Horizontal force the perpendicular axis to the full image
        extent with the *other* axis anchored at the drag's own
        origin, faithfully matching CropContainer.HandleMouseDown's
        (0, y)/(x, 0)-forcing override plus HandleMouseMove's own
        Left=0,Width=image.Width / Top=0,Height=image.Height forcing
        (CropContainer.cs) - not a guess, both read directly from the
        real source.
        """
        img_h, img_w = self._base_image.shape[:2]
        if self.tool is Tool.CROP_VERTICAL:
            return Rect.from_points(origin[0], 0, x, img_h)
        if self.tool is Tool.CROP_HORIZONTAL:
            return Rect.from_points(0, origin[1], img_w, y)
        return Rect.from_points(origin[0], origin[1], x, y)

    def _confirm_crop(self) -> None:
        """What clicking the style panel's Confirm button does -
        faithful port of Surface.ConfirmCrop(true) (Surface.cs:2193-
        2210): dispatches to the right core/crop.py transform by mode,
        then applies it the same way every other whole-image effect
        does (_apply_background_effect - shared BackgroundChangeMemento
        undo path, canvas/window resize, element repositioning all
        "for free"). The element-repositioning offset for Vertical/
        Horizontal deliberately matches Windows' own single *global*
        translate (ApplyVerticalCrop/ApplyHorizontalCrop, Surface.cs)
        rather than a smarter per-element left-of-band-stays-put
        conditional - Windows itself doesn't do that either, so this
        isn't a simplification, it's the faithful behavior (elements
        that were left of/above a removed band shift too, same as
        elements that were right of/below it).
        """
        if self._crop_selection is None:
            return
        rect = self._crop_selection
        if self.tool is Tool.CROP_VERTICAL:
            new_image = crop_out_vertical_strip(self._base_image, rect)
            transform = lambda s: translate_shape(s, -rect.right, 0)  # noqa: E731
        elif self.tool is Tool.CROP_HORIZONTAL:
            new_image = crop_out_horizontal_strip(self._base_image, rect)
            transform = lambda s: translate_shape(s, 0, -rect.bottom)  # noqa: E731
        else:
            new_image = crop_to_rect(self._base_image, rect)
            transform = lambda s: translate_shape(s, -rect.left, -rect.top)  # noqa: E731
        self._crop_selection = None
        self._crop_resize_handle = None
        self._apply_background_effect(new_image, transform=transform)
        self._refresh_style_panel()

    def _cancel_crop(self) -> None:
        """What clicking the style panel's Cancel button (or pressing
        Escape while a crop selection is in progress) does - discards
        the selection without touching the image, matching Windows'
        Surface.ConfirmCrop(false) (just removes the CropContainer, no
        Apply* call).
        """
        self._crop_selection = None
        self._crop_resize_handle = None
        self._refresh_style_panel()
        self._drawing_area.queue_draw()

    def _build_effects_control(self, box: Gtk.Box, icon_color) -> None:
        """The single "Effects" toolbar entry (task #89) - a plain
        dropdown button, not a drawing tool: no Gtk.RadioButton
        membership, never touches self.tool, doesn't take a
        group_leader/return one the way _build_obfuscate_control/
        _build_highlight_control do. Faithful to the real
        toolStripSplitButton1 (ImageEditorForm.Designer.cs,
        LanguageKey="editor_effects"): despite the "SplitButton" class
        name it's actually a GreenshotToolStripDropDownButton, not a
        true split button with separate click-vs-arrow regions - the
        whole control just opens its dropdown, so a plain Gtk.MenuButton
        matches it exactly, no click/toggle state to track.

        Wraps this port's already-working whole-image effect handlers
        (previously only reachable from the Image menu, task #36) plus
        Obfuscate Text (task #100, ui/text_obfuscation_dialog.py) -
        Windows' real 7th dropdown item, gated there behind
        CoreConfiguration.IsBetaTester (see _build_effects_menu's
        docstring) but always available here, since this port has no
        equivalent "beta tester" concept to gate it behind and the
        feature is fully implemented, not experimental.
        """
        button = Gtk.MenuButton()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_image(effects_icon_image(icon_color))
        button.set_tooltip_text("Effects")
        button.set_popup(self._build_effects_menu())
        box.pack_start(button, False, False, 0)
        self._effects_button = button

    def _build_effects_menu(self) -> Gtk.Menu:
        """Real Windows dropdown order (toolStripSplitButton1.
        DropDownItems, ImageEditorForm.Designer.cs:491-499): Add
        Border, Add Drop Shadow, Torn Edges, Grayscale, Invert, Remove
        Transparency, Obfuscate Text. Drop Shadow/Torn Edge each get
        *two* entries here (an instant-apply one plus a "...Settings"
        one) rather than Windows' single item with a left-click-vs-
        right-click(MouseUp) distinction - this port already made that
        same menu-vs-toolbar-widget tradeoff when these lived in the
        Image menu (task #36), and a GTK dropdown menu item has the
        identical no-right-click-affordance limitation a menu bar item
        does.

        Task #101's item-count discrepancy (7 declared in the Designer
        vs. 5 actually seen in a typical run) turned out to be two
        separate runtime Visible gates, not a missing/extra feature:
        - obfuscateTextToolStripMenuItem.Visible = CoreConfiguration.
          IsBetaTester (ImageEditorForm.cs:308) - off by default there.
          No equivalent "beta tester" concept exists in this port, so
          Obfuscate Text (task #100) is always shown here rather than
          gated behind reproducing IsBetaTester as a new setting just
          for this one item.
        - removeTransparencyToolStripMenuItem.Visible = Image.
          IsAlphaPixelFormat(_surface.Image.PixelFormat) (ImageEditor
          Form.cs:1476, refreshed from RefreshEditorControls on every
          selection/undo/image change) - ported below via
          _refresh_remove_transparency_visibility, called from the
          base_image setter (this port's own single "image changed"
          choke point, already used for the resize-on-load and
          dimensions-label updates). Windows checks the pixel *format*
          (does this format carry an alpha channel at all); this port's
          images are always physically RGBA regardless of origin, so
          the faithful equivalent is content-based - any pixel actually
          translucent - matching remove_transparency_image's own
          docstring ("only applies if there's alpha to remove in the
          source; this function is unconditional, callers check"),
          which had never had a caller do that checking until now.
        """
        menu = Gtk.Menu()

        def add_item(label: str, handler) -> Gtk.MenuItem:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i: handler())
            menu.append(item)
            return item

        add_item("Add Border", self._do_border)
        add_item("Add Drop Shadow", self._do_drop_shadow)
        add_item("Drop Shadow Settings...", self._do_drop_shadow_settings)
        add_item("Torn Edges", self._do_torn_edge)
        add_item("Torn Edge Settings...", self._do_torn_edge_settings)
        add_item("Grayscale", self._do_grayscale)
        add_item("Invert", self._do_invert)
        self._remove_transparency_item = add_item("Remove Transparency...", self._do_remove_transparency)
        # "Find & Redact Text...", not Windows' own "Obfuscate Text" -
        # see ui/text_obfuscation_dialog.py's module docstring for why
        # (collides with the separate manual Obfuscate tool, and
        # "Obfuscate" undersells the Highlight-based effect choices).
        add_item("Find & Redact Text...", self._do_obfuscate_text)
        menu.show_all()
        self._refresh_remove_transparency_visibility()
        return menu

    def _refresh_remove_transparency_visibility(self) -> None:
        """See _build_effects_menu's docstring - faithful port of
        ImageEditorForm.cs:1473-1477's Visible gate, content-based
        rather than format-based since this port's images are always
        RGBA.
        """
        has_transparency = bool((self._base_image[:, :, 3] < 255).any())
        self._remove_transparency_item.set_visible(has_transparency)

    def _build_action_button(self, box: Gtk.Box, image: Gtk.Image, tooltip: str, handler) -> None:
        """A plain one-shot toolbar icon button (task #90's Rotate CW/
        Rotate CCW/Resize) - not a drawing tool (no RadioButton
        membership, no self.tool involvement) and not a dropdown (no
        popup menu, unlike _build_effects_control) - just click-to-
        run, matching Windows' own separate rotateCwToolstripButton/
        rotateCcwToolstripButton/btnResize rather than a grouped
        split-button.
        """
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_image(image)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda _b: handler())
        box.pack_start(button, False, False, 0)

    def _build_action_toolbar(self) -> Gtk.Toolbar:
        """Matches the real Windows order (confirmed from
        ImageEditorForm.Designer.cs's destinationsToolStrip.Items):
        Save, Copy(image), Print | Delete | Cut, Copy(shape), Paste,
        Undo, Redo | Settings | Help - with one addition of our own,
        an external-editor button, placed after Settings since Windows
        has nothing there to anchor a "correct" position for it.
        """
        toolbar = Gtk.Toolbar()
        toolbar.set_style(Gtk.ToolbarStyle.ICONS)

        def add_button(icon_name: str, tooltip: str, handler) -> Gtk.ToolButton:
            button = Gtk.ToolButton(icon_widget=Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.SMALL_TOOLBAR))
            button.set_tooltip_text(tooltip)
            button.connect("clicked", lambda _b: handler())
            toolbar.insert(button, -1)
            return button

        add_button("document-save-symbolic", "Save (Ctrl+S)", self._do_save)
        add_button("edit-copy-symbolic", "Copy Image to Clipboard (Ctrl+C)", self._do_copy)
        add_button("document-print-symbolic", "Print (Ctrl+P)", self._do_print)

        toolbar.insert(Gtk.SeparatorToolItem(), -1)
        add_button("edit-delete-symbolic", "Delete (Del)", self._do_delete)

        toolbar.insert(Gtk.SeparatorToolItem(), -1)
        add_button("edit-cut-symbolic", "Cut", self._do_cut_shape)
        add_button("edit-copy-symbolic", "Copy Shape", self._do_copy_shape)
        add_button("edit-paste-symbolic", "Paste Shape", self._do_paste_shape)
        add_button("edit-undo-symbolic", "Undo (Ctrl+Z)", self._do_undo)
        add_button("edit-redo-symbolic", "Redo (Ctrl+Y)", self._do_redo)

        toolbar.insert(Gtk.SeparatorToolItem(), -1)
        add_button("preferences-system-symbolic", "Preferences", self._do_show_settings)
        add_button("applications-graphics-symbolic", "Open in External Editor", self._do_open_in_external_editor)

        toolbar.insert(Gtk.SeparatorToolItem(), -1)
        add_button("help-about-symbolic", "Help", self._do_show_help)

        return toolbar

    def _build_color_button(self, get_color, on_picked):
        """A small button showing ``get_color()`` as a solid swatch,
        opening the Greenshot-style color dialog (ui/color_dialog.py)
        on click - faithful port of ToolStripColorButton
        (Greenshot.Editor.Controls.ToolStripColorButton.cs:76-96),
        which opens the same custom palette dialog for both line-color
        and fill-color - replaces the plain Gtk.ColorButton (a generic
        system color dialog) this used to open. Returns (button,
        swatch) - the swatch is exposed so callers can queue_draw() it
        after a color change from elsewhere.
        """
        button = Gtk.Button()
        swatch = Gtk.DrawingArea()
        swatch.set_size_request(24, 16)
        button.add(swatch)

        def on_draw(widget, ctx):
            r, g, b, a = get_color()
            ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
            ctx.paint()
            return False

        swatch.connect("draw", on_draw)

        def on_clicked(_button):
            picked = show_color_picker(self, get_color())
            if picked is not None:
                on_picked(picked)
                swatch.queue_draw()

        button.connect("clicked", on_clicked)
        return button, swatch

    def _build_highlight_fill_button(self, get_color, on_picked):
        """Highlight's own restricted Fill swatch (task #106) - same
        (button, swatch) contract as _build_color_button above, but
        opens a small fixed-choice popup (_HIGHLIGHT_FILL_COLORS)
        instead of the arbitrary Greenshot-style palette dialog every
        other color field in this panel uses - see that constant's own
        docstring for why.
        """
        button = Gtk.MenuButton()
        swatch = Gtk.DrawingArea()
        swatch.set_size_request(24, 16)
        button.add(swatch)

        def on_draw(widget, ctx):
            r, g, b, a = get_color()
            ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
            ctx.paint()
            return False

        swatch.connect("draw", on_draw)

        menu = Gtk.Menu()
        for name, color in _HIGHLIGHT_FILL_COLORS:
            item = Gtk.MenuItem()
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            item_swatch = Gtk.DrawingArea()
            item_swatch.set_size_request(16, 16)
            r, g, b, a = color

            def on_item_draw(widget, ctx, r=r, g=g, b=b, a=a):
                ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
                ctx.paint()
                return False

            item_swatch.connect("draw", on_item_draw)
            row.pack_start(item_swatch, False, False, 0)
            row.pack_start(Gtk.Label(label=name), False, False, 0)
            item.add(row)

            def on_activate(_item, color=color):
                on_picked(color)
                swatch.queue_draw()

            item.connect("activate", on_activate)
            menu.append(item)
        menu.show_all()
        button.set_popup(menu)
        return button, swatch

    def _build_style_panel(self) -> Gtk.Box:
        """Color/thickness/shadow controls that edit self._active_style()
        (the selected shape's own style, or else the active tool's own
        remembered style - see that property), plus a separate
        obfuscate-amount spinner (blur radius / pixel size) for
        self._default_obfuscate_amount, since ObfuscateShape has no
        style field. Both affect shapes created *after* a change, and
        also retroactively restyle the current selection if it has the
        relevant field.

        Each field's label+control(s) live together in their own
        Gtk.Box "cell", keyed by field name in self._style_field_widgets
        - see _refresh_style_panel, which shows/hides whole cells at
        once based on visible_style_fields (core/tools.py), rather than
        this port's previous always-show-everything panel, and also
        syncs each control's displayed value there.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_border_width(4)
        box.set_size_request(-1, _STYLE_PANEL_MIN_HEIGHT)
        self._style_field_widgets = {}

        def add_cell(field_name: str, *widgets: Gtk.Widget) -> None:
            cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for widget in widgets:
                cell.pack_start(widget, False, False, 0)
            box.pack_start(cell, False, False, 0)
            self._style_field_widgets[field_name] = cell

        line_label = Gtk.Label(label="Line:")
        line_button, self._line_color_swatch = self._build_color_button(
            lambda: self._active_style().line_color, self._on_line_color_changed,
        )
        add_cell(STYLE_FIELD_LINE_COLOR, line_label, line_button)

        fill_label = Gtk.Label(label="Fill:")
        fill_button, self._fill_color_swatch = self._build_color_button(
            lambda: self._active_style().fill_color, self._on_fill_color_changed,
        )
        add_cell(STYLE_FIELD_FILL_COLOR, fill_label, fill_button)

        thickness_label = Gtk.Label(label="Line Thickness:")
        adjustment = Gtk.Adjustment(
            value=self._active_style().line_thickness, lower=0, upper=20, step_increment=1
        )
        self._thickness_spin = Gtk.SpinButton(adjustment=adjustment)
        self._thickness_spin.connect("value-changed", self._on_thickness_changed)
        add_cell(STYLE_FIELD_LINE_THICKNESS, thickness_label, self._thickness_spin)

        self._shadow_check = Gtk.CheckButton(label="Shadow")
        self._shadow_check.set_active(self._active_style().shadow)
        self._shadow_check.connect("toggled", self._on_shadow_toggled)
        add_cell(STYLE_FIELD_SHADOW, self._shadow_check)

        # Only shown while Obfuscate's own fields (mode/amount) are -
        # see _refresh_style_panel. Style fields and obfuscate fields
        # are never visible together (visible_style_fields), so this
        # would otherwise dangle before an empty style-fields cluster.
        self._style_separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(self._style_separator, False, False, 4)

        # Windows' real obfuscateModeButton (the Blur/Pixelize picker)
        # lives here, in propertiesToolStrip, not attached to
        # btnObfuscate in the tools toolbar - see _build_obfuscate_
        # control's docstring for the source citation. Button label
        # text (not an icon) shows the current mode, updated by
        # _set_obfuscate_mode - simpler than swapping an icon glyph
        # and consistent with every other control in this panel being
        # text, not icons (icons are only in the tool palette).
        mode_label = Gtk.Label(label="Mode:")
        self._obfuscate_mode_button = Gtk.MenuButton(label=self._obfuscate_mode_label(self._default_obfuscate_mode))
        self._obfuscate_mode_button.set_popup(self._build_obfuscate_mode_menu())
        add_cell(STYLE_FIELD_OBFUSCATE_MODE, mode_label, self._obfuscate_mode_button)

        # Solid Fill's own color (task #60) - a separate field/cell from
        # STYLE_FIELD_FILL_COLOR above on purpose, since ObfuscateShape
        # has no ShapeStyle to read/write through (see
        # STYLE_FIELD_OBFUSCATE_FILL_COLOR's own comment in
        # core/tools.py). Reuses _build_color_button, the same swatch-
        # button-plus-picker-dialog every other color field in this
        # panel already uses.
        obfuscate_fill_label = Gtk.Label(label="Fill:")
        obfuscate_fill_button, self._obfuscate_fill_swatch = self._build_color_button(
            self._active_obfuscate_fill_color, self._on_obfuscate_fill_color_changed,
        )
        add_cell(STYLE_FIELD_OBFUSCATE_FILL_COLOR, obfuscate_fill_label, obfuscate_fill_button)

        # Solid Fill's own optional preset label (task #60 follow-up) -
        # a fixed preset list, not free text entry, mirroring the Mode
        # dropdown above (Gtk.MenuButton + Gtk.RadioMenuItem group)
        # rather than reusing TextShape's click-to-edit machinery.
        text_label = Gtk.Label(label="Text:")
        self._obfuscate_fill_text_button = Gtk.MenuButton(
            label=self._obfuscate_fill_text_label(self._default_obfuscate_fill_text)
        )
        self._obfuscate_fill_text_button.set_popup(self._build_obfuscate_fill_text_menu())
        add_cell(STYLE_FIELD_OBFUSCATE_FILL_TEXT, text_label, self._obfuscate_fill_text_button)

        text_color_label = Gtk.Label(label="Text Color:")
        text_color_button, self._obfuscate_text_color_swatch = self._build_color_button(
            self._active_obfuscate_text_color, self._on_obfuscate_text_color_changed,
        )
        add_cell(STYLE_FIELD_OBFUSCATE_TEXT_COLOR, text_color_label, text_color_button)

        # Label text swaps with the active tool (see
        # _obfuscate_amount_label_text) - matches Windows' own two
        # separate, mode-specific controls ("Blur radius" for Blur,
        # "Pixel size" for Pixelize - ImageEditorForm.Designer.cs)
        # rather than a single generically-named field for both.
        self._obfuscate_amount_label = Gtk.Label(label=self._obfuscate_amount_label_text(self.tool))
        obfuscate_adjustment = Gtk.Adjustment(
            value=self._default_obfuscate_amount, lower=2, upper=50, step_increment=1
        )
        self._obfuscate_amount_spin = Gtk.SpinButton(adjustment=obfuscate_adjustment)
        self._obfuscate_amount_spin.connect("value-changed", self._on_obfuscate_amount_changed)
        add_cell(STYLE_FIELD_OBFUSCATE_AMOUNT, self._obfuscate_amount_label, self._obfuscate_amount_spin)

        # Highlight's own style-panel cells (task #88) - mirrors
        # Obfuscate's own Mode/Fill cells immediately above exactly,
        # plus its own real Windows controls (blurRadiusUpDown/
        # brightnessUpDown/magnificationFactorUpDown, ImageEditorForm.
        # Designer.cs) that Obfuscate has no equivalent of.
        highlight_mode_label = Gtk.Label(label="Mode:")
        self._highlight_mode_button = Gtk.MenuButton(label=self._highlight_mode_label(self._default_highlight_mode))
        self._highlight_mode_button.set_popup(self._build_highlight_mode_menu())
        add_cell(STYLE_FIELD_HIGHLIGHT_MODE, highlight_mode_label, self._highlight_mode_button)

        highlight_fill_label = Gtk.Label(label="Fill:")
        highlight_fill_button, self._highlight_fill_swatch = self._build_highlight_fill_button(
            self._active_highlight_fill_color, self._on_highlight_fill_color_changed,
        )
        add_cell(STYLE_FIELD_HIGHLIGHT_FILL_COLOR, highlight_fill_label, highlight_fill_button)

        brightness_label = Gtk.Label(label="Brightness:")
        brightness_adjustment = Gtk.Adjustment(
            value=self._default_highlight_brightness, lower=0.0, upper=1.0, step_increment=0.05,
        )
        self._highlight_brightness_spin = Gtk.SpinButton(adjustment=brightness_adjustment, digits=2)
        self._highlight_brightness_spin.connect("value-changed", self._on_highlight_brightness_changed)
        add_cell(STYLE_FIELD_HIGHLIGHT_BRIGHTNESS, brightness_label, self._highlight_brightness_spin)

        blur_radius_label = Gtk.Label(label="Blur Radius:")
        blur_radius_adjustment = Gtk.Adjustment(
            value=self._default_highlight_blur_radius, lower=1, upper=50, step_increment=1,
        )
        self._highlight_blur_radius_spin = Gtk.SpinButton(adjustment=blur_radius_adjustment)
        self._highlight_blur_radius_spin.connect("value-changed", self._on_highlight_blur_radius_changed)
        add_cell(STYLE_FIELD_HIGHLIGHT_BLUR_RADIUS, blur_radius_label, self._highlight_blur_radius_spin)

        # "Amount:" (task #106), not "Magnification:" - redundant with
        # the mode's own name right next to it (paralleling Obfuscate's
        # Pixelize/Blur amount field, already just called "Amount").
        magnification_label = Gtk.Label(label="Amount:")
        magnification_adjustment = Gtk.Adjustment(
            value=self._default_highlight_magnification, lower=2, upper=10, step_increment=1,
        )
        self._highlight_magnification_spin = Gtk.SpinButton(adjustment=magnification_adjustment)
        self._highlight_magnification_spin.connect("value-changed", self._on_highlight_magnification_changed)
        add_cell(STYLE_FIELD_HIGHLIGHT_MAGNIFICATION, magnification_label, self._highlight_magnification_spin)

        # Crop's own Mode cell (task #91) - mirrors Obfuscate/Highlight's
        # own Mode dropdowns exactly (real cropModeButton also lives in
        # propertiesToolStrip, not attached to btnCrop).
        crop_mode_label = Gtk.Label(label="Mode:")
        self._crop_mode_button = Gtk.MenuButton(label=_CROP_MODE_LABELS[self._default_crop_mode])
        self._crop_mode_button.set_popup(self._build_crop_mode_menu())
        add_cell(STYLE_FIELD_CROP_MODE, crop_mode_label, self._crop_mode_button)

        # Confirm/Cancel - not a STYLE_FIELD cell like everything else
        # above: Windows shows btnConfirm/btnCancel for *any*
        # CONFIRMABLE selection (ImageEditorForm.cs:1399,
        # `props.HasFieldValue(FieldType.FLAGS) &&
        # ...HasFlag(FieldFlag.CONFIRMABLE)`), driven by whether a crop
        # selection actually exists right now, not by which tool is
        # active - visible_style_fields has no equivalent concept, so
        # this cell's own visibility is set directly in
        # _refresh_style_panel instead of through the generic
        # field_name/visible_fields loop.
        # Icon buttons, not text labels - matches the real
        # btnConfirm/btnCancel's own appearance (a checkmark and a
        # "no entry" circle-with-a-line-through-it, confirmed by the
        # user comparing side-by-side with the real app) more closely
        # than a text label would. Standard freedesktop theme icons,
        # same convention _build_action_toolbar already uses for the
        # generic Save/Copy/Print/etc buttons, not hand-drawn Cairo
        # icons - Confirm/Cancel are generic actions, not tools.
        self._crop_confirm_cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        confirm_button = Gtk.Button()
        confirm_button.set_image(Gtk.Image.new_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.BUTTON))
        confirm_button.set_tooltip_text("Confirm")
        confirm_button.connect("clicked", lambda _b: self._confirm_crop())
        cancel_button = Gtk.Button()
        cancel_button.set_image(Gtk.Image.new_from_icon_name("action-unavailable-symbolic", Gtk.IconSize.BUTTON))
        cancel_button.set_tooltip_text("Cancel (Esc)")
        cancel_button.connect("clicked", lambda _b: self._cancel_crop())
        self._crop_confirm_cell.pack_start(confirm_button, False, False, 0)
        self._crop_confirm_cell.pack_start(cancel_button, False, False, 0)
        box.pack_start(self._crop_confirm_cell, False, False, 0)

        self._refresh_style_panel()
        return box

    @staticmethod
    def _obfuscate_amount_label_text(tool: Tool) -> str:
        if tool is Tool.BLUR:
            return "Blur Radius:"
        if tool is Tool.PIXELIZE:
            return "Pixel Size:"
        return "Amount:"

    def _on_obfuscate_amount_changed(self, spin: Gtk.SpinButton) -> None:
        amount = spin.get_value_as_int()
        self._default_obfuscate_amount = amount
        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            updated = dataclass_replace(shape, amount=amount)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    def _active_obfuscate_fill_color(self):
        """The Fill: swatch's own get_color() - the *selected*
        ObfuscateShape's own fill_color when there is one, else the
        remembered default for the next Solid Fill shape. Mirrors
        _active_style() for shapes that do have a ShapeStyle.
        """
        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            return shape.fill_color
        return self._default_obfuscate_fill_color

    def _on_obfuscate_fill_color_changed(self, color) -> None:
        self._default_obfuscate_fill_color = color
        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            updated = dataclass_replace(shape, fill_color=color)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    def _active_highlight_fill_color(self):
        """Mirrors _active_obfuscate_fill_color exactly, for
        Text Highlight's own Fill: swatch instead of Solid Fill's.
        """
        shape = self.selected_shape
        if isinstance(shape, HighlightShape):
            return shape.fill_color
        return self._default_highlight_fill_color

    def _on_highlight_fill_color_changed(self, color) -> None:
        self._default_highlight_fill_color = color
        shape = self.selected_shape
        if isinstance(shape, HighlightShape):
            updated = dataclass_replace(shape, fill_color=color)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    def _on_highlight_brightness_changed(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_style_panel:
            return
        brightness = spin.get_value()
        self._default_highlight_brightness = brightness
        shape = self.selected_shape
        if isinstance(shape, HighlightShape):
            updated = dataclass_replace(shape, brightness=brightness)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    def _on_highlight_blur_radius_changed(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_style_panel:
            return
        blur_radius = spin.get_value_as_int()
        self._default_highlight_blur_radius = blur_radius
        shape = self.selected_shape
        if isinstance(shape, HighlightShape):
            updated = dataclass_replace(shape, blur_radius=blur_radius)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    def _on_highlight_magnification_changed(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_style_panel:
            return
        magnification = spin.get_value_as_int()
        self._default_highlight_magnification = magnification
        shape = self.selected_shape
        if isinstance(shape, HighlightShape):
            updated = dataclass_replace(shape, magnification_factor=magnification)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    @staticmethod
    def _obfuscate_fill_text_label(text: str) -> str:
        return _OBFUSCATE_FILL_TEXT_LABELS[text]

    def _build_obfuscate_fill_text_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        self._obfuscate_fill_text_items = {}
        item_group_leader = None
        for preset in _OBFUSCATE_FILL_TEXT_PRESETS:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(
                item_group_leader, _OBFUSCATE_FILL_TEXT_LABELS[preset]
            )
            if item_group_leader is None:
                item_group_leader = item
            item.set_active(preset == self._default_obfuscate_fill_text)
            item.connect("toggled", self._on_obfuscate_fill_text_item_toggled, preset)
            menu.append(item)
            self._obfuscate_fill_text_items[preset] = item
        menu.show_all()
        return menu

    def _on_obfuscate_fill_text_item_toggled(self, item: Gtk.RadioMenuItem, preset: str) -> None:
        if item.get_active():
            self._set_obfuscate_fill_text(preset)

    def _set_obfuscate_fill_text(self, text: str) -> None:
        """Mirrors _set_obfuscate_mode: updates the remembered default
        for the next Solid Fill shape, and retroactively updates the
        selected shape too when there is one, the same as every other
        style-panel control.
        """
        self._default_obfuscate_fill_text = text
        self._obfuscate_fill_text_button.set_label(self._obfuscate_fill_text_label(text))
        if not self._obfuscate_fill_text_items[text].get_active():
            self._obfuscate_fill_text_items[text].set_active(True)

        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            updated = dataclass_replace(shape, fill_text=text)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    def _active_obfuscate_text_color(self):
        """Mirrors _active_obfuscate_fill_color, for the Text Color:
        swatch instead of the Fill: swatch.
        """
        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            return shape.text_color
        return self._default_obfuscate_text_color

    def _on_obfuscate_text_color_changed(self, color) -> None:
        self._default_obfuscate_text_color = color
        shape = self.selected_shape
        if isinstance(shape, ObfuscateShape):
            updated = dataclass_replace(shape, text_color=color)
            self.layer.replace(shape, updated)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=updated))
            self.selected_shape = updated
            self._drawing_area.queue_draw()

    def _apply_style_change(self, updated_style: ShapeStyle) -> None:
        """Style panel changes update the *relevant* tool's own style
        memory (self._tool_styles) - the selected shape's own type if
        one is selected and has a style field (style_key_for_shape;
        everything except Obfuscate/Icon/Cursor/Image/Svg, none of
        which have line/fill styling), else the active tool's. A
        selected shape's type is used rather than the active tool
        because selecting-then-restyling an existing shape normally
        happens with Select active, not that shape's own drawing tool
        - matching EditorConfigurationHelper.UpdateLastFieldValue,
        which keys off the changed field's own owning type either way.
        Also restyles the selection live, via one ElementChangeMemento
        per control change.
        """
        shape = self.selected_shape
        if shape is not None and hasattr(shape, "style"):
            style_key = style_key_for_shape(shape)
            restyled = dataclass_replace(shape, style=updated_style)
            self.layer.replace(shape, restyled)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=restyled))
            self.selected_shape = restyled
            self._drawing_area.queue_draw()
        else:
            style_key = self.tool
        if style_key is not None:
            self._tool_styles[style_key] = updated_style

    def _on_line_color_changed(self, color) -> None:
        self._apply_style_change(dataclass_replace(self._active_style(), line_color=color))

    def _on_fill_color_changed(self, color) -> None:
        self._apply_style_change(dataclass_replace(self._active_style(), fill_color=color))

    def _on_thickness_changed(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_style_panel:
            return
        self._apply_style_change(dataclass_replace(self._active_style(), line_thickness=spin.get_value_as_int()))

    def _on_shadow_toggled(self, check: Gtk.CheckButton) -> None:
        if self._syncing_style_panel:
            return
        self._apply_style_change(dataclass_replace(self._active_style(), shadow=check.get_active()))

    def _on_tool_button_toggled(self, button: Gtk.RadioToolButton, tool: Tool) -> None:
        if button.get_active():
            self.tool = tool
            # Picking a tool from the palette means "draw something new
            # with it", not "keep editing whatever was selected before" -
            # without this, a residual selection (including the
            # auto-inserted cursor shape every editor opens with) shadows
            # the newly-chosen tool's own style fields, since
            # visible_style_fields always prioritizes a selected shape
            # over the active tool. The setter below already calls
            # _refresh_style_panel().
            self.selected_shape = None

    def _do_undo(self) -> None:
        self._commit_text_editing_if_active()
        if self.undo_redo.undo():
            self.selected_shape = None
            self._drawing_area.queue_draw()

    def _do_redo(self) -> None:
        self._commit_text_editing_if_active()
        if self.undo_redo.redo():
            self.selected_shape = None
            self._drawing_area.queue_draw()

    def _do_select_all(self) -> None:
        """Object > Select All (task #125, real Windows'
        SelectAllToolStripMenuItemClick -> Surface.SelectAllElements,
        Surface.cs:2510-2513) - selects every shape on the layer, not
        just one.
        """
        self._commit_text_editing_if_active()
        self._set_selected_shapes(list(self.layer))
        self._drawing_area.queue_draw()

    def _do_delete(self) -> None:
        """Multi-shape aware since task #125 - real Windows'
        RemoveSelectedElements (Surface.cs:2118-2132) removes the
        *whole* selection as one undo step, not just a single element;
        CompositeMemento (already a faithful port of Windows' own
        AddElementsMemento/DeleteElementsMemento batch mementos, just
        never wired to anything before this) gives the same one-undo-
        restores-everything behavior here.
        """
        self._commit_text_editing_if_active()
        shapes = self.selected_shapes
        if not shapes:
            return
        mementos = []
        for shape in shapes:
            self.layer.remove(shape)
            mementos.append(DeleteElementMemento(self.layer, shape))
        self.undo_redo.push(CompositeMemento(mementos) if len(mementos) > 1 else mementos[0])
        self._set_selected_shapes([])
        self._drawing_area.queue_draw()

    def _do_cut_shape(self) -> None:
        self._commit_text_editing_if_active()
        shapes = self.selected_shapes
        if not shapes:
            return
        self._shape_clipboard = shapes
        self._do_delete()

    def _do_copy_shape(self) -> None:
        self._commit_text_editing_if_active()
        shapes = self.selected_shapes
        if not shapes:
            return
        self._shape_clipboard = shapes

    def _do_paste_shape(self) -> None:
        # Pastes the last cut/copied shape(s), not an image from the
        # real system clipboard - Windows' Paste can also embed an
        # image from the system clipboard, but ClipboardBackend here
        # is write-only (set_image), with no read-back support built
        # yet, so that half is out of scope for now.
        self._commit_text_editing_if_active()
        if self._shape_clipboard is None:
            return
        pasted = [translate_shape(shape, 20, 20) for shape in self._shape_clipboard]
        for shape in pasted:
            self.layer.add(shape)
            self.undo_redo.push(AddElementMemento(self.layer, shape))
        self._set_selected_shapes(pasted)
        self._drawing_area.queue_draw()

    def _do_duplicate(self) -> None:
        """Edit > Duplicate (task #95, matches real Windows'
        duplicateToolStripMenuItem/Ctrl+D) - same offset-copy-and-
        select behavior as Paste above, just sourced from the current
        selection directly instead of the shape clipboard, and without
        touching it. Multi-shape aware since task #125 - real Windows'
        DuplicateSelectedElements (Surface.cs:2411-2420) duplicates the
        whole selection, not just one element.
        """
        self._commit_text_editing_if_active()
        shapes = self.selected_shapes
        if not shapes:
            return
        duplicated = [translate_shape(shape, 20, 20) for shape in shapes]
        for shape in duplicated:
            self.layer.add(shape)
            self.undo_redo.push(AddElementMemento(self.layer, shape))
        self._set_selected_shapes(duplicated)
        self._drawing_area.queue_draw()

    def _do_bring_to_front(self) -> None:
        # Deliberately not undoable yet - Layer has no z-order memento
        # type (only Add/Delete/ElementChange exist); reordering is
        # rare enough, and easy enough to reverse manually (Send to
        # Back once), that this is a documented simplification rather
        # than something worth a new memento type for right now.
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        self.layer.bring_to_front([self.selected_shape])
        self._drawing_area.queue_draw()

    def _do_bring_forward(self) -> None:
        """Object > Arrange > Up One Level (task #95) - Layer.
        bring_forward already existed, fully unit tested, just never
        wired to any UI control until now."""
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        self.layer.bring_forward([self.selected_shape])
        self._drawing_area.queue_draw()

    def _do_send_backward(self) -> None:
        """Object > Arrange > Down One Level (task #95) - mirrors
        _do_bring_forward, see its comment."""
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        self.layer.send_backward([self.selected_shape])
        self._drawing_area.queue_draw()

    def _do_send_to_back(self) -> None:
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        self.layer.send_to_back([self.selected_shape])
        self._drawing_area.queue_draw()

    def _do_save_objects(self) -> None:
        """Object > "Save objects to file" (editor_save_objects,
        language-en-US.xml:170) - real Windows' own
        SaveElementsToStream (Surface.cs:729-745), saved via
        SaveFileDialog to a "Greenshot templates (*.gst)" file
        (ImageEditorForm.cs:1598-1611). Not byte-compatible with real
        .gst (JSON via orcshot_format.py, not NRBF - task #123's own
        scope; task #124 is the separate NRBF writer for real
        .greenshot/.gst compatibility), so this uses its own "*.json"
        extension rather than claiming to write a real .gst file.
        """
        self._commit_text_editing_if_active()
        dialog = Gtk.FileChooserDialog(title="Save Objects", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_current_folder(str(get_output_directory()))
        dialog.set_current_name("objects.json")
        dialog.set_do_overwrite_confirmation(True)
        object_filter = Gtk.FileFilter()
        object_filter.set_name("Orcshot objects")
        object_filter.add_pattern("*.json")
        dialog.add_filter(object_filter)
        try:
            if dialog.run() == Gtk.ResponseType.OK:
                path = Path(dialog.get_filename())
                if path.suffix.lower() != ".json":
                    path = path.with_suffix(".json")
                save_objects_file(self.layer, path)
        finally:
            dialog.destroy()

    def _do_load_objects(self) -> None:
        """Object > "Load objects from file" (editor_load_objects,
        language-en-US.xml:131) - mirrors _do_save_objects above. Real
        Windows' LoadElementsFromStream (Surface.cs:751-764) *adds* the
        loaded elements onto the existing surface rather than replacing
        it (DeselectAllElements then AddElements), which this matches -
        each loaded shape becomes its own AddElementMemento (the only
        add-memento this port has; no bulk-load memento type exists,
        so undoing a multi-shape load takes multiple undos) and the
        last one loaded becomes the selection, standing in for real
        Windows' SelectElements(loadedElements) multi-select (this
        port only tracks one selected shape today - task #125).
        Accepts either a Save Objects file or a full .orcshot file
        (image discarded) - load_objects_file's own documented
        behavior.
        """
        self._commit_text_editing_if_active()
        dialog = Gtk.FileChooserDialog(title="Load Objects", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        object_filter = Gtk.FileFilter()
        object_filter.set_name("Orcshot objects")
        for pattern in ("*.json", "*.orcshot"):
            object_filter.add_pattern(pattern)
        dialog.add_filter(object_filter)
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            path = dialog.get_filename()
        finally:
            dialog.destroy()

        try:
            loaded_layer = load_objects_file(path)
        except InvalidOrcshotFileError as exc:
            error_dialog = Gtk.MessageDialog(
                transient_for=self, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                text="Couldn't load objects",
            )
            error_dialog.format_secondary_text(str(exc))
            error_dialog.run()
            error_dialog.destroy()
            return

        for shape in loaded_layer:
            self.layer.add(shape)
            self.selected_shape = shape
            self.undo_redo.push(AddElementMemento(self.layer, shape))
        self._drawing_area.queue_draw()

    def _do_open(self) -> None:
        """File > Open... (task #129) - always opens into a brand-new
        EditorWindow rather than replacing this one's document, same
        as every other capture already becomes its own window (task
        #111's "Reuse Editor" setting doesn't exist yet). Shared with
        the file-manager double-click/MIME-open path (app.py's
        do_open) via open_orcshot_file_in_new_window below, so both
        get identical error handling.
        """
        dialog = Gtk.FileChooserDialog(title="Open", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        dialog.set_current_folder(str(get_output_directory()))
        orcshot_filter = Gtk.FileFilter()
        orcshot_filter.set_name("Orcshot files")
        orcshot_filter.add_pattern("*.orcshot")
        dialog.add_filter(orcshot_filter)
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            path = dialog.get_filename()
        finally:
            dialog.destroy()
        open_orcshot_file_in_new_window(path, transient_for=self)

    def _composited_image(self) -> np.ndarray:
        return composite_to_numpy(self._base_image, self.layer)

    def _next_step_number(self) -> int:
        return sum(1 for shape in self.layer if isinstance(shape, StepLabelShape)) + 1

    def _do_copy(self) -> None:
        self._commit_text_editing_if_active()
        self._clipboard.set_image(self._composited_image())

    def _do_save(self) -> bool:
        """Save As... - always dialog-driven, with an explicit "Save as
        type" selector (task #95's Output tab work) rather than relying
        on whatever extension the user happens to type, matching real
        Windows' own SaveImageFileDialog. Returns whether a save
        actually happened - lets _on_delete_event tell a completed save
        apart from a cancelled one, matching ImageEditorFormFormClosing's
        own post-BtnSaveClick `if (_surface.Modified)` check
        (ImageEditorForm.cs:1024-1028).
        """
        self._commit_text_editing_if_active()
        output_settings = get_output_settings()
        dialog = Gtk.FileChooserDialog(
            title="Save Screenshot", transient_for=self, action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        dialog.set_current_folder(str(get_output_directory()))

        format_combo = Gtk.ComboBoxText()
        for value, label in _SAVE_AS_FORMATS:
            format_combo.append(value, label)
        # "orcshot" only here, not in _SAVE_AS_FORMATS - that list is
        # shared with the Output tab's "Primary format" dropdown
        # (quick-save's default raster format), and this isn't a valid
        # choice there. Matches real Windows exactly: its own
        # OutputFileFormat setting's docstring explicitly lists only
        # "bmp, gif, jpg, png, tiff" - "greenshot" is a Save-As-only
        # format on Windows too, never a quick-save default there
        # either (ICoreConfiguration.cs:130-132).
        format_combo.append("orcshot", "Orcshot (with shapes, task #123)")
        format_combo.set_active_id(output_settings.primary_format)
        if format_combo.get_active_id() is None:
            format_combo.set_active_id("png")

        def on_format_changed(combo: Gtk.ComboBoxText) -> None:
            dialog.set_current_name(f"screenshot.{combo.get_active_id()}")

        format_combo.connect("changed", on_format_changed)
        extra = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        extra.pack_start(Gtk.Label(label="Save as type:"), False, False, 0)
        extra.pack_start(format_combo, False, False, 0)
        extra.show_all()
        dialog.set_extra_widget(extra)
        dialog.set_current_name(f"screenshot.{format_combo.get_active_id()}")
        dialog.set_do_overwrite_confirmation(True)

        saved = False
        try:
            if dialog.run() == Gtk.ResponseType.OK:
                output_format = format_combo.get_active_id()
                path = Path(dialog.get_filename())
                if path.suffix.lower().lstrip(".") != output_format:
                    path = path.with_suffix(f".{output_format}")
                if output_format == "orcshot":
                    # The whole point is preserving shapes separately,
                    # re-editable - the flattened _composited_image()
                    # would defeat that, so this uses _base_image (the
                    # raw capture) + self.layer directly, task #123.
                    save_orcshot_file(self._base_image, self.layer, path)
                else:
                    self._maybe_show_quality_dialog(output_format)
                    jpeg_quality = get_output_settings().jpeg_quality
                    save_image_to_file(self._composited_image(), path, jpeg_quality=jpeg_quality)
                self._saved_generation = self.undo_redo.generation
                if output_settings.copy_path_to_clipboard:
                    Gtk.Clipboard.get_default(self.get_display()).set_text(str(path), -1)
                saved = True
        finally:
            dialog.destroy()
        return saved

    def _do_choose_save_location(self) -> None:
        _choose_save_location(self)

    def _do_insert_image(self) -> None:
        """Embeds an image file as a new ImageShape - Windows has no
        dedicated "insert image" toolbar tool (DrawingModes.Bitmap is
        defined but never assigned anywhere in the source); this is
        part of its generic file-import system instead (a
        IFileFormatHandler alongside PNG/JPG/ICO/etc.), so it lives in
        the File menu, not the tool palette. There's no drag gesture
        to size the shape from (this is a file picker, not a
        click-and-drag tool), so it starts at default_insert_bounds'
        placement - centered, scaled down only if larger than the
        canvas - and is then resizable/movable like any other shape
        via the Select tool. GdkPixbuf's own supported-format list
        covers .ico/.cur natively (confirmed live), which is also why
        there's no separate "Icon/stamp" tool here - Windows' own
        IconContainer for that is dead code with no UI path to
        trigger it at all, so nothing was dropped by folding it in.
        """
        self._commit_text_editing_if_active()
        dialog = Gtk.FileChooserDialog(title="Insert Image", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Images")
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.ico", "*.cur", "*.tif", "*.tiff"):
            image_filter.add_pattern(pattern)
        dialog.add_filter(image_filter)
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            path = dialog.get_filename()
        finally:
            dialog.destroy()

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        image = pixbuf_to_numpy(pixbuf)
        img_h, img_w = image.shape[:2]
        base_h, base_w = self._base_image.shape[:2]
        bounds = default_insert_bounds(img_w, img_h, base_w, base_h)
        shape = ImageShape(bounds=bounds, image=image)
        self.layer.add(shape)
        self.selected_shape = shape
        self.undo_redo.push(AddElementMemento(self.layer, shape))
        self._drawing_area.queue_draw()

    def _do_insert_svg(self) -> None:
        """Same idea as _do_insert_image, for SVG - Windows registers
        SVG support as a generic IFileFormatHandler too
        (SvgFileFormatHandler.cs), not a dedicated toolbar tool."""
        self._commit_text_editing_if_active()
        dialog = Gtk.FileChooserDialog(title="Insert SVG", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        svg_filter = Gtk.FileFilter()
        svg_filter.set_name("SVG images")
        svg_filter.add_pattern("*.svg")
        dialog.add_filter(svg_filter)
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            path = dialog.get_filename()
        finally:
            dialog.destroy()

        svg_data = Path(path).read_text()
        handle = Rsvg.Handle.new_from_data(svg_data.encode("utf-8"))
        dimensions = handle.get_dimensions()
        base_h, base_w = self._base_image.shape[:2]
        bounds = default_insert_bounds(dimensions.width, dimensions.height, base_w, base_h)
        shape = SvgShape(bounds=bounds, svg_data=svg_data)
        self.layer.add(shape)
        self.selected_shape = shape
        self.undo_redo.push(AddElementMemento(self.layer, shape))
        self._drawing_area.queue_draw()

    def _do_insert_window(self) -> None:
        """Windows' Insert_window_toolstripmenuitem
        (ImageEditorForm.Designer.cs, last item in the Edit menu after
        a separator) captures another open window and drops it in via
        Surface.AddImageContainer at a fixed natural size
        (ImageEditorForm.cs:1717-1802, Surface.cs:843-854) - populated
        from a hover submenu of window titles built by
        MainForm.AddCaptureWindowMenuItems. This port reuses its own
        click-to-select window-picker overlay instead of building that
        submenu, then places the result the same way _do_insert_image
        does (default_insert_bounds, not a fixed position) so it's
        consistent with every other insert path here. force_plain_overlay
        skips the GNOME-Shell-native fast path since it has no hook to
        hand an image back without going through the destination
        picker - see window_picker.start_window_picker's docstring.
        """
        self._commit_text_editing_if_active()

        def on_captured(image, cursor_shape) -> None:
            img_h, img_w = image.shape[:2]
            base_h, base_w = self._base_image.shape[:2]
            bounds = default_insert_bounds(img_w, img_h, base_w, base_h)
            shape = ImageShape(bounds=bounds, image=image)
            self.layer.add(shape)
            self.selected_shape = shape
            self.undo_redo.push(AddElementMemento(self.layer, shape))
            self._drawing_area.queue_draw()

        from orcshot.ui.window_picker import start_window_picker

        start_window_picker(on_window_captured=on_captured, force_plain_overlay=True, capture_mouse_cursor=False)

    def _do_print(self) -> None:
        self._commit_text_editing_if_active()
        print_image(self._composited_image(), parent=self)

    def _do_show_settings(self) -> None:
        self._commit_text_editing_if_active()
        show_preferences_dialog(self)

    @staticmethod
    def _installed_flatpak_apps() -> set:
        if shutil.which("flatpak") is None:
            return set()
        try:
            result = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application"],
                capture_output=True, text=True, timeout=5, check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _command_for_candidate(self, path_command: str, flatpak_id: str, flatpak_apps: set):
        if shutil.which(path_command):
            return [path_command]
        if flatpak_id in flatpak_apps:
            return ["flatpak", "run", flatpak_id]
        return None

    def _find_external_editor_command(self):
        """The argv prefix to launch an available candidate editor, or
        None if none are installed. Checks a plain PATH executable
        first, then a Flatpak install for the same candidate -
        preferring a live `flatpak list` query over `locate`: `locate`
        depends on the mlocate/plocate package being installed at all,
        and its index can be stale until the next `updatedb` run, so a
        just-installed app might not show up yet; `flatpak list` is
        authoritative and always current.

        Tries settings.get_external_editor_preference()'s choice
        first if it names a specific candidate; falls through to the
        normal Krita-then-GIMP order either way (whether the
        preference is "auto", names a candidate not in
        _EXTERNAL_EDITOR_CANDIDATES, or names one that's no longer
        installed) so an uninstalled preference doesn't leave this
        button permanently broken.
        """
        flatpak_apps = self._installed_flatpak_apps()
        preferred = get_external_editor_preference()
        for name, path_command, flatpak_id in _EXTERNAL_EDITOR_CANDIDATES:
            if name != preferred:
                continue
            command = self._command_for_candidate(path_command, flatpak_id, flatpak_apps)
            if command is not None:
                return command
        for _name, path_command, flatpak_id in _EXTERNAL_EDITOR_CANDIDATES:
            command = self._command_for_candidate(path_command, flatpak_id, flatpak_apps)
            if command is not None:
                return command
        return None

    @staticmethod
    def _external_editor_cache_dir() -> Path:
        """Where the exported temp PNG for "Open in External Editor"
        lives - $XDG_CACHE_HOME/orcshot, *not* system /tmp.

        Confirmed live (`flatpak run org.kde.krita ls /tmp`, an empty
        listing) that a Flatpak sandbox's /tmp is its own private
        tmpfs regardless of the "filesystems=host" permission Krita's
        Flatpak actually has (`flatpak info --show-permissions
        org.kde.krita`) - bubblewrap always isolates /tmp specifically,
        host permission or not. A file this app writes to /tmp is
        therefore invisible inside the sandbox even though it exists
        on the real filesystem, which is exactly the "file does not
        exist" error Krita reported. The home directory, by contrast,
        genuinely is shared (`flatpak run org.kde.krita ls ~` shows
        the real host home) - so $XDG_CACHE_HOME (under home) is used
        instead, matching this project's existing XDG-dir convention
        (settings.config_file_path). Delegates to
        ui/file_export.py's orcshot_cache_dir, the shared
        implementation - ui/external_commands.py's own temp exports
        use the same directory for the same reason.
        """
        return orcshot_cache_dir()

    def _do_open_in_external_editor(self) -> None:
        self._commit_text_editing_if_active()
        command = self._find_external_editor_command()
        if command is None:
            dialog = Gtk.MessageDialog(
                transient_for=self, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                text="No external image editor found",
            )
            names = ", ".join(name for name, _, _ in _EXTERNAL_EDITOR_CANDIDATES)
            dialog.format_secondary_text(f"Tried: {names} (checked both PATH and Flatpak). Install one of these to use this button.")
            dialog.run()
            dialog.destroy()
            return
        # Cleans up the previous export before writing a new one -
        # unique filenames (not one fixed path) avoid a second export
        # clobbering a file a still-open first editor session has
        # already loaded; deleting the old one here (rather than never
        # cleaning up) avoids that pile growing unbounded across a long
        # editing session, since ~/.cache/orcshot isn't
        # OS-managed transient storage the way /tmp is.
        previous = getattr(self, "_external_editor_temp_path", None)
        if previous is not None:
            previous.unlink(missing_ok=True)
        fd, path_str = tempfile.mkstemp(suffix=".png", prefix="orcshot-", dir=str(self._external_editor_cache_dir()))
        os.close(fd)
        path = Path(path_str)
        self._external_editor_temp_path = path
        save_image_to_file(self._composited_image(), path)
        subprocess.Popen(command + [str(path)])

    # Mirrors _TOOL_KEYS above one-for-one, in the same order - "6" is
    # handled outside that dict (see its own comment there) but listed
    # here in its natural position anyway. Solid Fill/Scramble/Pixelize/
    # Blur are deliberately absent as their own rows (no dedicated key
    # each) but called out in their own explanatory row so this doesn't
    # read as though they were just forgotten.
    _HELP_SECTIONS = [
        ("Tools", [
            ("Escape", "Select"),
            ("R", "Rectangle"),
            ("E", "Ellipse"),
            ("L", "Line"),
            ("F", "Freehand"),
            ("A", "Arrow"),
            ("T", "Text"),
            ("S", "Speech Bubble"),
            ("I", "Step Label"),
            ("H", "Highlight (whichever mode was last prepared)"),
            ("O", "Obfuscate (whichever mode was last prepared)"),
            ("C", "Crop (whichever mode was last prepared)"),
            ("M", "Emoji"),
            ("Z", "Resize (a whole-image effect, not a drawing tool)"),
            ("", "Every tool's own sub-modes (Text/Area/Grayscale/Magnify Highlight; Solid Fill/Scramble/"
                  "Pixelize/Blur Obfuscate; Default/Vertical/Horizontal Crop) - via that tool's own Mode "
                  "dropdown, no dedicated key each"),
        ]),
        ("Editing", [
            ("Delete", "Delete the selected shape"),
            ("Double-click", "Re-edit an existing text/speech bubble/emoji shape"),
            ("Enter", "Commit a text/speech bubble/emoji edit"),
            ("Escape", "Cancel a text/speech bubble/emoji edit, or an in-progress crop selection"),
        ]),
        ("Actions", [
            ("Ctrl+Z / Ctrl+Y", "Undo / Redo"),
            ("Ctrl+C", "Copy the whole image to the clipboard"),
            ("Ctrl+S", "Save"),
            ("Ctrl+P", "Print"),
            ("Ctrl+B", "Add Border"),
            ("Ctrl+Q", "Add Drop Shadow"),
            ("Ctrl+T", "Add Torn Edge"),
            ("Ctrl+G", "Grayscale"),
            ("Ctrl+I", "Invert Colors"),
            ("Ctrl+Delete", "Clear (transparent background)"),
            ("Ctrl+, / Ctrl+.", "Rotate counterclockwise / clockwise"),
            ("Ctrl+ +/-", "Zoom in / out"),
            ("Ctrl+Shift+ +/-", "Enlarge / shrink canvas"),
            ("Ctrl+0", "Zoom to actual size"),
            ("Ctrl+9", "Zoom to best fit"),
        ]),
    ]

    @staticmethod
    def _tray_icon_help_rows() -> list:
        """Genuinely different behavior per platform, not just a
        wording choice - see app.py's _build_tray_icon docstring for
        the full citation trail (a real AyatanaAppIndicator3
        limitation on Wayland, not a bug in this app: once a menu is
        attached, there's no separate click action, only Xlib/XEmbed-
        based Gtk.StatusIcon on X11 distinguishes left/right click).
        Detected the same way app.py itself picks which tray
        implementation to build, rather than guessing from whatever
        capture backend happened to get selected.
        """
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            return [("Click", "Open the tray menu (Wayland has no separate click action)")]
        return [
            ("Left-click", "Start a region capture immediately"),
            ("Right-click", "Open the tray menu"),
        ]

    def _do_show_help(self) -> None:
        self._commit_text_editing_if_active()
        dialog = Gtk.Dialog(title="Orcshot Help", transient_for=self)
        dialog.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        content = dialog.get_content_area()
        content.set_border_width(12)

        grid = Gtk.Grid(row_spacing=4, column_spacing=16)
        row = 0

        def add_header(text: str) -> None:
            nonlocal row
            label = Gtk.Label()
            label.set_markup(f"<b>{text}</b>")
            label.set_xalign(0)
            if row > 0:
                label.set_margin_top(10)
            grid.attach(label, 0, row, 2, 1)
            row += 1

        def add_row(key: str, function: str) -> None:
            nonlocal row
            # Slightly indented relative to its own section header,
            # not the header's own left edge - matches this dialog's
            # previous plain-text layout, just as a real Gtk.Grid
            # instead of hand-counted whitespace padding (which was
            # already drifting - "Ctrl+Z / Ctrl+Y" is wider than every
            # other Actions key, so manual column alignment was
            # approximate at best).
            key_label = Gtk.Label(label=key)
            key_label.set_xalign(0)
            key_label.set_selectable(True)
            key_label.set_margin_start(12)
            function_label = Gtk.Label(label=function)
            function_label.set_xalign(0)
            function_label.set_selectable(True)
            grid.attach(key_label, 0, row, 1, 1)
            grid.attach(function_label, 1, row, 1, 1)
            row += 1

        for title, entries in self._HELP_SECTIONS:
            add_header(title)
            for key, function in entries:
                add_row(key, function)

        add_header("Tray Icon")
        for key, function in self._tray_icon_help_rows():
            add_row(key, function)

        content.pack_start(grid, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    @staticmethod
    def _text_editing_rect(shape):
        """Which of a shape's rects holds the editable text -
        SpeechBubbleShape's bubble_bounds (its wider ``bounds`` also
        covers the tail, see shapes.py), everything else's own bounds.
        """
        return shape.bubble_bounds if isinstance(shape, SpeechBubbleShape) else shape.bounds

    def _text_editor_screen_rect(self):
        """The editing overlay's position/size in drawing-area widget
        coordinates - same inset-by-ceil(line_thickness/2) math as
        render.py's _draw_text_block, then offset/scaled by the
        current pan/zoom exactly like _on_button_press's own inverse
        transform (_content_offset), so the live TextView lines up
        with where render_shape will actually draw the committed text.
        """
        shape = self._editing_text_shape
        rect = self._text_editing_rect(shape)
        line_thickness = shape.style.line_thickness
        text_offset = math.ceil(line_thickness / 2) if line_thickness > 0 else 0
        offset_x, offset_y = self._content_offset()
        zoom = float(self._zoom)
        x = offset_x + (rect.left + text_offset) * zoom
        y = offset_y + (rect.top + text_offset) * zoom
        w = (rect.width - 2 * text_offset) * zoom
        h = (rect.height - 2 * text_offset) * zoom
        return x, y, w, h

    def _on_canvas_overlay_get_child_position(self, overlay, widget, allocation):
        if widget is not self._text_editor or self._editing_text_shape is None:
            return False
        x, y, w, h = self._text_editor_screen_rect()
        allocation.x, allocation.y = round(x), round(y)
        allocation.width, allocation.height = max(1, round(w)), max(1, round(h))
        return True

    def _apply_text_editor_style(self, shape) -> None:
        """UpdateTextBoxFont/UpdateTextBoxFormat (TextContainer.cs) -
        matches the shape's font (scaled by the current zoom, same as
        _pango_layout), alignment, text color, and background.

        The background is the shape's own real fill_color, not a
        synthesized contrast color the way Windows' EnsureTextBoxContrast
        picks one (always-opaque white/dark-gray, regardless of the
        shape's own fill) - a deliberate deviation, by request: WYSIWYG
        while editing (a transparent-fill shape, the Text tool's own
        default, shows no background at all while typing, matching
        what committing it actually produces) was preferred over
        faithfully porting a readability crutch for the has-no-fill
        case.

        No Windows citation for the border-radius below - WinForms'
        TextBox is a plain rectangle there too (UpdateTextBoxPosition,
        TextContainer.cs:542-570, positions it from the container's
        bounds with no rounded-corner accommodation). Purely this
        port's own polish: without it, the editor overlay's own
        rectangular background corners visibly poke out past
        SpeechBubbleShape's rounded outline while typing.
        """
        size = shape.font_size * float(self._zoom)
        weight = "Bold " if shape.bold else ""
        slant = "Italic " if shape.italic else ""
        font_desc = Pango.FontDescription.from_string(f"{shape.font_family} {weight}{slant}{size}")
        self._text_editor.override_font(font_desc)
        self._text_editor.set_justification(_TEXT_EDITOR_JUSTIFICATION[shape.horizontal_alignment])

        text_color = shape.style.line_color
        radius = bubble_corner_radius(shape) * float(self._zoom) if isinstance(shape, SpeechBubbleShape) else 0.0
        css = (
            # Transparent, not matching the theme's own default - a
            # rounded "text" node still paints its full rectangular
            # allocation everywhere CSS doesn't explicitly punch a
            # rounded hole in it, which without this left solid black
            # theme-background squares showing through the corners the
            # border-radius below was supposed to round away.
            "textview {"
            "background-color: transparent;"
            "}"
            "textview text {"
            f"color: {_css_rgba(text_color)};"
            f"caret-color: {_css_rgba(text_color)};"
            f"background-color: {_css_rgba(shape.style.fill_color)};"
            f"border-radius: {max(0.0, radius)}px;"
            "}"
        )
        self._text_editor_css_provider.load_from_data(css.encode())
        self._update_text_editor_vertical_offset()

    def _update_text_editor_vertical_offset(self) -> None:
        """No native "vertical-align: center" for a Gtk.TextView's own
        content (unlike Pango layout centering, which _draw_text_block
        already applies to the committed render) - approximated via
        top_margin, using the same vertical_text_offset math render.py
        uses, so what you see while typing starts roughly where the
        final centered/bottom-aligned text will land instead of always
        top-aligned, and keeps tracking as the text grows/shrinks (see
        this method's callers).

        Measures a real Pango.Layout built the same way render.py's
        own _pango_layout is (same font string, wrap mode, width) -
        the earlier version of this method used the TextView widget's
        own get_preferred_height_for_width instead, which uses GTK's
        internal text-layout line-height metrics rather than Pango's
        raw ones, and drifted further from the committed render's own
        centering the more text/lines there were. font_size is scaled
        by zoom (screen pixels, matching where this widget actually
        lives) rather than passed raw the way _draw_text_block does,
        since that draws in unscaled image space under a later
        ctx.scale(zoom, zoom) - this measures in screen space directly
        instead, paired with box_w/box_h already being screen pixels
        too (_text_editor_screen_rect).
        """
        shape = self._editing_text_shape
        if shape is None:
            return
        _, _, box_w, box_h = self._text_editor_screen_rect()
        buffer = self._text_editor.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        size = shape.font_size * float(self._zoom)
        weight = "Bold " if shape.bold else ""
        slant = "Italic " if shape.italic else ""
        layout = self._text_editor.create_pango_layout(text)
        layout.set_font_description(Pango.FontDescription.from_string(f"{shape.font_family} {weight}{slant}{size}"))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_width(max(0, round(box_w * Pango.SCALE)))
        _, text_height = layout.get_pixel_size()
        offset = vertical_text_offset(shape.vertical_alignment, box_h, text_height)
        self._text_editor.set_top_margin(max(0.0, offset))

    def _show_text_editor(self) -> None:
        shape = self._editing_text_shape
        buffer = self._text_editor.get_buffer()
        buffer.set_text(shape.text)
        buffer.place_cursor(buffer.get_end_iter())
        self._apply_text_editor_style(shape)
        self._canvas_overlay.queue_resize()
        self._text_editor.show()
        self._text_editor.grab_focus()

    def _hide_text_editor(self) -> None:
        # Only reclaim focus for the canvas if the text editor still
        # had it (Escape/Enter while typing) - if focus already moved
        # elsewhere (e.g. a style panel control, which is what fired
        # the focus-out that led here), grabbing it back would yank
        # focus away from whatever the user just clicked into.
        had_focus = self._text_editor.has_focus()
        self._text_editor.hide()
        if had_focus:
            self._drawing_area.grab_focus()

    def _on_text_editor_changed(self, buffer) -> None:
        if self._editing_text_shape is None:
            return  # buffer edits from outside an active editing session
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        self._update_editing_text(text)
        self._update_text_editor_vertical_offset()

    def _on_text_editor_key_press(self, widget, event) -> bool:
        # Escape/plain-Enter (textBox_KeyDown, TextContainer.cs) are
        # the only keys this overlay special-cases - everything else,
        # including Shift+Enter's newline, Ctrl+A/Ctrl+C, arrow-key
        # navigation, and character insertion, is native Gtk.TextView
        # behavior handled by its own default key bindings.
        if event.keyval == Gdk.KEY_Escape:
            self._cancel_text_editing()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (event.state & Gdk.ModifierType.SHIFT_MASK):
            self._commit_text_editing()
            return True
        return False

    def _on_text_editor_focus_out(self, widget, event) -> bool:
        # TextBox_LostFocus (TextContainer.cs) - also fires as a side
        # effect of _hide_text_editor's own hide() call once editing
        # has already ended, which _commit_text_editing_if_active's
        # guard below makes a harmless no-op.
        self._commit_text_editing_if_active()
        return False

    def _update_editing_text(self, new_text: str) -> None:
        old_shape = self._editing_text_shape
        new_shape = dataclass_replace(old_shape, text=new_text)
        self.layer.replace(old_shape, new_shape)
        self._editing_text_shape = new_shape
        self.selected_shape = new_shape
        self._drawing_area.queue_draw()

    def _commit_text_editing(self) -> None:
        shape = self._editing_text_shape
        original = self._editing_original_shape
        self._editing_text_shape = None
        self._editing_original_shape = None

        if not shape.text.strip():
            self.layer.remove(shape)
            self.selected_shape = None
            if original is not None:
                # it existed before this edit session - deleting it
                # needs to be undoable, unlike discarding a fresh one.
                self.undo_redo.push(DeleteElementMemento(self.layer, original))
        elif original is not None:
            self.undo_redo.push(ElementChangeMemento(self.layer, before=original, after=shape))
        else:
            self.undo_redo.push(AddElementMemento(self.layer, shape))
        self._hide_text_editor()
        self._drawing_area.queue_draw()

    def _commit_text_editing_if_active(self) -> None:
        if self._editing_text_shape is not None:
            self._commit_text_editing()

    def _cancel_text_editing(self) -> None:
        shape = self._editing_text_shape
        original = self._editing_original_shape
        self._editing_text_shape = None
        self._editing_original_shape = None

        if original is not None:
            # revert to the pre-edit text; nothing was ever pushed to
            # undo history for this session, so there's nothing to undo.
            self.layer.replace(shape, original)
            self.selected_shape = original
        else:
            self.layer.remove(shape)
            self.selected_shape = None
        self._hide_text_editor()
        self._drawing_area.queue_draw()

    def _move_preview_for(self, shape):
        """``shape``'s live move preview, if it's one of the shapes
        currently being dragged - looked up by position in the
        parallel _move_shapes/_move_previews lists (not a dict keyed
        by shape - see _move_shapes' own comment on why), None if
        ``shape`` isn't being moved right now.
        """
        for moving, preview in zip(self._move_shapes, self._move_previews):
            if moving is shape:
                return preview
        return None

    def _selected_display_shape(self):
        """The selected (primary) shape's current bounds for handle
        drawing, following whichever live preview (if any) applies."""
        if self._resize_shape is not None:
            return self._resize_preview or self._resize_shape
        primary = self.selected_shape
        if primary is not None and any(s is primary for s in self._move_shapes):
            return self._move_preview_for(primary) or primary
        return primary

    def _draw_handles(self, ctx, shape):
        half = _HANDLE_SIZE / 2
        for x, y in shape_handles(shape).values():
            ctx.save()
            ctx.rectangle(x - half, y - half, _HANDLE_SIZE, _HANDLE_SIZE)
            ctx.set_source_rgb(*_HANDLE_FILL)
            ctx.fill_preserve()
            ctx.set_source_rgb(*_HANDLE_STROKE)
            ctx.set_line_width(1)
            ctx.stroke()
            ctx.restore()

    def _draw_selection_outline(self, ctx, shape) -> None:
        """A plain bounding-box outline, no resize handles - task
        #125's own marker for every selected shape that isn't the
        primary one (see _selected_display_shape). Same stroke color
        as the primary shape's own handles, just without the fill
        squares, so a multi-selection still reads as one coherent
        "these are all selected" visual rather than looking like only
        one shape is really selected.
        """
        b = shape.bounds
        ctx.save()
        ctx.set_source_rgb(*_HANDLE_STROKE)
        ctx.set_line_width(1)
        ctx.set_dash([4, 3])
        ctx.rectangle(b.left, b.top, b.width, b.height)
        ctx.stroke()
        ctx.restore()

    def _resize_canvas_and_window(self) -> None:
        """Resizes the drawing area to the current base image's size
        at the current zoom level, then resizes the *window* to fit
        that (GetOptimalWindowSize, ImageEditorForm.cs:2012-2052) -
        chrome size (everything that isn't the canvas: menu bar,
        toolbars, style panel, tool palette) is measured from the
        current layout rather than hardcoded, since it doesn't vary
        with zoom/canvas size but does vary with which panels are
        shown. Only scrolls (via _canvas_scroller) if even the
        screen-clamped window still can't fit the canvas. Shared by
        _set_zoom (zoom changed, image size didn't) and every
        whole-image effect that changes the canvas's own dimensions
        (rotate/border/resize/etc., core/effects.py) - either way the
        drawing area's on-screen size needs to track "image size *
        zoom" freshly.
        """
        img_h, img_w = self._base_image.shape[:2]
        canvas_w, canvas_h = round(img_w * self._zoom), round(img_h * self._zoom)
        self._drawing_area.set_size_request(canvas_w, canvas_h)

        window_alloc = self.get_allocation()
        scroller_alloc = self._canvas_scroller.get_allocation()
        chrome_w = max(0, window_alloc.width - scroller_alloc.width)
        chrome_h = max(0, window_alloc.height - scroller_alloc.height)

        display = Gdk.Display.get_default()
        gdk_window = self.get_window()
        monitor = display.get_monitor_at_window(gdk_window) if gdk_window is not None else None
        if monitor is None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        work_area = monitor.get_workarea()

        total_w, total_h = optimal_window_size(
            chrome_w, chrome_h, canvas_w, canvas_h,
            _MIN_WINDOW_WIDTH, _MIN_WINDOW_HEIGHT, work_area.width, work_area.height,
        )
        self.resize(total_w, total_h)
        self._drawing_area.queue_draw()

    def _set_zoom(self, new_zoom: Fraction) -> None:
        """Every zoom action (menu/dropdown pick, keyboard shortcut,
        Ctrl+wheel) funnels through here - faithful port of
        ZoomSetValue (ImageEditorForm.cs:2113-2164).
        """
        if new_zoom == self._zoom:
            return
        self._zoom = new_zoom
        self._resize_canvas_and_window()
        self._zoom_label.set_text(zoom_percent_label(self._zoom))

    def _do_zoom_in(self) -> None:
        self._set_zoom(zoom_in(self._zoom))

    def _do_zoom_out(self) -> None:
        self._set_zoom(zoom_out(self._zoom))

    def _do_zoom_actual_size(self) -> None:
        self._set_zoom(ACTUAL_SIZE_ZOOM)

    def _do_zoom_best_fit(self) -> None:
        img_h, img_w = self._base_image.shape[:2]
        display = Gdk.Display.get_default()
        gdk_window = self.get_window()
        monitor = display.get_monitor_at_window(gdk_window) if gdk_window is not None else None
        if monitor is None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        work_area = monitor.get_workarea()
        self._set_zoom(best_fit_zoom(img_w, img_h, work_area.width, work_area.height))

    def _on_scroll(self, widget, event):
        # Ctrl+wheel zoom (PanelMouseWheel, ImageEditorForm.cs:1181-1200),
        # throttled to one step per 100ms the same way Windows is
        # (_zoomStartTime, ImageEditorForm.cs:1185-1187) - a physical
        # scroll wheel can send many events per detent otherwise.
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        now = time.monotonic()
        if now - self._last_wheel_zoom_time < _ZOOM_WHEEL_THROTTLE_SECONDS:
            return True
        self._last_wheel_zoom_time = now
        if event.direction == Gdk.ScrollDirection.UP:
            self._do_zoom_in()
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self._do_zoom_out()
        return True

    def _build_status_bar(self) -> Gtk.Box:
        """Bottom status bar - matches Windows' statusStrip1's
        dimensionsLabel + zoomStatusDropDownBtn (ImageEditorForm.
        Designer.cs:59,224,271-277). Task #95 added a real top-level
        Zoom menu too (_build_menu_bar) - confirmed via source that
        Windows genuinely has both entry points sharing one
        zoomMenuStrip, not just this dropdown; _populate_zoom_menu is
        the shared builder so the two never drift apart.
        """
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(2)

        img_h, img_w = self._base_image.shape[:2]
        self._dimensions_label = Gtk.Label(label=f"{img_w} x {img_h}")
        bar.pack_start(self._dimensions_label, False, False, 4)

        zoom_menu = Gtk.Menu()
        self._populate_zoom_menu(zoom_menu)

        zoom_button = Gtk.MenuButton()
        self._zoom_label = Gtk.Label(label=zoom_percent_label(self._zoom))
        zoom_button.add(self._zoom_label)
        zoom_button.set_popup(zoom_menu)
        bar.pack_end(zoom_button, False, False, 0)
        return bar

    # --- Whole-image effects (core/effects.py + ui/effects.py) --------
    #
    # None of these are drawn annotation shapes - they transform the
    # entire captured image, faithfully porting Greenshot.Base/Effects/*
    # (see REQUIREMENTS.md's "Whole-image effects" section for the
    # full per-effect citation trail). Live in the toolbar's Effects
    # dropdown (_build_effects_control, task #89) matching Windows'
    # own toolStripSplitButton1 - there is and never was a menu-bar
    # path for these (task #95 removed the "Image" menu, which by then
    # only still held "Clear", not effects - see _do_clear's own note).

    def _apply_background_effect(self, new_image: np.ndarray, transform=None) -> None:
        """Applies any whole-image effect as one undoable step -
        faithful port of Surface.ApplyBitmapEffect (Surface.cs:1093-1127):
        transforms every existing element to match, if the effect
        moved/resized the canvas (``transform``: shape -> shape, e.g.
        a partial application of translate_shape/scale_shape/
        rotate_shape_90 - None for pixel-only effects like grayscale/
        invert, which never touch element positions), then swaps in
        the new image - the base_image property setter keeps
        rendering/canvas size/window size/the dimensions label all in
        sync automatically, including on undo/redo - and pushes one
        BackgroundChangeMemento.
        """
        self._commit_text_editing_if_active()
        before_image = self.base_image
        element_pairs = []
        if transform is not None:
            for shape in list(self.layer):
                new_shape = transform(shape)
                self.layer.replace(shape, new_shape)
                element_pairs.append((shape, new_shape))
                if self.selected_shape is shape:
                    self.selected_shape = new_shape
        self.base_image = new_image
        self.undo_redo.push(BackgroundChangeMemento(self, self.layer, before_image, new_image, element_pairs))
        self._drawing_area.queue_draw()

    def _do_rotate_cw(self) -> None:
        h, w = self._base_image.shape[:2]
        new_image = rotate_90_image(self._base_image, clockwise=True)
        self._apply_background_effect(new_image, transform=lambda s: rotate_shape_90(s, w, h, clockwise=True))

    def _do_rotate_ccw(self) -> None:
        h, w = self._base_image.shape[:2]
        new_image = rotate_90_image(self._base_image, clockwise=False)
        self._apply_background_effect(new_image, transform=lambda s: rotate_shape_90(s, w, h, clockwise=False))

    def _do_grayscale(self) -> None:
        self._apply_background_effect(grayscale_image(self._base_image))

    def _do_invert(self) -> None:
        self._apply_background_effect(invert_image(self._base_image))

    _BORDER_WIDTH = 2  # Windows' own fixed default (AddBorderToolStripMenuItemClick) - no dialog

    def _do_border(self) -> None:
        width = self._BORDER_WIDTH
        new_image = add_border_image(self._base_image, width=width, color=(0, 0, 0, 255))
        self._apply_background_effect(new_image, transform=lambda s: translate_shape(s, width, width))

    _ENLARGE_CANVAS_PAD = 25  # matches ImageEditorForm.cs:1817-1821's fixed 25px

    def _do_enlarge_canvas(self) -> None:
        pad = self._ENLARGE_CANVAS_PAD
        new_image = enlarge_canvas_image(self._base_image, left=pad, right=pad, top=pad, bottom=pad)
        self._apply_background_effect(new_image, transform=lambda s: translate_shape(s, pad, pad))

    def _do_shrink_canvas(self) -> None:
        rect = autocrop_rect(self._base_image)
        if rect is None:
            return
        new_image = crop_to_rect(self._base_image, rect)
        self._apply_background_effect(new_image, transform=lambda s: translate_shape(s, -rect.left, -rect.top))

    def _do_clear(self) -> None:
        """Edit > Clear All (task #95 - moved here from a now-removed
        "Image" menu that Windows never actually had; see
        _build_menu_bar's own docstring)."""
        h, w = self._base_image.shape[:2]
        self._apply_background_effect(clear_image(w, h))

    def _do_remove_transparency(self) -> None:
        self._commit_text_editing_if_active()
        dialog = Gtk.ColorChooserDialog(title="Remove Transparency", transient_for=self)
        dialog.set_use_alpha(False)
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            fill_color = _rgba_to_color(dialog.get_rgba())
        finally:
            dialog.destroy()
        self._apply_background_effect(remove_transparency_image(self._base_image, fill_color=fill_color))

    def _do_obfuscate_text(self) -> None:
        """Task #100 - see ui/text_obfuscation_dialog.py's module
        docstring for the full faithful-port writeup."""
        self._commit_text_editing_if_active()
        do_obfuscate_text(self)

    def _do_resize(self) -> None:
        """Opens ResizeSettingsForm's equivalent - width/height in
        pixels with an aspect-ratio lock. Windows also offers a
        percent-based entry mode; not ported here, a deliberate scope
        reduction to keep the dialog simple - pixel entry alone covers
        the effect's actual behavior faithfully.
        """
        self._commit_text_editing_if_active()
        h, w = self._base_image.shape[:2]
        dialog = Gtk.Dialog(title="Resize Image", transient_for=self)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.attach(Gtk.Label(label="Width:"), 0, 0, 1, 1)
        width_spin = Gtk.SpinButton.new_with_range(1, 10000, 1)
        width_spin.set_value(w)
        grid.attach(width_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Height:"), 0, 1, 1, 1)
        height_spin = Gtk.SpinButton.new_with_range(1, 10000, 1)
        height_spin.set_value(h)
        grid.attach(height_spin, 1, 1, 1, 1)
        aspect_check = Gtk.CheckButton(label="Maintain aspect ratio")
        aspect_check.set_active(True)
        grid.attach(aspect_check, 0, 2, 2, 1)
        content.pack_start(grid, False, False, 0)

        updating = [False]

        def on_width_changed(spin):
            if updating[0] or not aspect_check.get_active():
                return
            updating[0] = True
            height_spin.set_value(round(spin.get_value() * h / w))
            updating[0] = False

        def on_height_changed(spin):
            if updating[0] or not aspect_check.get_active():
                return
            updating[0] = True
            width_spin.set_value(round(spin.get_value() * w / h))
            updating[0] = False

        width_spin.connect("value-changed", on_width_changed)
        height_spin.connect("value-changed", on_height_changed)

        dialog.show_all()
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            new_w, new_h = int(width_spin.get_value()), int(height_spin.get_value())
        finally:
            dialog.destroy()

        new_image = resize_image(self._base_image, new_w, new_h)
        scale_x, scale_y = new_w / w, new_h / h
        self._apply_background_effect(new_image, transform=lambda s: scale_shape(s, scale_x, scale_y))

    def _do_drop_shadow(self) -> None:
        """Instant-apply with the last-used (or default) settings -
        Windows' own left-click behavior (Ctrl+Q too); right-click
        equivalent is _do_drop_shadow_settings below.
        """
        settings = self._drop_shadow_settings
        new_image = drop_shadow_image(self._base_image, **settings)
        pad = settings["size"]
        self._apply_background_effect(new_image, transform=lambda s: translate_shape(s, pad, pad))

    def _do_drop_shadow_settings(self) -> None:
        self._commit_text_editing_if_active()
        settings = self._drop_shadow_settings
        dialog = Gtk.Dialog(title="Drop Shadow Settings", transient_for=self)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.attach(Gtk.Label(label="Darkness:"), 0, 0, 1, 1)
        darkness_spin = Gtk.SpinButton.new_with_range(0, 1, 0.05)
        darkness_spin.set_digits(2)
        darkness_spin.set_value(settings["darkness"])
        grid.attach(darkness_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Size:"), 0, 1, 1, 1)
        size_spin = Gtk.SpinButton.new_with_range(1, 50, 1)
        size_spin.set_value(settings["size"])
        grid.attach(size_spin, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Offset X:"), 0, 2, 1, 1)
        offset_x_spin = Gtk.SpinButton.new_with_range(-50, 50, 1)
        offset_x_spin.set_value(settings["offset"][0])
        grid.attach(offset_x_spin, 1, 2, 1, 1)
        grid.attach(Gtk.Label(label="Offset Y:"), 0, 3, 1, 1)
        offset_y_spin = Gtk.SpinButton.new_with_range(-50, 50, 1)
        offset_y_spin.set_value(settings["offset"][1])
        grid.attach(offset_y_spin, 1, 3, 1, 1)
        content.pack_start(grid, False, False, 0)

        dialog.show_all()
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            settings["darkness"] = darkness_spin.get_value()
            settings["size"] = int(size_spin.get_value())
            settings["offset"] = (int(offset_x_spin.get_value()), int(offset_y_spin.get_value()))
        finally:
            dialog.destroy()
        self._do_drop_shadow()

    def _do_torn_edge(self) -> None:
        """Instant-apply with the last-used (or default) settings -
        same left-click/Ctrl+T pattern as drop shadow.
        """
        settings = self._torn_edge_settings
        new_image = torn_edge_image(self._base_image, **settings)
        pad = settings["shadow_size"]
        if settings["generate_shadow"]:
            pad *= 2  # torn_edge_image pads once for the tear, again for the shadow it chains into
        self._apply_background_effect(new_image, transform=lambda s: translate_shape(s, pad, pad))

    def _do_torn_edge_settings(self) -> None:
        self._commit_text_editing_if_active()
        settings = self._torn_edge_settings
        dialog = Gtk.Dialog(title="Torn Edge Settings", transient_for=self)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.attach(Gtk.Label(label="Tooth height:"), 0, 0, 1, 1)
        tooth_spin = Gtk.SpinButton.new_with_range(1, 50, 1)
        tooth_spin.set_value(settings["tooth_height"])
        grid.attach(tooth_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Horizontal tooth range:"), 0, 1, 1, 1)
        h_range_spin = Gtk.SpinButton.new_with_range(2, 200, 1)
        h_range_spin.set_value(settings["horizontal_tooth_range"])
        grid.attach(h_range_spin, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="Vertical tooth range:"), 0, 2, 1, 1)
        v_range_spin = Gtk.SpinButton.new_with_range(2, 200, 1)
        v_range_spin.set_value(settings["vertical_tooth_range"])
        grid.attach(v_range_spin, 1, 2, 1, 1)
        content.pack_start(grid, False, False, 0)

        edge_labels = ("Top", "Right", "Bottom", "Left")
        edge_checks = []
        edge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, enabled in zip(edge_labels, settings["edges"]):
            check = Gtk.CheckButton(label=label)
            check.set_active(enabled)
            edge_checks.append(check)
            edge_box.pack_start(check, False, False, 0)
        content.pack_start(edge_box, False, False, 0)

        shadow_check = Gtk.CheckButton(label="Generate shadow")
        shadow_check.set_active(settings["generate_shadow"])
        content.pack_start(shadow_check, False, False, 0)

        dialog.show_all()
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            settings["tooth_height"] = int(tooth_spin.get_value())
            settings["horizontal_tooth_range"] = int(h_range_spin.get_value())
            settings["vertical_tooth_range"] = int(v_range_spin.get_value())
            settings["edges"] = tuple(c.get_active() for c in edge_checks)
            settings["generate_shadow"] = shadow_check.get_active()
        finally:
            dialog.destroy()
        self._do_torn_edge()

    def _content_offset(self) -> tuple:
        """How far the image is inset from the drawing area's top-left
        corner. The drawing area can end up larger than the zoomed
        image - a small/zoomed-out capture is narrower than the
        toolbar's natural width, and Gtk.Box (packed with fill=True)
        stretches every child to that width - so without this, a
        small capture used to sit pinned to the corner with a
        lopsided gap on the right/bottom instead of looking centered.
        """
        img_h, img_w = self._base_image.shape[:2]
        zoomed_w, zoomed_h = round(img_w * self._zoom), round(img_h * self._zoom)
        alloc = self._drawing_area.get_allocation()
        return max(0, (alloc.width - zoomed_w) // 2), max(0, (alloc.height - zoomed_h) // 2)

    def _on_draw(self, widget, ctx):
        offset_x, offset_y = self._content_offset()
        ctx.translate(offset_x, offset_y)
        ctx.scale(float(self._zoom), float(self._zoom))
        ctx.set_source_surface(self._surface, 0, 0)
        ctx.paint()
        for shape in self.layer:
            move_preview = self._move_preview_for(shape)
            if move_preview is not None:
                render_shape(ctx, move_preview, base_image=self._base_image)
            elif shape is self._resize_shape and self._resize_preview is not None:
                render_shape(ctx, self._resize_preview, base_image=self._base_image)
            else:
                render_shape(ctx, shape, base_image=self._base_image)
        if self._drag_shape is not None:
            render_shape(ctx, self._drag_shape, base_image=self._base_image)

        # Every non-primary selected shape gets a plain outline (no
        # resize handles - multi-shape resize is out of scope, see
        # _selected_display_shape's own comment); the primary one gets
        # full handles below, matching real Windows' own Adorners
        # (only ever shown on one element even during a multi-select).
        # Slicing to [:-1] is naturally [] when 0-1 shapes are
        # selected, no separate length check needed.
        for shape in self._selected_shapes[:-1]:
            outline_shape = self._move_preview_for(shape) or shape
            self._draw_selection_outline(ctx, outline_shape)

        display_shape = self._selected_display_shape()
        if display_shape is not None:
            self._draw_handles(ctx, display_shape)

        if self.tool in _CROP_MODE_ORDER and self._crop_selection is not None:
            self._draw_crop_overlay(ctx, self._crop_selection)
        return False

    def _draw_crop_overlay(self, ctx, rect: Rect) -> None:
        """The in-progress crop selection's own overlay - faithful port
        of CropContainer.Draw (CropContainer.cs): a translucent tint
        (Windows: Color.FromArgb(100, 150, 150, 100), alpha~0.39) over
        whichever region *won't* survive confirming - outside the
        selection for Default (crop-to), inside it for Vertical/
        Horizontal (crop-out, matching those modes' own "remove this
        band" semantic, see core/crop.py's own module docstring) - plus
        a solid selection border and resize handles. core/crop.py's own
        docstring explicitly calls this preview an "editing-UI
        rendering concern... not ported" there, meaning here, in the
        UI layer, is exactly where it belongs.
        """
        img_h, img_w = self._base_image.shape[:2]
        ctx.save()
        ctx.set_source_rgba(150 / 255, 150 / 255, 100 / 255, 100 / 255)
        if self.tool in (Tool.CROP_VERTICAL, Tool.CROP_HORIZONTAL):
            ctx.rectangle(rect.left, rect.top, rect.width, rect.height)
            ctx.fill()
        else:
            ctx.rectangle(0, 0, img_w, rect.top)  # top
            ctx.rectangle(0, rect.top, rect.left, rect.height)  # left
            ctx.rectangle(rect.right, rect.top, img_w - rect.right, rect.height)  # right
            ctx.rectangle(0, rect.bottom, img_w, img_h - rect.bottom)  # bottom
            ctx.fill()
        ctx.set_source_rgb(*_HANDLE_STROKE)
        ctx.set_line_width(1)
        ctx.rectangle(rect.left, rect.top, rect.width, rect.height)
        ctx.stroke()
        ctx.restore()

        half = _HANDLE_SIZE / 2
        for hx, hy in self._crop_handles(rect).values():
            ctx.save()
            ctx.rectangle(hx - half, hy - half, _HANDLE_SIZE, _HANDLE_SIZE)
            ctx.set_source_rgb(*_HANDLE_FILL)
            ctx.fill_preserve()
            ctx.set_source_rgb(*_HANDLE_STROKE)
            ctx.set_line_width(1)
            ctx.stroke()
            ctx.restore()

    def _on_button_press(self, widget, event):
        self._commit_text_editing_if_active()
        offset_x, offset_y = self._content_offset()
        # InverseZoomMouseCoordinates (Surface.cs:1469-1470): screen/
        # widget pixels back into unscaled image-space coordinates, so
        # drawing/hit-testing stays accurate at any zoom level.
        zoom = float(self._zoom)
        x, y = int((event.x - offset_x) / zoom), int((event.y - offset_y) / zoom)

        if self.tool in _CROP_MODE_ORDER:
            # Never creates/hits a Shape at all - see core/crop.py's
            # own module docstring - so this branches before the
            # normal Layer-hit-testing/shape-drag logic below entirely
            # rather than trying to weave into it.
            if self._crop_selection is not None:
                handle = self._crop_handle_at(self._crop_selection, x, y)
                if handle is not None:
                    self._crop_resize_handle = handle
                    widget.queue_draw()
                    return True
            self._crop_selection = self._crop_selection_from_drag((x, y), x, y)
            self._drag_origin = (x, y)
            self._refresh_style_panel()
            widget.queue_draw()
            return True

        if self.selected_shape is not None:
            handle = handle_at(self.selected_shape, x, y)
            if handle is not None:
                self._resize_shape = self.selected_shape
                self._resize_handle = handle
                widget.queue_draw()
                return True

        hit = self.layer.topmost_at(x, y)
        # Task #125: real Windows' own SurfaceMouseUp shift-toggle
        # logic (Surface.cs:1607-1636), adapted to this port's own
        # mouse-down-commits-selection architecture (predates this
        # task) rather than switching to Windows' mouse-up-based one.
        shift_held = bool(event.state & Gdk.ModifierType.SHIFT_MASK)

        if hit is not None and isinstance(hit, (TextShape, SpeechBubbleShape)) and event.type == Gdk.EventType._2BUTTON_PRESS:
            # A double-click's second press follows a first (single)
            # press that already ran the branch below and may have
            # started a move - cancel that, double-click means edit.
            self._move_shapes = []
            self._move_origin = None
            self.selected_shape = hit
            self._editing_text_shape = hit
            self._editing_original_shape = hit
            self._show_text_editor()
            widget.queue_draw()
            return True

        if hit is not None:
            already_selected = any(s is hit for s in self._selected_shapes)
            if shift_held and already_selected:
                # Shift-click on an already-selected shape deselects
                # just it, leaving the rest of the selection untouched
                # - matches real Windows' own DeselectElement toggle -
                # and doesn't start a move for a shape that's no longer
                # selected.
                self._set_selected_shapes([s for s in self._selected_shapes if s is not hit])
                widget.queue_draw()
                return True
            if shift_held:
                self._set_selected_shapes(self._selected_shapes + [hit])
            elif not already_selected:
                # Plain click on something NOT already part of a
                # multi-selection replaces the whole selection - but a
                # plain click on something that IS already selected
                # deliberately leaves the rest of the selection alone,
                # so dragging any member of an existing multi-selection
                # moves the whole group (matches real Windows exactly,
                # Surface.cs:1611-1630).
                self.selected_shape = hit
            # Move the *whole* current selection together, not just
            # the clicked shape - real Windows' own SurfaceMouseMove:
            # "dragged element has been selected before -> move all"
            # (Surface.cs:1707-1708).
            self._move_shapes = list(self._selected_shapes)
            self._move_origin = (x, y)
        elif self.tool is Tool.SELECT:
            # Select (Windows' "Cursor" tool) on empty space: real
            # Windows just clears the selection here (Surface.cs:1632-
            # 1635); this port also starts a rubber-band/marquee drag
            # (task #125, an Orcshot-only addition beyond the real
            # port - real Windows' own SurfaceMouseDown/Move has no
            # such feature at all, confirmed via its source, see
            # REQUIREMENTS.md's task #125 section). Shift-held starts
            # an *additive* rubber band instead of clearing first.
            if not shift_held:
                self._set_selected_shapes([])
            self._rubber_band_origin = (x, y)
            self._rubber_band_rect = Rect(x, y, x, y)
            self._rubber_band_additive = shift_held
        else:
            self.selected_shape = None
            self._drag_origin = (x, y)
            if self.tool is Tool.FREEHAND:
                self._drag_points = [(x, y)]
                self._drag_shape = create_freehand_shape(self._drag_points, self._style_for_tool(self.tool))
            else:
                self._drag_shape = create_shape_from_drag(
                    self.tool, (x, y), (x, y), self._style_for_tool(self.tool),
                    amount=self._default_obfuscate_amount, fill_color=self._default_obfuscate_fill_color,
                    fill_text=self._default_obfuscate_fill_text, text_color=self._default_obfuscate_text_color,
                    highlight_color=self._default_highlight_fill_color,
                    highlight_brightness=self._default_highlight_brightness,
                    highlight_blur_radius=self._default_highlight_blur_radius,
                    highlight_magnification=self._default_highlight_magnification,
                )
        widget.queue_draw()
        return True

    def _on_motion(self, widget, event):
        offset_x, offset_y = self._content_offset()
        # InverseZoomMouseCoordinates (Surface.cs:1469-1470): screen/
        # widget pixels back into unscaled image-space coordinates, so
        # drawing/hit-testing stays accurate at any zoom level.
        zoom = float(self._zoom)
        x, y = int((event.x - offset_x) / zoom), int((event.y - offset_y) / zoom)
        if self.tool in _CROP_MODE_ORDER and self._crop_selection is not None:
            if self._crop_resize_handle is not None:
                self._crop_selection = self._resize_crop_rect(self._crop_selection, self._crop_resize_handle, x, y)
            elif self._drag_origin is not None:
                self._crop_selection = self._crop_selection_from_drag(self._drag_origin, x, y)
            widget.queue_draw()
            return True
        if self._resize_shape is not None:
            self._resize_preview = resize_shape(self._resize_shape, self._resize_handle, x, y)
            widget.queue_draw()
            return True
        if self._move_shapes:
            dx, dy = x - self._move_origin[0], y - self._move_origin[1]
            self._move_previews = [translate_shape(shape, dx, dy) for shape in self._move_shapes]
            widget.queue_draw()
            return True
        if self._rubber_band_origin is not None:
            ox, oy = self._rubber_band_origin
            self._rubber_band_rect = Rect.from_points(ox, oy, x, y)
            widget.queue_draw()
            return True
        if self._drag_origin is not None:
            if self.tool is Tool.FREEHAND:
                self._drag_points.append((x, y))
                self._drag_shape = create_freehand_shape(self._drag_points, self._style_for_tool(self.tool))
            else:
                self._drag_shape = create_shape_from_drag(
                    self.tool, self._drag_origin, (x, y), self._style_for_tool(self.tool),
                    amount=self._default_obfuscate_amount, fill_color=self._default_obfuscate_fill_color,
                    fill_text=self._default_obfuscate_fill_text, text_color=self._default_obfuscate_text_color,
                    highlight_color=self._default_highlight_fill_color,
                    highlight_brightness=self._default_highlight_brightness,
                    highlight_blur_radius=self._default_highlight_blur_radius,
                    highlight_magnification=self._default_highlight_magnification,
                )
            widget.queue_draw()
            return True
        return False

    def _on_button_release(self, widget, event):
        offset_x, offset_y = self._content_offset()
        # InverseZoomMouseCoordinates (Surface.cs:1469-1470): screen/
        # widget pixels back into unscaled image-space coordinates, so
        # drawing/hit-testing stays accurate at any zoom level.
        zoom = float(self._zoom)
        x, y = int((event.x - offset_x) / zoom), int((event.y - offset_y) / zoom)
        if self.tool in _CROP_MODE_ORDER and self._crop_selection is not None:
            if self._crop_resize_handle is not None:
                self._crop_selection = self._resize_crop_rect(self._crop_selection, self._crop_resize_handle, x, y)
                self._crop_resize_handle = None
            elif self._drag_origin is not None:
                self._crop_selection = self._crop_selection_from_drag(self._drag_origin, x, y)
                self._drag_origin = None
            widget.queue_draw()
            return True
        if self._resize_shape is not None:
            final = resize_shape(self._resize_shape, self._resize_handle, x, y)
            self.layer.replace(self._resize_shape, final)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=self._resize_shape, after=final))
            self.selected_shape = final
            self._resize_shape = None
            self._resize_handle = None
            self._resize_preview = None
            widget.queue_draw()
            return True
        if self._move_shapes:
            dx, dy = x - self._move_origin[0], y - self._move_origin[1]
            if dx != 0 or dy != 0:
                # A real drag, not just a click - commit every moving
                # shape to its translated position as one undo step
                # (CompositeMemento, task #125 - real Windows' own
                # multi-move is a single undo too, matching how a
                # single-shape move already worked here). A no-op
                # click's selection was already fully decided at
                # button-press time (see _on_button_press's own
                # comments) - nothing to do here for that case.
                mementos = []
                finals = []
                for shape in self._move_shapes:
                    final = translate_shape(shape, dx, dy)
                    self.layer.replace(shape, final)
                    mementos.append(ElementChangeMemento(self.layer, before=shape, after=final))
                    finals.append(final)
                self.undo_redo.push(CompositeMemento(mementos) if len(mementos) > 1 else mementos[0])
                self._set_selected_shapes(finals)
            self._move_shapes = []
            self._move_origin = None
            self._move_previews = []
            widget.queue_draw()
            return True
        if self._rubber_band_origin is not None:
            rect = self._rubber_band_rect
            self._rubber_band_origin = None
            self._rubber_band_rect = None
            enclosed = [shape for shape in self.layer if rect.contains_rect(shape.bounds)]
            if self._rubber_band_additive:
                # Additive (shift-held) rubber band: union with the
                # existing selection rather than replacing it, same
                # spirit as shift-click's own toggle - though a second
                # rubber band over already-selected shapes just leaves
                # them selected (not a toggle-off), since "drag a box
                # over things to add them" doesn't have an obvious
                # toggle reading the way a single click does.
                merged = list(self._selected_shapes)
                for shape in enclosed:
                    if not any(s is shape for s in merged):
                        merged.append(shape)
                self._set_selected_shapes(merged)
            else:
                self._set_selected_shapes(enclosed)
            widget.queue_draw()
            return True
        if self._drag_origin is not None:
            if self.tool is Tool.FREEHAND:
                shape = create_freehand_shape(self._drag_points, self._style_for_tool(self.tool))
            else:
                shape = create_shape_from_drag(
                    self.tool, self._drag_origin, (x, y), self._style_for_tool(self.tool),
                    amount=self._default_obfuscate_amount, next_step_number=self._next_step_number(),
                    fill_color=self._default_obfuscate_fill_color,
                    fill_text=self._default_obfuscate_fill_text, text_color=self._default_obfuscate_text_color,
                    highlight_color=self._default_highlight_fill_color,
                    highlight_brightness=self._default_highlight_brightness,
                    highlight_blur_radius=self._default_highlight_blur_radius,
                    highlight_magnification=self._default_highlight_magnification,
                )
            self._drag_origin = None
            self._drag_points = None
            self._drag_shape = None
            self.layer.add(shape)
            self.selected_shape = shape
            if self.tool in (Tool.TEXT, Tool.SPEECH_BUBBLE, Tool.EMOJI):
                # Editing starts immediately; AddElementMemento is only
                # pushed once the text is committed (see
                # _commit_text_editing), not per-keystroke.
                self._editing_text_shape = shape
                self._editing_original_shape = None  # brand new, not a re-edit
                self._show_text_editor()
            else:
                self.undo_redo.push(AddElementMemento(self.layer, shape))
            widget.queue_draw()
            return True
        return False

    def _on_key_press(self, widget, event):
        if self._editing_text_shape is not None:
            # The text editor is a real focused widget now - let GTK's
            # normal focus-widget dispatch hand the event to it
            # (Escape/plain-Enter aside, handled in its own key-press
            # handler) rather than treating every key as a shortcut
            # the way this window-level handler does the rest of the
            # time.
            return False

        ctrl_held = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift_held = bool(event.state & Gdk.ModifierType.SHIFT_MASK)

        # Zoom in/out (Ctrl++/Ctrl+-) vs Enlarge/Shrink Canvas
        # (Ctrl+Shift++/Ctrl+Shift+-, ImageEditorForm.cs:1164-1171)
        # share the same physical +/- key and, on keyboards where
        # typing "+" itself requires Shift, the same GDK keyval too -
        # GDK reports the already-shifted character, unlike Windows'
        # separate KeyCode/Modifiers model, so Shift state (not the
        # keyval alone) is what disambiguates these two pairs.
        if ctrl_held and event.keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            if shift_held:
                self._do_enlarge_canvas()
            else:
                self._do_zoom_in()
            return True
        if ctrl_held and event.keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            if shift_held:
                self._do_shrink_canvas()
            else:
                self._do_zoom_out()
            return True
        if ctrl_held and not shift_held and event.keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self._do_zoom_actual_size()
            return True
        if ctrl_held and not shift_held and event.keyval in (Gdk.KEY_9, Gdk.KEY_KP_9):
            self._do_zoom_best_fit()
            return True

        # H/O/C (Highlight/Obfuscate/Crop) aren't 1:1 Tool mappings the
        # way every key in _TOOL_KEYS is - each is one toolbar button
        # standing in for several modes (Highlight: Text/Area/
        # Grayscale/Magnify; Obfuscate: Solid Fill/Scramble/Pixelize/
        # Blur; Crop: Default/Vertical/Horizontal), with no key of its
        # own for any specific mode, only each one's own Mode dropdown
        # - matching real Windows, whose H/O/C keys
        # (ImageEditorFormKeyDown, ImageEditorForm.cs:1091-1099) fire
        # BtnHighlightClick/BtnObfuscateClick/BtnCropClick, not a mode-
        # specific handler. Each _activate_*_tool() already does
        # exactly the right thing: activates whichever mode is
        # currently prepared, the same as clicking the real toolbar
        # button, and is a correct no-op if that tool's already active
        # (doesn't rely on GTK's set_active() no-refire quirk the way
        # the generic dispatch below does - it explicitly branches on
        # whether the button's already active).
        if not ctrl_held and event.keyval in (Gdk.KEY_h, Gdk.KEY_H):
            self._activate_highlight_tool()
            return True
        if not ctrl_held and event.keyval in (Gdk.KEY_o, Gdk.KEY_O):
            self._activate_obfuscate_tool()
            return True
        if not ctrl_held and event.keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self._activate_crop_tool()
            return True

        tool = _TOOL_KEYS.get(event.keyval)
        if tool is not None and not ctrl_held:
            # set_active(True) fires "toggled", which itself sets
            # self.tool - this just keeps the toolbar's radio buttons
            # in sync with a keyboard-driven tool switch.
            self._tool_buttons[tool].set_active(True)
            return True

        if event.keyval == Gdk.KEY_Delete:
            # Ctrl+Delete clears the whole image (Surface.Clear,
            # ImageEditorForm.cs:1134); plain Delete removes the
            # selected shape (_do_delete) - matching Windows' own
            # ClearToolStripMenuItem shortcut vs the object-delete key.
            if ctrl_held:
                self._do_clear()
            else:
                self._do_delete()
            return True

        # Resize's own shortcut is bare "Z", no modifier
        # (ImageEditorForm.cs:1104's BtnResizeClick binding) - only
        # outside text-editing (already guarded above) and without
        # Ctrl, so it doesn't collide with anything else here.
        if not ctrl_held and event.keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self._do_resize()
            return True

        if not ctrl_held:
            return False
        if event.keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self._do_undo()
            return True
        if event.keyval in (Gdk.KEY_y, Gdk.KEY_Y):
            self._do_redo()
            return True
        if event.keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self._do_copy()
            return True
        if event.keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self._do_save()
            return True
        if event.keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._do_print()
            return True
        if event.keyval in (Gdk.KEY_g, Gdk.KEY_G):
            self._do_grayscale()
            return True
        if event.keyval in (Gdk.KEY_i, Gdk.KEY_I):
            self._do_invert()
            return True
        if event.keyval in (Gdk.KEY_b, Gdk.KEY_B):
            self._do_border()
            return True
        if event.keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self._do_drop_shadow()
            return True
        if event.keyval in (Gdk.KEY_t, Gdk.KEY_T):
            self._do_torn_edge()
            return True
        if event.keyval == Gdk.KEY_comma:
            self._do_rotate_ccw()
            return True
        if event.keyval == Gdk.KEY_period:
            self._do_rotate_cw()
            return True
        return False

    def _on_destroy(self, widget) -> None:
        app = Gio.Application.get_default()
        if app is not None:
            app.unregister_editor_window(self)

    def _on_delete_event(self, _window, _event) -> bool:
        """Faithful port of ImageEditorFormFormClosing (ImageEditorForm.
        cs:1004-1033): with unsaved changes and the "Suppress the save
        dialog when closing the editor" Expert setting off (see
        settings.get_suppress_save_dialog_at_close), asks Yes/No/Cancel
        before closing - "Yes" saves first (and still cancels the close
        if that save itself gets cancelled), "No" closes without saving,
        "Cancel" aborts the close entirely. Windows drops the Cancel
        option specifically when the whole *application* is shutting
        down (ApplicationExitCall/WindowsShutDown/TaskManagerClosing) -
        this port has no such distinction (every close of this window
        arrives as the same GTK delete-event), so Cancel is always
        offered here, matching how Windows itself handles every other
        single-window close.

        Returning True from a "delete-event" handler blocks the close,
        the GTK equivalent of FormClosingEventArgs.Cancel = true.
        """
        if not self.is_modified or get_suppress_save_dialog_at_close():
            return False

        self.present()
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE, text="Do you want to save the screenshot?",
        )
        dialog.set_title("Save image?")
        dialog.add_buttons(
            "Yes", Gtk.ResponseType.YES,
            "No", Gtk.ResponseType.NO,
            "Cancel", Gtk.ResponseType.CANCEL,
        )
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.NO:
            return False
        if response == Gtk.ResponseType.YES:
            return not self._do_save()
        # Cancel, or the dialog's own close button (DELETE_EVENT) - both
        # default to the safe choice: don't close, don't lose anything.
        return True


def open_orcshot_file_in_new_window(path, transient_for: Gtk.Window = None) -> "EditorWindow" | None:
    """Loads an .orcshot file (task #123) into a brand-new
    EditorWindow. Shared by EditorWindow._do_open (File > Open, task
    #129) and app.py's do_open (the GApplication file-open vtable that
    file-manager double-click/"Open With" ultimately triggers) - both
    need identical error handling, and both always want a fresh window
    rather than reusing one. The loaded shapes become the window's own
    initial content, not undoable edits - no mementos are pushed for
    them, so the fresh undo stack starts empty, matching how opening a
    file doesn't leave anything to "undo" back out of.
    """
    try:
        image, layer = load_orcshot_file(path)
    except InvalidOrcshotFileError as exc:
        error_dialog = Gtk.MessageDialog(
            transient_for=transient_for, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text="Couldn't open file",
        )
        error_dialog.format_secondary_text(str(exc))
        error_dialog.run()
        error_dialog.destroy()
        return None

    editor = EditorWindow(image)
    for shape in layer:
        editor.layer.add(shape)
    editor.show_all()
    return editor


def _choose_save_location(parent: Gtk.Window = None) -> None:
    """Lets the user view/change the folder the destination
    picker's silent "Save" (ui/destination_picker.py) and
    EditorWindow's own Save dialog both start from - persisted
    via settings.py, so it's remembered across captures and
    restarts. Module-level (not an EditorWindow method) since
    task #119 made this reachable from the tray icon's own
    Preferences dialog too, with no editor open at all.
    """
    dialog = Gtk.FileChooserDialog(
        title="Screenshot Save Location", transient_for=parent, action=Gtk.FileChooserAction.SELECT_FOLDER
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        "Select", Gtk.ResponseType.OK,
    )
    current = get_output_directory()
    current.mkdir(parents=True, exist_ok=True)
    dialog.set_current_folder(str(current))
    try:
        if dialog.run() == Gtk.ResponseType.OK:
            set_output_directory(Path(dialog.get_filename()))
    finally:
        dialog.destroy()


def show_preferences_dialog(parent: Gtk.Window = None) -> None:
    """Preferences dialog - task #95 part 2 rebuilt this as a
    tabbed Gtk.Notebook matching real Windows' actual SettingsForm
    structure (SettingsForm.Designer.cs's tabcontrol.Controls:
    General/Capture/Output/Destinations/Printer/Plugins/Expert).
    Plugins is dropped (real Windows' tab lists loaded plugin DLLs
    with Configure buttons; this port has exactly one "plugin"-
    shaped thing, ExternalCommand, better served by Destinations
    tab's own Configure button than a whole tab for one item).
    Expert is dropped too, by direflail's own later call - every
    field it held had a real home in one of the other tabs
    (Suppress save dialog -> General>Application Settings, Counter
    -> Output>Preferred File Settings, Printer footer pattern ->
    Printer), and the "I know what I am doing!" gate that used to
    lock them all went with it - they're normal, always-editable
    settings now like everything else. Check for unstable updates
    was removed outright rather than relocated - direflail's own
    call, since Orcshot's own update checker (task #103) has no
    beta channel to gate (GitHub's releases/latest endpoint already
    excludes prereleases on its own - see REQUIREMENTS.md).
    """
    dialog = Gtk.Dialog(title="Preferences", transient_for=parent)
    dialog.set_default_size(480, 420)
    dialog.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
    content = dialog.get_content_area()

    notebook = Gtk.Notebook()
    notebook.append_page(_build_general_settings_tab(dialog), Gtk.Label(label="General"))
    notebook.append_page(_build_capture_settings_tab(), Gtk.Label(label="Capture"))
    notebook.append_page(_build_output_settings_tab(dialog), Gtk.Label(label="Output"))
    notebook.append_page(_build_destinations_settings_tab(dialog), Gtk.Label(label="Destinations"))
    notebook.append_page(_build_printer_settings_tab(), Gtk.Label(label="Printer"))
    content.pack_start(notebook, True, True, 0)

    dialog.show_all()
    dialog.run()
    dialog.destroy()

def _build_general_settings_tab(parent: Gtk.Window) -> Gtk.Box:
    """Matches real Windows' General tab (SettingsForm.Designer.cs:
    480-482's tab_general.Controls: groupbox_network,
    groupbox_hotkeys, groupbox_applicationsettings) - reordered
    (Application Settings, Hotkeys, Network and Updates) per
    direflail's own call, not Windows' own control-declaration
    order.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(12)

    app_frame = Gtk.Frame(label="Application Settings")
    app_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    app_box.set_border_width(8)
    app_frame.add(app_box)

    # Placeholder - task #109 (i18n infrastructure) doesn't exist
    # yet, so there's only ever one real choice. Shown disabled
    # rather than omitted so the real Windows field this
    # corresponds to (combobox_language, groupbox_applicationsettings)
    # has a visible, honest placement already.
    language_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    language_row.pack_start(Gtk.Label(label="Language:"), False, False, 0)
    language_combo = Gtk.ComboBoxText()
    language_combo.append("en", "English")
    language_combo.set_active_id("en")
    language_combo.set_sensitive(False)
    language_combo.set_tooltip_text("Only English is available - see task #109 (i18n infrastructure).")
    language_row.pack_start(language_combo, False, False, 0)
    app_box.pack_start(language_row, False, False, 0)

    # Faithful port of "Icon size" (numericUpdownIconSize,
    # SettingsForm.Designer.cs:330-336, 16-256 step 16) - see
    # settings.get_icon_size's own docstring for the default and
    # ui/icons.py's tool_icon_image for how it's actually applied
    # (bitmap-scaled, not redrawn).
    icon_size_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    icon_size_row.pack_start(Gtk.Label(label="Icon size:"), False, False, 0)
    icon_size_spin = Gtk.SpinButton.new_with_range(16, 256, 16)
    icon_size_spin.set_value(get_icon_size())
    icon_size_spin.set_tooltip_text("Takes effect the next time you open a screenshot.")
    icon_size_spin.connect("value-changed", lambda spin: set_icon_size(spin.get_value_as_int()))
    icon_size_row.pack_start(icon_size_spin, False, False, 0)
    app_box.pack_start(icon_size_row, False, False, 0)

    # Faithful port of "Launch Greenshot on startup"
    # (checkbox_autostartshortcut, SettingsForm.Designer.cs:348) -
    # a direct, immediate toggle, distinct from the Configure
    # Hotkeys button below's first-run-style wizard (which also
    # offers to enable autostart, but only as part of a full
    # reconfigure pass, not a live on/off switch on its own).
    autostart_check = Gtk.CheckButton(label="Launch Orcshot on startup")
    autostart_check.set_active(is_autostart_enabled())

    def on_autostart_toggled(btn) -> None:
        from orcshot.ui.first_run_setup import _default_executable

        if btn.get_active():
            install_autostart_entry(_default_executable())
        else:
            remove_autostart_entry()

    autostart_check.connect("toggled", on_autostart_toggled)
    app_box.pack_start(autostart_check, False, False, 0)

    # Not a Windows setting - "Open in External Editor" itself
    # isn't a Windows feature (see _EXTERNAL_EDITOR_CANDIDATES).
    # No clear Windows tab to match against, kept here as a
    # general app-behavior preference rather than invented a
    # dedicated tab for one control.
    editor_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    editor_row.pack_start(Gtk.Label(label="External Image Editor:"), False, False, 0)
    editor_combo = Gtk.ComboBoxText()
    editor_combo.append(EXTERNAL_EDITOR_AUTO, "Auto (Krita, then GIMP)")
    for name, _path_command, _flatpak_id in _EXTERNAL_EDITOR_CANDIDATES:
        editor_combo.append(name, name)
    current_preference = get_external_editor_preference()
    if editor_combo.set_active_id(current_preference) is False:
        # A stale preference naming a candidate that no longer
        # exists in _EXTERNAL_EDITOR_CANDIDATES - falls back to
        # Auto in the UI (matches _find_external_editor_command's
        # own fallback behavior for the same case) rather than
        # showing nothing selected.
        editor_combo.set_active_id(EXTERNAL_EDITOR_AUTO)
    editor_combo.connect("changed", lambda combo: set_external_editor_preference(combo.get_active_id()))
    editor_row.pack_start(editor_combo, False, False, 0)
    app_box.pack_start(editor_row, False, False, 0)

    # Moved here from the now-removed Expert tab (SettingsForm.
    # Designer.cs's groupbox_expert originally, task #93) - no
    # longer gated behind an "I know what I am doing!" checkbox,
    # per direflail's own call to drop that gate entirely once
    # everything moved to its real home.
    suppress_save_check = Gtk.CheckButton(label="Suppress the save dialog when closing the editor")
    suppress_save_check.set_active(get_suppress_save_dialog_at_close())
    suppress_save_check.connect(
        "toggled", lambda btn: set_suppress_save_dialog_at_close(btn.get_active())
    )
    app_box.pack_start(suppress_save_check, False, False, 0)

    box.pack_start(app_frame, False, False, 0)

    hotkeys_frame = Gtk.Frame(label="Hotkeys")
    hotkeys_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    hotkeys_box.set_border_width(8)
    hotkeys_frame.add(hotkeys_box)
    hotkeys_button = Gtk.Button(label="Configure Hotkeys...")
    # Reuses the existing conflict-detecting setup dialog
    # (ui/first_run_setup.py) rather than rebuilding Windows' own
    # live-capture HotkeyControl widgets inline here - that dialog
    # already covers all 4 bindings plus autostart in one place.
    hotkeys_button.connect(
            "clicked",
            lambda _b: __import__("orcshot.ui.first_run_setup", fromlist=["run_setup_dialog"]).run_setup_dialog(parent),
        )
    hotkeys_box.pack_start(hotkeys_button, False, False, 0)
    box.pack_start(hotkeys_frame, False, False, 0)

    network_frame = Gtk.Frame(label="Network and Updates")
    network_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    network_box.set_border_width(8)
    network_frame.add(network_box)

    # Faithful port of "Use your global proxy?" (UseProxy,
    # ICoreConfiguration.cs:215-217) - see get_use_default_proxy's
    # own docstring for what "default proxy" means on Linux vs.
    # Windows' WinINet.
    proxy_check = Gtk.CheckButton(label="Use system default proxy")
    proxy_check.set_active(get_use_default_proxy())
    proxy_check.connect("toggled", lambda btn: set_use_default_proxy(btn.get_active()))
    network_box.pack_start(proxy_check, False, False, 0)

    interval_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    interval_row.pack_start(Gtk.Label(label="Check for updates every"), False, False, 0)
    interval_spin = Gtk.SpinButton.new_with_range(0, 365, 1)
    interval_spin.set_value(get_update_check_interval_days())
    interval_spin.set_tooltip_text(
        "How often Orcshot checks GitHub for a newer release in the background. "
        "0 = never check, matching Windows' own UpdateCheckInterval semantics."
    )
    interval_spin.connect("value-changed", lambda spin: set_update_check_interval_days(spin.get_value_as_int()))
    interval_row.pack_start(interval_spin, False, False, 0)
    interval_row.pack_start(Gtk.Label(label="days"), False, False, 0)
    network_box.pack_start(interval_row, False, False, 0)
    box.pack_start(network_frame, False, False, 0)

    return box

def _build_capture_settings_tab() -> Gtk.Box:
    """Matches real Windows' Capture tab (groupbox_capture) as far
    as this port can - "Capture mouse cursor" (moved here
    unchanged from the old flat dialog) plus the "zoomer" (region-
    select magnifier) toggle, new this pass.

    Deliberately NOT here, each for its own real reason rather than
    an oversight: Notifications/Play Sound (task #126 - no capture-
    complete notify/sound feature exists in this port at all to
    attach them to). The Window Capture group (groupbox_
    windowscapture's Screen/GDI/Aero/AeroTransparent/Auto capture-
    technique selector, interactive-capture radio, background
    color) - entirely about which Windows graphics API grabs a
    window's pixels, with no Linux equivalent; this port's X11/
    Wayland backends already pick the right mechanism automatically
    per platform, there's no user-facing choice to expose. "Match
    capture size" (groupbox_editor's own checkbox) - this port's
    editor always resizes to match the capture (task #97, a
    deliberate, already-verified, unconditional choice, not
    independently toggleable - "off" would need a real remembered/
    default-size fallback this port doesn't have). Wait time before
    capture (numericUpDownWaitTime) - a real capture-delay timer
    feature that doesn't exist here at all yet, genuinely new scope
    beyond a settings checkbox, not filed as its own task since
    nobody's asked for it.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(12)

    frame = Gtk.Frame(label="Capture")
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    inner.set_border_width(8)
    frame.add(inner)

    # Faithful port of Windows' "Capture mousepointer" checkbox
    # (ICoreConfiguration.cs:79-81, default True) - see
    # ui/capture_modes.py's module docstring for how this
    # interacts with the tray-menu-vs-hotkey asymmetry.
    cursor_check = Gtk.CheckButton(label="Capture mouse cursor")
    cursor_check.set_active(get_capture_mouse_cursor())
    cursor_check.connect("toggled", lambda btn: set_capture_mouse_cursor(btn.get_active()))
    inner.pack_start(cursor_check, False, False, 0)

    # Faithful port of the "zoomer" (ZoomerEnabled,
    # ICoreConfiguration.cs:318-320, default True) - wired into
    # ui/region_select.py (X11) and ui/region_select_wayland.py
    # (Wayland portal fallback); the Wayland Shell-native path
    # (task #82's GJS magnifier) doesn't read this yet, a real
    # documented gap - see get_show_magnifier_while_selecting's
    # own docstring.
    magnifier_check = Gtk.CheckButton(label="Show magnifier while selecting a region")
    magnifier_check.set_active(get_show_magnifier_while_selecting())
    magnifier_check.set_tooltip_text(
        "Applies to X11 and the Wayland portal-fallback path. The Wayland Shell-native picker's own "
        "magnifier doesn't read this setting yet."
    )
    magnifier_check.connect("toggled", lambda btn: set_show_magnifier_while_selecting(btn.get_active()))
    inner.pack_start(magnifier_check, False, False, 0)

    box.pack_start(frame, False, False, 0)
    return box

def _build_output_settings_tab(parent: Gtk.Window) -> Gtk.Box:
    """Matches real Windows' Output tab - groupbox_preferredfilesettings
    (filename pattern, primary format, copy-path-to-clipboard,
    Screenshot Save Location) and groupbox_qualitysettings (reduce
    colors, always show quality dialog, JPEG quality), backed by
    settings.OutputSettings. Every control here reads/writes the
    same OutputSettings instance as a whole (dataclass_replace per
    field) rather than separate get_x/set_x calls, matching how
    the dataclass itself is documented as "always edited together".
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(12)

    def update_output_settings(**changes) -> None:
        set_output_settings(dataclass_replace(get_output_settings(), **changes))

    file_frame = Gtk.Frame(label="Preferred File Settings")
    file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    file_box.set_border_width(8)
    file_frame.add(file_box)

    # Pattern style is a real dropdown, not composed with the other
    # - direflail's own call, after live testing showed why a bare
    # "%" prefix next to ordinary text is inherently self-
    # ambiguous with itself (confirmed live: even a curated "safe"
    # strftime whitelist still let %d eat the "d" out of an
    # ordinary word "done"). One delimiter convention active at a
    # time removes the ambiguity entirely - see
    # core/filename_pattern.py's own module docstring.
    mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    mode_row.pack_start(Gtk.Label(label="Pattern style:"), False, False, 0)
    mode_combo = Gtk.ComboBoxText()
    mode_combo.append(MODE_GREENSHOT, "Greenshot-style (${YYYY})")
    mode_combo.append(MODE_STRFTIME, "strftime (%Y)")
    mode_combo.set_active_id(get_output_settings().filename_pattern_mode)
    mode_combo.connect("changed", lambda combo: update_output_settings(filename_pattern_mode=combo.get_active_id()))
    mode_row.pack_start(mode_combo, False, False, 0)
    file_box.pack_start(mode_row, False, False, 0)

    pattern_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    pattern_row.pack_start(Gtk.Label(label="Filename pattern:"), False, False, 0)
    pattern_entry = Gtk.Entry()
    pattern_entry.set_text(get_output_settings().filename_pattern)
    pattern_entry.set_tooltip_text(
        "Uses whichever style is selected above - the other style's own special characters "
        "are left as plain literal text. Click ? for the token/code list."
    )
    pattern_entry.connect("changed", lambda entry: update_output_settings(filename_pattern=entry.get_text()))
    pattern_row.pack_start(pattern_entry, True, True, 0)
    pattern_help_button = Gtk.Button(label="?")

    def on_pattern_help(_button) -> None:
        if get_output_settings().filename_pattern_mode == MODE_STRFTIME:
            # Standard library strftime - no Windows/Greenshot
            # equivalent to cite, this mode is this port's own
            # addition for Linux/Python users who'd rather use the
            # convention they already know.
            text, secondary = "strftime codes", (
                "Standard Python/C strftime codes, e.g.:\n"
                "%Y year, %y year (2 digits)\n"
                "%m month, %d day\n"
                "%H hour (24h), %I hour (12h), %p AM/PM\n"
                "%M minute, %S second\n"
                "%A/%a weekday name, %B/%b month name\n"
                "%% a literal percent sign\n"
                "\n"
                "No ${...} placeholders in this mode - switch \"Pattern style\" above to use those instead."
            )
        else:
            # Verbatim text real Windows' own "?" button shows
            # (Greenshot/Languages/language-en-US.xml:252-269,
            # settings_message_filenamepattern), adapted for what
            # this port actually supports: ${domain}/${user}/
            # ${hostname} dropped (see this module's own docstring
            # for why).
            text, secondary = "Filename pattern tokens", (
                "The following placeholders are replaced automatically:\n"
                "${YYYY} year, 4 digits\n"
                "${MM} month, 2 digits\n"
                "${DD} day, 2 digits\n"
                "${hh} hour, 2 digits\n"
                "${mm} minute, 2 digits\n"
                "${ss} second, 2 digits\n"
                "${NUM} incrementing number, 6 digits (see Counter below)\n"
                "${RRR...} random alphanumerics, same length as the number of R's\n"
                "${title} capture title, when available\n"
                "\n"
                "No %-codes in this mode - switch \"Pattern style\" above to use those instead."
            )
        info = Gtk.MessageDialog(
            transient_for=parent, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
            text=text, secondary_text=secondary,
        )
        info.run()
        info.destroy()

    pattern_help_button.connect("clicked", on_pattern_help)
    pattern_row.pack_start(pattern_help_button, False, False, 0)
    file_box.pack_start(pattern_row, False, False, 0)

    # Moved here from the now-removed Expert tab (SettingsForm.
    # Designer.cs's groupbox_expert originally, task #93) - lives
    # right under the filename pattern since ${NUM} is this value,
    # not a separate concept.
    counter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    counter_row.pack_start(Gtk.Label(label="Counter (${NUM} in filename):"), False, False, 0)
    counter_spin = Gtk.SpinButton.new_with_range(1, 999999, 1)
    counter_spin.set_value(get_filename_counter())
    counter_spin.connect("value-changed", lambda spin: set_filename_counter(spin.get_value_as_int()))
    counter_row.pack_start(counter_spin, False, False, 0)
    file_box.pack_start(counter_row, False, False, 0)

    format_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    format_row.pack_start(Gtk.Label(label="Primary format:"), False, False, 0)
    format_combo = Gtk.ComboBoxText()
    for value, label in _SAVE_AS_FORMATS:
        format_combo.append(value, label)
    format_combo.set_active_id(get_output_settings().primary_format)
    format_combo.connect("changed", lambda combo: update_output_settings(primary_format=combo.get_active_id()))
    format_row.pack_start(format_combo, False, False, 0)
    file_box.pack_start(format_row, False, False, 0)

    copy_path_check = Gtk.CheckButton(label="Copy file path to clipboard after saving")
    copy_path_check.set_active(get_output_settings().copy_path_to_clipboard)
    copy_path_check.connect("toggled", lambda btn: update_output_settings(copy_path_to_clipboard=btn.get_active()))
    file_box.pack_start(copy_path_check, False, False, 0)

    location_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    location_row.pack_start(Gtk.Label(label="Screenshot Save Location:"), False, False, 0)
    location_label = Gtk.Label(label=str(get_output_directory()))
    location_row.pack_start(location_label, True, True, 0)
    change_button = Gtk.Button(label="Change...")

    def on_change(_button):
        _choose_save_location(parent)
        location_label.set_text(str(get_output_directory()))

    change_button.connect("clicked", on_change)
    location_row.pack_start(change_button, False, False, 0)
    file_box.pack_start(location_row, False, False, 0)

    box.pack_start(file_frame, False, False, 0)

    quality_frame = Gtk.Frame(label="Quality Settings")
    quality_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    quality_box.set_border_width(8)
    quality_frame.add(quality_box)

    # Persisted but not yet applied to a save - see OutputSettings'
    # own docstring for why (no palette-quantization step exists
    # in this port yet, a real, documented gap).
    reduce_colors_check = Gtk.CheckButton(label="Reduce colors to 256 (8-bit)")
    reduce_colors_check.set_active(get_output_settings().reduce_colors)
    reduce_colors_check.set_tooltip_text("Not applied to saves yet - this port has no color-quantization step built.")
    reduce_colors_check.connect("toggled", lambda btn: update_output_settings(reduce_colors=btn.get_active()))
    quality_box.pack_start(reduce_colors_check, False, False, 0)

    prompt_quality_check = Gtk.CheckButton(label="Always show quality dialog before saving")
    prompt_quality_check.set_active(get_output_settings().always_show_quality_dialog)
    prompt_quality_check.connect(
        "toggled", lambda btn: update_output_settings(always_show_quality_dialog=btn.get_active())
    )
    quality_box.pack_start(prompt_quality_check, False, False, 0)

    jpeg_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    jpeg_row.pack_start(Gtk.Label(label="JPEG quality:"), False, False, 0)
    jpeg_spin = Gtk.SpinButton.new_with_range(0, 100, 1)
    jpeg_spin.set_value(get_output_settings().jpeg_quality)
    jpeg_spin.connect("value-changed", lambda spin: update_output_settings(jpeg_quality=spin.get_value_as_int()))
    jpeg_row.pack_start(jpeg_spin, False, False, 0)
    quality_box.pack_start(jpeg_row, False, False, 0)

    box.pack_start(quality_frame, False, False, 0)
    return box

def _build_destinations_settings_tab(dialog: Gtk.Dialog) -> Gtk.Box:
    """Matches real Windows' Destinations tab (groupbox_destination:
    checkbox_picker + listview_destinations). The checked listview
    is real now - every destination show_destination_picker would
    offer (ui/destination_picker.py's _all_destinations, including
    the Office destination if LibreOffice/OpenOffice is detected
    and any configured ExternalCommands), toggled against
    settings.get_excluded_destinations()/set_excluded_destinations().
    checkbox_picker itself (Windows' "always show the picker,
    rather than going straight to a single preferred destination")
    has no equivalent here - this port's hotkeys/tray always open
    the picker already, there's no "skip the picker" mode to
    toggle in the first place.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(12)

    frame = Gtk.Frame(label="Destinations")
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    inner.set_border_width(8)
    frame.add(inner)

    from orcshot.ui.destination_picker import _all_destinations

    store = Gtk.ListStore(bool, str, str)  # enabled, label, id
    excluded = get_excluded_destinations()
    # include_excluded=True - otherwise an unchecked/excluded
    # destination would disappear from its own checklist (the
    # normal, filtered _all_destinations() already hides it).
    for destination_id, label, _handler in _all_destinations(include_excluded=True):
        store.append([destination_id not in excluded, label, destination_id])

    tree_view = Gtk.TreeView(model=store)
    toggle_renderer = Gtk.CellRendererToggle()

    def on_toggled(_renderer, path) -> None:
        store[path][0] = not store[path][0]
        currently_excluded = {row[2] for row in store if not row[0]}
        set_excluded_destinations(currently_excluded)

    toggle_renderer.connect("toggled", on_toggled)
    tree_view.append_column(Gtk.TreeViewColumn("Enabled", toggle_renderer, active=0))
    tree_view.append_column(Gtk.TreeViewColumn("Destination", Gtk.CellRendererText(), text=1))
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_min_content_height(140)
    scroller.add(tree_view)
    inner.pack_start(scroller, True, True, 0)

    external_commands_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    external_commands_row.pack_start(Gtk.Label(label="External Commands:"), False, False, 0)
    manage_commands_button = Gtk.Button(label="Manage...")

    def on_manage_external_commands(_button) -> None:
        from orcshot.ui.external_commands import show_manage_external_commands_dialog

        show_manage_external_commands_dialog(dialog)

    manage_commands_button.connect("clicked", on_manage_external_commands)
    external_commands_row.pack_start(manage_commands_button, False, False, 0)
    inner.pack_start(external_commands_row, False, False, 0)

    box.pack_start(frame, False, False, 0)
    return box

def _build_printer_settings_tab() -> Gtk.Box:
    """Matches real Windows' Printer tab (groupBoxColors +
    groupBoxPrintLayout + checkbox_alwaysshowprintoptionsdialog,
    SettingsForm.Designer.cs:815-978) - sets real *default*
    settings.PrintOptions, the same dataclass ui/printing.py's own
    per-print-job dialog already reads/writes. Each control here
    persists on change directly (matching Output tab's own
    pattern), not through an OK/Cancel flow - these are defaults,
    not a one-shot decision the way the per-job dialog's fields
    are.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(12)

    def update_print_options(**changes) -> None:
        set_print_options(dataclass_replace(get_print_options(), **changes))

    options = get_print_options()

    layout_frame = Gtk.Frame(label="Page Layout Settings")
    layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    layout_box.set_border_width(8)

    shrink_check = Gtk.CheckButton(label="Shrink printout to fit paper size")
    shrink_check.set_active(options.allow_shrink)
    shrink_check.connect("toggled", lambda btn: update_print_options(allow_shrink=btn.get_active()))
    layout_box.pack_start(shrink_check, False, False, 0)

    enlarge_check = Gtk.CheckButton(label="Enlarge printout to fit paper size")
    enlarge_check.set_active(options.allow_enlarge)
    enlarge_check.connect("toggled", lambda btn: update_print_options(allow_enlarge=btn.get_active()))
    layout_box.pack_start(enlarge_check, False, False, 0)

    rotate_check = Gtk.CheckButton(label="Rotate printout to page orientation")
    rotate_check.set_active(options.allow_rotate)
    rotate_check.connect("toggled", lambda btn: update_print_options(allow_rotate=btn.get_active()))
    layout_box.pack_start(rotate_check, False, False, 0)

    center_check = Gtk.CheckButton(label="Center printout on page")
    center_check.set_active(options.center)
    center_check.connect("toggled", lambda btn: update_print_options(center=btn.get_active()))
    layout_box.pack_start(center_check, False, False, 0)

    footer_check = Gtk.CheckButton(label="Print date / time at bottom of page")
    footer_check.set_active(options.footer)
    footer_check.connect("toggled", lambda btn: update_print_options(footer=btn.get_active()))
    layout_box.pack_start(footer_check, False, False, 0)

    # Moved here from the now-removed Expert tab (SettingsForm.
    # Designer.cs's groupbox_expert originally, task #93) - the
    # pattern for the checkbox above, not a separate concept.
    footer_pattern_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    footer_pattern_row.pack_start(Gtk.Label(label="Footer pattern:"), False, False, 0)
    footer_pattern_entry = Gtk.Entry()
    footer_pattern_entry.set_text(get_footer_pattern())
    footer_pattern_entry.set_tooltip_text(
        "A Python strftime format, e.g. %B %d, %Y %I:%M %p - printed at the bottom of the page."
    )
    footer_pattern_entry.connect("changed", lambda entry: set_footer_pattern(entry.get_text()))
    footer_pattern_row.pack_start(footer_pattern_entry, True, True, 0)
    layout_box.pack_start(footer_pattern_row, False, False, 0)

    layout_frame.add(layout_box)
    box.pack_start(layout_frame, False, False, 0)

    color_frame = Gtk.Frame(label="Color Settings")
    color_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    color_box.set_border_width(8)

    color_radio = Gtk.RadioButton.new_with_label(None, "Full color print")
    grayscale_radio = Gtk.RadioButton.new_with_label_from_widget(color_radio, "Force grayscale printing")
    monochrome_radio = Gtk.RadioButton.new_with_label_from_widget(color_radio, "Force black/white printing")
    if options.monochrome:
        monochrome_radio.set_active(True)
    elif options.grayscale:
        grayscale_radio.set_active(True)
    else:
        color_radio.set_active(True)

    def on_color_mode_toggled(_btn) -> None:
        update_print_options(grayscale=grayscale_radio.get_active(), monochrome=monochrome_radio.get_active())

    for radio in (color_radio, grayscale_radio, monochrome_radio):
        radio.connect("toggled", on_color_mode_toggled)
        color_box.pack_start(radio, False, False, 0)

    invert_check = Gtk.CheckButton(label="Print with inverted colors")
    invert_check.set_active(options.inverted)
    invert_check.connect("toggled", lambda btn: update_print_options(inverted=btn.get_active()))
    color_box.pack_start(invert_check, False, False, 0)

    color_frame.add(color_box)
    box.pack_start(color_frame, False, False, 0)

    prompt_check = Gtk.CheckButton(label="Show print options dialog every time an image is printed")
    prompt_check.set_active(options.prompt_options)
    prompt_check.connect("toggled", lambda btn: update_print_options(prompt_options=btn.get_active()))
    box.pack_start(prompt_check, False, False, 0)

    return box
