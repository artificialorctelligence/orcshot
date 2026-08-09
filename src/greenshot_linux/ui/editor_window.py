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
from dataclasses import replace as dataclass_replace
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

from greenshot_linux.capture.clipboard import ClipboardBackend
from greenshot_linux.core.crop import autocrop_rect, crop_to_rect
from greenshot_linux.core.drawing import Layer
from greenshot_linux.core.effects import (
    add_border_image,
    clear_image,
    drop_shadow_image,
    enlarge_canvas_image,
    grayscale_image,
    invert_image,
    remove_transparency_image,
    rotate_90_image,
)
from greenshot_linux.core.history import (
    AddElementMemento,
    BackgroundChangeMemento,
    DeleteElementMemento,
    ElementChangeMemento,
    UndoRedoStack,
)
from greenshot_linux.core.shapes import (
    ImageShape, ObfuscateMode, ObfuscateShape, ShapeStyle, SpeechBubbleShape, StepLabelShape, SvgShape, TextShape,
)
from greenshot_linux.settings import (
    EXTERNAL_EDITOR_AUTO,
    get_capture_mouse_cursor,
    get_external_editor_preference,
    get_output_directory,
    set_capture_mouse_cursor,
    set_external_editor_preference,
    set_output_directory,
)
from greenshot_linux.resources import LOGO_PATH
from greenshot_linux.core.tools import (
    STYLE_FIELD_FILL_COLOR,
    STYLE_FIELD_LINE_COLOR,
    STYLE_FIELD_LINE_THICKNESS,
    STYLE_FIELD_OBFUSCATE_AMOUNT,
    STYLE_FIELD_OBFUSCATE_FILL_COLOR,
    STYLE_FIELD_OBFUSCATE_MODE,
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
from greenshot_linux.core.zoom import (
    ACTUAL_SIZE_ZOOM,
    ZOOM_LEVELS,
    best_fit_zoom,
    optimal_window_size,
    zoom_in,
    zoom_out,
    zoom_percent_label,
)
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface
from greenshot_linux.ui.color_dialog import show_color_picker
from greenshot_linux.ui.composite import composite_to_numpy
from greenshot_linux.ui.effects import resize_image, torn_edge_image
from greenshot_linux.ui.gdk_convert import pixbuf_to_numpy
from greenshot_linux.ui.file_export import save_image_to_file
from greenshot_linux.ui.icons import tool_icon_image
from greenshot_linux.ui.printing import print_image
from greenshot_linux.ui.render import bubble_corner_radius, render_shape, vertical_text_offset

# ZoomSetValue's 100ms Ctrl+wheel throttle (ImageEditorForm.cs:96,1185-1187)
_ZOOM_WHEEL_THROTTLE_SECONDS = 0.1
# ImageEditorForm's MinimumSize (ImageEditorForm.Designer.cs)
_MIN_WINDOW_WIDTH = 650
_MIN_WINDOW_HEIGHT = 530

_TOOL_KEYS = {
    Gdk.KEY_1: Tool.RECTANGLE,
    Gdk.KEY_2: Tool.ELLIPSE,
    Gdk.KEY_3: Tool.LINE,
    Gdk.KEY_4: Tool.ARROW,
    Gdk.KEY_5: Tool.FREEHAND,
    Gdk.KEY_6: Tool.PIXELIZE,
    Gdk.KEY_7: Tool.BLUR,
    Gdk.KEY_8: Tool.TEXT,
    Gdk.KEY_9: Tool.SPEECH_BUBBLE,
    Gdk.KEY_0: Tool.STEP_LABEL,
    # Select has no dedicated key yet - no clear Windows precedent to
    # port, and every unclaimed letter is a fresh, undocumented
    # convention rather than a faithful port, so it's toolbar-only for
    # now pending explicit direction. "M" for Emoji does have Windows
    # precedent (ImageEditorForm.Designer.cs: btnEmoji.Text = "Emoji
    # (M)") and doesn't collide with any existing Ctrl+ binding.
    Gdk.KEY_m: Tool.EMOJI,
    Gdk.KEY_M: Tool.EMOJI,
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

_TOOL_LABELS = [
    (Tool.SELECT, "Select"),
    None,
    (Tool.RECTANGLE, "Rectangle"),
    (Tool.ELLIPSE, "Ellipse"),
    (Tool.LINE, "Line"),
    (Tool.ARROW, "Arrow"),
    (Tool.FREEHAND, "Freehand"),
    _OBFUSCATE_GROUP,
    (Tool.TEXT, "Text"),
    (Tool.SPEECH_BUBBLE, "Speech Bubble"),
    (Tool.STEP_LABEL, "Step Label"),
    (Tool.EMOJI, "Emoji"),
]

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


class EditorWindow(Gtk.Window):
    def __init__(self, image: np.ndarray, clipboard_backend: ClipboardBackend = None):
        super().__init__(title="Greenshot Linux")
        self._base_image = image
        self._surface = numpy_to_cairo_surface(image)
        height, width = image.shape[:2]

        if clipboard_backend is None:
            from greenshot_linux.capture.backend_select import default_clipboard_backend

            clipboard_backend = default_clipboard_backend()
        self._clipboard = clipboard_backend

        self.layer = Layer()
        self.undo_redo = UndoRedoStack()
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
        # self._selected_shape just below sets its own backing field
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
        # Bypasses the selected_shape property below - same reason the
        # base_image property's docstring gives for __init__ setting
        # self._base_image directly: its setter refreshes the
        # obfuscate-amount label, but _obfuscate_amount_label doesn't
        # exist yet this early in construction.
        self._selected_shape = None
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
        # A single cut/copied shape (Windows' per-shape Cut/Copy/Paste,
        # distinct from _do_copy's whole-image-to-system-clipboard) -
        # not the system clipboard, just in-editor state.
        self._shape_clipboard = None

        # drag-to-create state
        self._drag_origin = None
        self._drag_points = None
        self._drag_shape = None

        # click-to-move state
        self._move_shape = None
        self._move_origin = None
        self._move_preview = None

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
        # Registers with the running GreenshotApplication (if any) so
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
        """
        super().show_all()
        self._refresh_style_panel()

    @property
    def selected_shape(self):
        return self._selected_shape

    @selected_shape.setter
    def selected_shape(self, shape) -> None:
        """Keeps the style panel in sync with whichever shape/tool is
        actually relevant right now - see _refresh_style_panel.
        Centralizing this in the property setter (rather than a call
        at each of the many call sites that assign self.selected_shape
        throughout this file) means it can't be missed by a future
        one. Bypassed by __init__ - see self._selected_shape's own
        comment there.
        """
        self._selected_shape = shape
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
        """
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
        shape = self._selected_shape
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
        shape = self._selected_shape
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

    def _build_menu_bar(self) -> Gtk.MenuBar:
        """File/Edit/Object/Help, matching Windows Greenshot's editor
        menu structure - only the items applicable to this port's
        actual feature set (no Office/OneDrive/cloud destinations,
        already out of scope - see REQUIREMENTS.md's "Explicitly cut"
        section). Duplicates the toolbar/keyboard-shortcut actions
        rather than replacing them - matching Windows, which has both.
        """
        menu_bar = Gtk.MenuBar()

        def add_menu(label: str) -> Gtk.Menu:
            menu = Gtk.Menu()
            item = Gtk.MenuItem(label=label)
            item.set_submenu(menu)
            menu_bar.append(item)
            return menu

        def add_item(menu: Gtk.Menu, label: str, handler) -> None:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i: handler())
            menu.append(item)

        file_menu = add_menu("File")
        add_item(file_menu, "Save...", self._do_save)
        add_item(file_menu, "Print...", self._do_print)
        file_menu.append(Gtk.SeparatorMenuItem())
        add_item(file_menu, "Insert Image...", self._do_insert_image)
        add_item(file_menu, "Insert SVG...", self._do_insert_svg)
        file_menu.append(Gtk.SeparatorMenuItem())
        add_item(file_menu, "Screenshot Save Location...", self._do_choose_save_location)
        file_menu.append(Gtk.SeparatorMenuItem())
        add_item(file_menu, "Close", self.close)

        edit_menu = add_menu("Edit")
        add_item(edit_menu, "Undo", self._do_undo)
        add_item(edit_menu, "Redo", self._do_redo)
        edit_menu.append(Gtk.SeparatorMenuItem())
        add_item(edit_menu, "Copy", self._do_copy)

        object_menu = add_menu("Object")
        add_item(object_menu, "Delete", self._do_delete)
        object_menu.append(Gtk.SeparatorMenuItem())
        add_item(object_menu, "Bring to Front", self._do_bring_to_front)
        add_item(object_menu, "Send to Back", self._do_send_to_back)

        # Whole-image effects (core/effects.py + ui/effects.py) -
        # Windows exposes these via a toolbar split-button + separate
        # toolbar buttons (toolStripSplitButton1/btnCrop/rotateCw.../
        # btnResize, ImageEditorForm.Designer.cs:334-355,491-499), not
        # a menu - grouped into a dedicated menu here instead, matching
        # how this port already puts some toolbar-button actions
        # (Insert Image, Print) in File instead. "Enlarge Canvas"/
        # "Shrink Canvas" deliberately have no item here - Windows
        # itself has no menu/toolbar entry for either, keyboard-only
        # (Ctrl+Shift++ / Ctrl+Shift+-, see _on_key_press).
        image_menu = add_menu("Image")
        add_item(image_menu, "Rotate Clockwise", self._do_rotate_cw)
        add_item(image_menu, "Rotate Counterclockwise", self._do_rotate_ccw)
        add_item(image_menu, "Resize...", self._do_resize)
        image_menu.append(Gtk.SeparatorMenuItem())
        add_item(image_menu, "Grayscale", self._do_grayscale)
        add_item(image_menu, "Invert Colors", self._do_invert)
        add_item(image_menu, "Remove Transparency...", self._do_remove_transparency)
        image_menu.append(Gtk.SeparatorMenuItem())
        add_item(image_menu, "Border", self._do_border)
        add_item(image_menu, "Drop Shadow", self._do_drop_shadow)
        add_item(image_menu, "Drop Shadow Settings...", self._do_drop_shadow_settings)
        add_item(image_menu, "Torn Edge", self._do_torn_edge)
        add_item(image_menu, "Torn Edge Settings...", self._do_torn_edge_settings)
        image_menu.append(Gtk.SeparatorMenuItem())
        add_item(image_menu, "Clear", self._do_clear)

        help_menu = add_menu("Help")
        add_item(help_menu, "About Greenshot Linux", self._do_show_about)

        return menu_bar

    def _do_show_about(self) -> None:
        dialog = Gtk.AboutDialog(transient_for=self)
        dialog.set_program_name("Greenshot Linux")
        dialog.set_comments("A Linux Mint port of Greenshot")
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
            tool, label = entry
            button = Gtk.RadioButton.new_from_widget(group_leader)
            if group_leader is None:
                group_leader = button
            button.set_mode(False)  # flat icon toggle, not a radio-circle-plus-label
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_image(tool_icon_image(tool, color=icon_color))
            button.set_tooltip_text(label)
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
        button.set_image(tool_icon_image(Tool.PIXELIZE, color=icon_color))
        button.set_tooltip_text("Obfuscate")
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

        Otherwise, if Obfuscate already *is* the active tool (and
        nothing's selected), its own fields still update live (the
        amount label swaps between "Blur Radius:"/"Pixel Size:"
        immediately) - that mirrors Windows' FieldAggregator reflecting
        the newly prepared filter's fields right away, even though
        nothing here changes *whether* Obfuscate is active.
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
        elif self.tool in _OBFUSCATE_MODE_ORDER:
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

    def _select_and_activate_obfuscate_mode(self, mode: Tool) -> None:
        """The 6/7 keyboard shortcuts (_TOOL_KEYS) - unlike the mode
        dropdown, a keyboard shortcut is expected to actually do
        something immediately, so this both prepares the mode and
        activates the tool in one step. No direct Windows equivalent:
        Windows has only one Obfuscate drawing mode with no per-
        sub-mode shortcut, so there's nothing to be unfaithful to here
        - this is this port's own convenience addition.
        """
        self._set_obfuscate_mode(mode)
        self._activate_obfuscate_tool()

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

        add_button("document-save-symbolic", "Save", self._do_save)
        add_button("edit-copy-symbolic", "Copy Image to Clipboard", self._do_copy)
        add_button("document-print-symbolic", "Print", self._do_print)

        toolbar.insert(Gtk.SeparatorToolItem(), -1)
        add_button("edit-delete-symbolic", "Delete", self._do_delete)

        toolbar.insert(Gtk.SeparatorToolItem(), -1)
        add_button("edit-cut-symbolic", "Cut", self._do_cut_shape)
        add_button("edit-copy-symbolic", "Copy Shape", self._do_copy_shape)
        add_button("edit-paste-symbolic", "Paste Shape", self._do_paste_shape)
        add_button("edit-undo-symbolic", "Undo", self._do_undo)
        add_button("edit-redo-symbolic", "Redo", self._do_redo)

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
        shape = self._selected_shape
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

    def _do_delete(self) -> None:
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        shape = self.selected_shape
        self.layer.remove(shape)
        self.undo_redo.push(DeleteElementMemento(self.layer, shape))
        self.selected_shape = None
        self._drawing_area.queue_draw()

    def _do_cut_shape(self) -> None:
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        self._shape_clipboard = self.selected_shape
        self._do_delete()

    def _do_copy_shape(self) -> None:
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        self._shape_clipboard = self.selected_shape

    def _do_paste_shape(self) -> None:
        # Pastes the last cut/copied *shape*, not an image from the
        # real system clipboard - Windows' Paste can also embed an
        # image from the system clipboard, but ClipboardBackend here
        # is write-only (set_image), with no read-back support built
        # yet, so that half is out of scope for now.
        self._commit_text_editing_if_active()
        if self._shape_clipboard is None:
            return
        pasted = translate_shape(self._shape_clipboard, 20, 20)
        self.layer.add(pasted)
        self.selected_shape = pasted
        self.undo_redo.push(AddElementMemento(self.layer, pasted))
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

    def _do_send_to_back(self) -> None:
        self._commit_text_editing_if_active()
        if self.selected_shape is None:
            return
        self.layer.send_to_back([self.selected_shape])
        self._drawing_area.queue_draw()

    def _composited_image(self) -> np.ndarray:
        return composite_to_numpy(self._base_image, self.layer)

    def _next_step_number(self) -> int:
        return sum(1 for shape in self.layer if isinstance(shape, StepLabelShape)) + 1

    def _do_copy(self) -> None:
        self._commit_text_editing_if_active()
        self._clipboard.set_image(self._composited_image())

    def _do_save(self) -> None:
        self._commit_text_editing_if_active()
        dialog = Gtk.FileChooserDialog(
            title="Save Screenshot", transient_for=self, action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        dialog.set_current_folder(str(get_output_directory()))
        dialog.set_current_name("screenshot.png")
        dialog.set_do_overwrite_confirmation(True)
        try:
            if dialog.run() == Gtk.ResponseType.OK:
                save_image_to_file(self._composited_image(), dialog.get_filename())
        finally:
            dialog.destroy()

    def _do_choose_save_location(self) -> None:
        """Lets the user view/change the folder the destination
        picker's silent "Save" (ui/destination_picker.py) and this
        window's own Save dialog both start from - persisted via
        settings.py, so it's remembered across captures and restarts.
        """
        dialog = Gtk.FileChooserDialog(
            title="Screenshot Save Location", transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER
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

    def _do_print(self) -> None:
        self._commit_text_editing_if_active()
        print_image(self._composited_image(), parent=self)

    def _do_show_settings(self) -> None:
        """A minimal Preferences dialog - matches Windows' real
        Settings button (btnSettings, ImageEditorForm.Designer.cs),
        but there isn't much to configure here yet, so it's a small
        home for the existing save-location control rather than a
        Windows-parity settings surface. Grows as more settings show
        up (see task list).
        """
        self._commit_text_editing_if_active()
        dialog = Gtk.Dialog(title="Preferences", transient_for=self)
        dialog.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(6)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Screenshot Save Location:"), False, False, 0)
        location_label = Gtk.Label(label=str(get_output_directory()))
        row.pack_start(location_label, True, True, 0)
        change_button = Gtk.Button(label="Change...")

        def on_change(_button):
            self._do_choose_save_location()
            location_label.set_text(str(get_output_directory()))

        change_button.connect("clicked", on_change)
        row.pack_start(change_button, False, False, 0)
        content.pack_start(row, False, False, 0)

        # Faithful port of Windows' "Capture mousepointer" checkbox
        # (ICoreConfiguration.cs:79-81, default True) - see
        # ui/capture_modes.py's module docstring for how this
        # interacts with the tray-menu-vs-hotkey asymmetry.
        cursor_check = Gtk.CheckButton(label="Capture mouse cursor")
        cursor_check.set_active(get_capture_mouse_cursor())
        cursor_check.connect("toggled", lambda btn: set_capture_mouse_cursor(btn.get_active()))
        content.pack_start(cursor_check, False, False, 0)

        # Not a Windows setting - "Open in External Editor" itself
        # isn't a Windows feature (see _EXTERNAL_EDITOR_CANDIDATES).
        # IDs match settings.get/set_external_editor_preference's
        # values directly (EXTERNAL_EDITOR_AUTO, or a candidate name).
        editor_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        editor_row.pack_start(Gtk.Label(label="External Image Editor:"), False, False, 0)
        editor_combo = Gtk.ComboBoxText()
        editor_combo.append(EXTERNAL_EDITOR_AUTO, "Auto (Krita, then GIMP)")
        for name, _path_command, _flatpak_id in self._EXTERNAL_EDITOR_CANDIDATES:
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
        content.pack_start(editor_row, False, False, 0)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    # Not a Windows feature - Windows has no "open in an external
    # editor" destination. A new addition, not a port, per explicit
    # request. Krita is tried first since it was specifically
    # requested, with GIMP as a fallback (overridable - see
    # settings.get_external_editor_preference and _do_show_settings).
    # (name, PATH command, Flatpak app ID) - checks both, since Flatpak
    # is how at least one of these is commonly installed on Mint
    # (confirmed live: this dev machine has Krita only via Flatpak, not
    # on PATH - a plain shutil.which("krita") check alone would have
    # missed it).
    _EXTERNAL_EDITOR_CANDIDATES = (
        ("Krita", "krita", "org.kde.krita"),
        ("GIMP", "gimp", "org.gimp.GIMP"),
    )

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
        for name, path_command, flatpak_id in self._EXTERNAL_EDITOR_CANDIDATES:
            if name != preferred:
                continue
            command = self._command_for_candidate(path_command, flatpak_id, flatpak_apps)
            if command is not None:
                return command
        for _name, path_command, flatpak_id in self._EXTERNAL_EDITOR_CANDIDATES:
            command = self._command_for_candidate(path_command, flatpak_id, flatpak_apps)
            if command is not None:
                return command
        return None

    @staticmethod
    def _external_editor_cache_dir() -> Path:
        """Where the exported temp PNG for "Open in External Editor"
        lives - $XDG_CACHE_HOME/greenshot-linux, *not* system /tmp.

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
        (settings.config_file_path).
        """
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        directory = cache_home / "greenshot-linux"
        # mode=0o700 rather than relying on umask: the exported PNGs
        # here can contain sensitive screen content, and while
        # tempfile.mkstemp already forces 0600 on each individual file
        # regardless of umask, the *directory* itself would otherwise
        # inherit whatever the umask allows (typically 0755 -
        # world-listable) - restricting it too means even filenames/
        # mtimes in here aren't enumerable by another local user on a
        # system with looser-than-default home permissions. Only takes
        # effect on first creation - doesn't retroactively fix a
        # pre-existing directory from before this restriction existed.
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return directory

    def _do_open_in_external_editor(self) -> None:
        self._commit_text_editing_if_active()
        command = self._find_external_editor_command()
        if command is None:
            dialog = Gtk.MessageDialog(
                transient_for=self, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                text="No external image editor found",
            )
            names = ", ".join(name for name, _, _ in self._EXTERNAL_EDITOR_CANDIDATES)
            dialog.format_secondary_text(f"Tried: {names} (checked both PATH and Flatpak). Install one of these to use this button.")
            dialog.run()
            dialog.destroy()
            return
        # Cleans up the previous export before writing a new one -
        # unique filenames (not one fixed path) avoid a second export
        # clobbering a file a still-open first editor session has
        # already loaded; deleting the old one here (rather than never
        # cleaning up) avoids that pile growing unbounded across a long
        # editing session, since ~/.cache/greenshot-linux isn't
        # OS-managed transient storage the way /tmp is.
        previous = getattr(self, "_external_editor_temp_path", None)
        if previous is not None:
            previous.unlink(missing_ok=True)
        fd, path_str = tempfile.mkstemp(suffix=".png", prefix="greenshot-linux-", dir=str(self._external_editor_cache_dir()))
        os.close(fd)
        path = Path(path_str)
        self._external_editor_temp_path = path
        save_image_to_file(self._composited_image(), path)
        subprocess.Popen(command + [str(path)])

    _HELP_TEXT = (
        "Tools\n"
        "  1–0   Select a drawing tool\n"
        "  M      Emoji tool\n"
        "\n"
        "Editing\n"
        "  Delete           Delete the selected shape\n"
        "  Double-click     Re-edit an existing text/speech bubble/emoji shape\n"
        "  Enter            Commit a text/speech bubble/emoji edit\n"
        "  Escape           Cancel a text/speech bubble/emoji edit\n"
        "\n"
        "Actions\n"
        "  Ctrl+Z / Ctrl+Y  Undo / Redo\n"
        "  Ctrl+C           Copy the whole image to the clipboard\n"
        "  Ctrl+S           Save\n"
        "  Ctrl+P           Print\n"
    )

    def _do_show_help(self) -> None:
        self._commit_text_editing_if_active()
        dialog = Gtk.Dialog(title="Greenshot Linux Help", transient_for=self)
        dialog.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        content = dialog.get_content_area()
        content.set_border_width(12)
        label = Gtk.Label(label=self._HELP_TEXT)
        label.set_xalign(0)
        label.set_selectable(True)
        content.pack_start(label, True, True, 0)
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

    def _selected_display_shape(self):
        """The selected shape's current bounds for handle drawing,
        following whichever live preview (if any) applies."""
        if self._resize_shape is not None:
            return self._resize_preview or self._resize_shape
        if self._move_shape is not None and self._move_shape is self.selected_shape:
            return self._move_preview or self._move_shape
        return self.selected_shape

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
        Designer.cs:59,224,271-277). The zoom control lives here, not
        in the menu bar - Windows has no top-level zoom menu either,
        only this dropdown (opening the same zoomMenuStrip) plus
        keyboard shortcuts and Ctrl+wheel.
        """
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(2)

        img_h, img_w = self._base_image.shape[:2]
        self._dimensions_label = Gtk.Label(label=f"{img_w} x {img_h}")
        bar.pack_start(self._dimensions_label, False, False, 4)

        zoom_menu = Gtk.Menu()

        def add_zoom_item(label: str, handler) -> None:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i: handler())
            zoom_menu.append(item)

        add_zoom_item("Zoom In", self._do_zoom_in)
        add_zoom_item("Zoom Out", self._do_zoom_out)
        add_zoom_item("Best Fit", self._do_zoom_best_fit)
        zoom_menu.append(Gtk.SeparatorMenuItem())
        for level in ZOOM_LEVELS:
            label = zoom_percent_label(level) + (" - Actual Size" if level == ACTUAL_SIZE_ZOOM else "")
            add_zoom_item(label, lambda level=level: self._set_zoom(level))
        zoom_menu.show_all()

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
    # full per-effect citation trail). Grouped in a dedicated "Image"
    # menu below (_build_menu_bar) rather than Windows' toolbar split-
    # button - this port already uses a menu bar where Windows uses
    # toolbar buttons for several other things (Insert Image, Print),
    # so that's the established, consistent choice here, not a new one.

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
            if shape is self._move_shape and self._move_preview is not None:
                render_shape(ctx, self._move_preview, base_image=self._base_image)
            elif shape is self._resize_shape and self._resize_preview is not None:
                render_shape(ctx, self._resize_preview, base_image=self._base_image)
            else:
                render_shape(ctx, shape, base_image=self._base_image)
        if self._drag_shape is not None:
            render_shape(ctx, self._drag_shape, base_image=self._base_image)

        display_shape = self._selected_display_shape()
        if display_shape is not None:
            self._draw_handles(ctx, display_shape)
        return False

    def _on_button_press(self, widget, event):
        self._commit_text_editing_if_active()
        offset_x, offset_y = self._content_offset()
        # InverseZoomMouseCoordinates (Surface.cs:1469-1470): screen/
        # widget pixels back into unscaled image-space coordinates, so
        # drawing/hit-testing stays accurate at any zoom level.
        zoom = float(self._zoom)
        x, y = int((event.x - offset_x) / zoom), int((event.y - offset_y) / zoom)

        if self.selected_shape is not None:
            handle = handle_at(self.selected_shape, x, y)
            if handle is not None:
                self._resize_shape = self.selected_shape
                self._resize_handle = handle
                widget.queue_draw()
                return True

        hit = self.layer.topmost_at(x, y)

        if hit is not None and isinstance(hit, (TextShape, SpeechBubbleShape)) and event.type == Gdk.EventType._2BUTTON_PRESS:
            # A double-click's second press follows a first (single)
            # press that already ran the branch below and may have
            # started a move - cancel that, double-click means edit.
            self._move_shape = None
            self._move_origin = None
            self.selected_shape = hit
            self._editing_text_shape = hit
            self._editing_original_shape = hit
            self._show_text_editor()
            widget.queue_draw()
            return True

        if hit is not None:
            self.selected_shape = hit
            self._move_shape = hit
            self._move_origin = (x, y)
        elif self.tool is not Tool.SELECT:
            # Select (Windows' "Cursor" tool) only selects/moves/
            # resizes existing shapes - clicking empty space with it
            # active does nothing, unlike every drawing tool.
            self.selected_shape = None
            self._drag_origin = (x, y)
            if self.tool is Tool.FREEHAND:
                self._drag_points = [(x, y)]
                self._drag_shape = create_freehand_shape(self._drag_points, self._style_for_tool(self.tool))
            else:
                self._drag_shape = create_shape_from_drag(
                    self.tool, (x, y), (x, y), self._style_for_tool(self.tool),
                    amount=self._default_obfuscate_amount, fill_color=self._default_obfuscate_fill_color,
                )
        else:
            self.selected_shape = None
        widget.queue_draw()
        return True

    def _on_motion(self, widget, event):
        offset_x, offset_y = self._content_offset()
        # InverseZoomMouseCoordinates (Surface.cs:1469-1470): screen/
        # widget pixels back into unscaled image-space coordinates, so
        # drawing/hit-testing stays accurate at any zoom level.
        zoom = float(self._zoom)
        x, y = int((event.x - offset_x) / zoom), int((event.y - offset_y) / zoom)
        if self._resize_shape is not None:
            self._resize_preview = resize_shape(self._resize_shape, self._resize_handle, x, y)
            widget.queue_draw()
            return True
        if self._move_shape is not None:
            dx, dy = x - self._move_origin[0], y - self._move_origin[1]
            self._move_preview = translate_shape(self._move_shape, dx, dy)
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
        if self._move_shape is not None:
            dx, dy = x - self._move_origin[0], y - self._move_origin[1]
            if dx == 0 and dy == 0:
                # a click without a drag - e.g. just selecting a shape,
                # or the first press of what turns into a double-click.
                # Nothing moved; pushing a memento here would only
                # clutter undo history with a no-op step.
                self.selected_shape = self._move_shape
            else:
                final = translate_shape(self._move_shape, dx, dy)
                self.layer.replace(self._move_shape, final)
                self.undo_redo.push(ElementChangeMemento(self.layer, before=self._move_shape, after=final))
                self.selected_shape = final
            self._move_shape = None
            self._move_origin = None
            self._move_preview = None
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

        # Checked before _TOOL_KEYS: plain 0/9 switch tools (Step
        # Label/Speech Bubble), but Ctrl+0/Ctrl+9 are zoom shortcuts
        # (Actual Size/Best Fit, ImageEditorForm.cs:1153-1157) - since
        # GDK reports the same base keyval regardless of Ctrl, the
        # tool-switch lookup below would otherwise swallow them first.
        #
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

        tool = _TOOL_KEYS.get(event.keyval)
        if tool is not None and not ctrl_held:
            if tool in (Tool.PIXELIZE, Tool.BLUR):
                # Both keys route through the same shared Obfuscate
                # button (self._tool_buttons[Tool.PIXELIZE] is
                # self._tool_buttons[Tool.BLUR]) - set_active(True)
                # alone wouldn't reliably pick the right mode if it's
                # already the active tool (see
                # _select_and_activate_obfuscate_mode).
                self._select_and_activate_obfuscate_mode(tool)
            else:
                # set_active(True) fires "toggled", which itself sets
                # self.tool - this just keeps the toolbar's radio
                # buttons in sync with a keyboard-driven tool switch.
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
