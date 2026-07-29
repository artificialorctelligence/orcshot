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
editing mode where key presses append/backspace the shape's text
directly (no GtkEntry overlay - the shape re-renders live through the
normal Cairo pipeline on every keystroke); Enter or clicking elsewhere
commits, Escape or committing with empty text discards the shape.
While editing, every other key handler (tool switching, undo/redo,
copy/save/print) is suppressed so typing "z" doesn't trigger undo.
No visible text cursor/caret (the live-updating text itself is the
only feedback that typing is registering).

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
shadow) updates self._default_style, affecting shapes created *after*
a change; if a shape is currently selected when a control changes, it
gets restyled too (one ElementChangeMemento per control change) -
except Obfuscate/Icon/Cursor/Image/Svg, none of which have a style
field to change. The panel doesn't sync *from* a selection though -
clicking an existing shape doesn't update the controls to show its
current style, only editing them pushes a change out. A separate
"Obfuscate Amount" spinner (blur radius / pixel size, self._default_
obfuscate_amount) works the same way but only applies to Pixelize/Blur
shapes - it's threaded through create_shape_from_drag's amount
parameter regardless of the current tool (ignored for every other
tool), and retroactively updates a selected ObfuscateShape the same
way the style controls retroactively restyle.

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

import os
import shutil
import subprocess
import tempfile
from dataclasses import replace as dataclass_replace
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Rsvg", "2.0")

import numpy as np
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Rsvg

from greenshot_linux.capture.clipboard import ClipboardBackend
from greenshot_linux.core.drawing import Layer
from greenshot_linux.core.history import (
    AddElementMemento,
    DeleteElementMemento,
    ElementChangeMemento,
    UndoRedoStack,
)
from greenshot_linux.core.shapes import (
    ImageShape, ObfuscateShape, ShapeStyle, SpeechBubbleShape, StepLabelShape, SvgShape, TextShape,
)
from greenshot_linux.settings import (
    get_capture_mouse_cursor,
    get_output_directory,
    set_capture_mouse_cursor,
    set_output_directory,
)
from greenshot_linux.resources import LOGO_PATH
from greenshot_linux.core.tools import (
    Tool,
    create_freehand_shape,
    create_shape_from_drag,
    default_insert_bounds,
    handle_at,
    resize_shape,
    shape_handles,
    translate_shape,
)
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface
from greenshot_linux.ui.composite import composite_to_numpy
from greenshot_linux.ui.gdk_convert import pixbuf_to_numpy
from greenshot_linux.ui.file_export import save_image_to_file
from greenshot_linux.ui.icons import tool_icon_image
from greenshot_linux.ui.printing import print_image
from greenshot_linux.ui.render import render_shape

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
# this tool - Highlight/Obfuscate/Effects (task #36/#42) and
# Crop/Rotate/Resize (task #36) are the next two groups in the real
# toolbar but aren't built yet, so there's nothing to list for them
# here yet.
_TOOL_LABELS = [
    (Tool.SELECT, "Select"),
    None,
    (Tool.RECTANGLE, "Rectangle"),
    (Tool.ELLIPSE, "Ellipse"),
    (Tool.LINE, "Line"),
    (Tool.ARROW, "Arrow"),
    (Tool.FREEHAND, "Freehand"),
    (Tool.PIXELIZE, "Pixelize"),
    (Tool.BLUR, "Blur"),
    (Tool.TEXT, "Text"),
    (Tool.SPEECH_BUBBLE, "Speech Bubble"),
    (Tool.STEP_LABEL, "Step Label"),
    (Tool.EMOJI, "Emoji"),
]

_HANDLE_SIZE = 6
_HANDLE_FILL = (1.0, 1.0, 1.0)
_HANDLE_STROKE = (0.1, 0.4, 0.9)


def _color_to_rgba(color) -> Gdk.RGBA:
    r, g, b, a = color
    rgba = Gdk.RGBA()
    rgba.red, rgba.green, rgba.blue, rgba.alpha = r / 255, g / 255, b / 255, a / 255
    return rgba


def _rgba_to_color(rgba: Gdk.RGBA):
    return (
        round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255), round(rgba.alpha * 255),
    )


class EditorWindow(Gtk.Window):
    def __init__(self, image: np.ndarray, clipboard_backend: ClipboardBackend = None):
        super().__init__(title="Greenshot Linux")
        self._base_image = image
        self._surface = numpy_to_cairo_surface(image)
        height, width = image.shape[:2]

        if clipboard_backend is None:
            from greenshot_linux.capture.x11_clipboard import X11ClipboardBackend

            clipboard_backend = X11ClipboardBackend()
        self._clipboard = clipboard_backend

        self.layer = Layer()
        self.undo_redo = UndoRedoStack()
        # Matches the Windows source's default (ImageEditorForm.
        # Designer.cs: btnCursor.Checked = true) - the editor opens
        # with Select active, not a drawing tool, so the first click
        # on a fresh capture doesn't accidentally start drawing.
        self.tool = Tool.SELECT
        self._default_style = ShapeStyle()
        self._default_obfuscate_amount = 5  # matches ObfuscateShape's own default
        self.selected_shape = None
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
        )
        self._drawing_area.connect("draw", self._on_draw)
        self._drawing_area.connect("button-press-event", self._on_button_press)
        self._drawing_area.connect("motion-notify-event", self._on_motion)
        self._drawing_area.connect("button-release-event", self._on_button_release)

        content_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_row.pack_start(self._build_tool_palette(), False, False, 0)
        content_row.pack_start(self._drawing_area, True, True, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(self._build_menu_bar(), False, False, 0)
        box.pack_start(self._build_action_toolbar(), False, False, 0)
        box.pack_start(self._build_style_panel(), False, False, 0)
        box.pack_start(content_row, True, True, 0)
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

    def _build_style_panel(self) -> Gtk.Box:
        """Color/thickness/shadow controls that update self._default_style,
        plus a separate obfuscate-amount spinner (blur radius / pixel
        size) for self._default_obfuscate_amount, since ObfuscateShape
        has no style field. Both affect shapes created *after* a
        change, and also retroactively restyle the current selection
        if it has the relevant field.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_border_width(4)

        box.pack_start(Gtk.Label(label="Line:"), False, False, 0)
        self._line_color_button = Gtk.ColorButton()
        self._line_color_button.set_use_alpha(True)
        self._line_color_button.set_rgba(_color_to_rgba(self._default_style.line_color))
        self._line_color_button.connect("color-set", self._on_line_color_changed)
        box.pack_start(self._line_color_button, False, False, 0)

        box.pack_start(Gtk.Label(label="Fill:"), False, False, 0)
        self._fill_color_button = Gtk.ColorButton()
        self._fill_color_button.set_use_alpha(True)
        self._fill_color_button.set_rgba(_color_to_rgba(self._default_style.fill_color))
        self._fill_color_button.connect("color-set", self._on_fill_color_changed)
        box.pack_start(self._fill_color_button, False, False, 0)

        box.pack_start(Gtk.Label(label="Line Thickness:"), False, False, 0)
        adjustment = Gtk.Adjustment(
            value=self._default_style.line_thickness, lower=0, upper=20, step_increment=1
        )
        self._thickness_spin = Gtk.SpinButton(adjustment=adjustment)
        self._thickness_spin.connect("value-changed", self._on_thickness_changed)
        box.pack_start(self._thickness_spin, False, False, 0)

        self._shadow_check = Gtk.CheckButton(label="Shadow")
        self._shadow_check.set_active(self._default_style.shadow)
        self._shadow_check.connect("toggled", self._on_shadow_toggled)
        box.pack_start(self._shadow_check, False, False, 0)

        # Label text swaps with the active tool (see
        # _obfuscate_amount_label_text) - matches Windows' own two
        # separate, mode-specific controls ("Blur radius" for Blur,
        # "Pixel size" for Pixelize - ImageEditorForm.Designer.cs)
        # rather than a single generically-named field for both.
        self._obfuscate_amount_label = Gtk.Label(label=self._obfuscate_amount_label_text(self.tool))
        box.pack_start(self._obfuscate_amount_label, False, False, 0)
        obfuscate_adjustment = Gtk.Adjustment(
            value=self._default_obfuscate_amount, lower=2, upper=50, step_increment=1
        )
        self._obfuscate_amount_spin = Gtk.SpinButton(adjustment=obfuscate_adjustment)
        self._obfuscate_amount_spin.connect("value-changed", self._on_obfuscate_amount_changed)
        box.pack_start(self._obfuscate_amount_spin, False, False, 0)

        return box

    @staticmethod
    def _obfuscate_amount_label_text(tool: Tool) -> str:
        if tool is Tool.BLUR:
            return "Blur Radius:"
        if tool is Tool.PIXELIZE:
            return "Pixel Size:"
        return "Obfuscate Amount:"

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

    def _apply_style_change(self, updated_style: ShapeStyle) -> None:
        """Style panel changes always update self._default_style (for
        shapes created from here on); if a shape is currently selected
        and has a style field (everything except Obfuscate/Icon/
        Cursor/Image/Svg, none of which have line/fill styling), it's
        restyled too, via one ElementChangeMemento per control change.
        """
        self._default_style = updated_style
        shape = self.selected_shape
        if shape is not None and hasattr(shape, "style"):
            restyled = dataclass_replace(shape, style=updated_style)
            self.layer.replace(shape, restyled)
            self.undo_redo.push(ElementChangeMemento(self.layer, before=shape, after=restyled))
            self.selected_shape = restyled
            self._drawing_area.queue_draw()

    def _on_line_color_changed(self, button: Gtk.ColorButton) -> None:
        self._apply_style_change(dataclass_replace(self._default_style, line_color=_rgba_to_color(button.get_rgba())))

    def _on_fill_color_changed(self, button: Gtk.ColorButton) -> None:
        self._apply_style_change(dataclass_replace(self._default_style, fill_color=_rgba_to_color(button.get_rgba())))

    def _on_thickness_changed(self, spin: Gtk.SpinButton) -> None:
        self._apply_style_change(dataclass_replace(self._default_style, line_thickness=spin.get_value_as_int()))

    def _on_shadow_toggled(self, check: Gtk.CheckButton) -> None:
        self._apply_style_change(dataclass_replace(self._default_style, shadow=check.get_active()))

    def _on_tool_button_toggled(self, button: Gtk.RadioToolButton, tool: Tool) -> None:
        if button.get_active():
            self.tool = tool
            self._obfuscate_amount_label.set_text(self._obfuscate_amount_label_text(tool))

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

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    # Not a Windows feature - Windows has no "open in an external
    # editor" destination. A new addition, not a port, per explicit
    # request. Krita is tried first since it was specifically
    # requested, with GIMP as a fallback. (name, PATH command, Flatpak
    # app ID) - checks both, since Flatpak is how at least one of
    # these is commonly installed on Mint (confirmed live: this dev
    # machine has Krita only via Flatpak, not on PATH - a plain
    # shutil.which("krita") check alone would have missed it).
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

    def _find_external_editor_command(self):
        """The argv prefix to launch the first available candidate
        editor, or None if none are installed. Checks a plain PATH
        executable first, then a Flatpak install for the same
        candidate - preferring a live `flatpak list` query over
        `locate`: `locate` depends on the mlocate/plocate package
        being installed at all, and its index can be stale until the
        next `updatedb` run, so a just-installed app might not show up
        yet; `flatpak list` is authoritative and always current.
        """
        flatpak_apps = None
        for _name, path_command, flatpak_id in self._EXTERNAL_EDITOR_CANDIDATES:
            if shutil.which(path_command):
                return [path_command]
            if flatpak_apps is None:
                flatpak_apps = self._installed_flatpak_apps()
            if flatpak_id in flatpak_apps:
                return ["flatpak", "run", flatpak_id]
        return None

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
        fd, path = tempfile.mkstemp(suffix=".png", prefix="greenshot-linux-")
        os.close(fd)
        save_image_to_file(self._composited_image(), path)
        subprocess.Popen(command + [path])

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
        self._drawing_area.queue_draw()

    def _handle_text_editing_key(self, event) -> bool:
        shape = self._editing_text_shape
        if event.keyval == Gdk.KEY_Escape:
            self._cancel_text_editing()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                self._update_editing_text(shape.text + "\n")
            else:
                self._commit_text_editing()
            return True
        if event.keyval == Gdk.KEY_BackSpace:
            self._update_editing_text(shape.text[:-1])
            return True
        codepoint = Gdk.keyval_to_unicode(event.keyval)
        if codepoint:
            char = chr(codepoint)
            if char.isprintable():
                self._update_editing_text(shape.text + char)
        return True  # swallow everything else - no tool-switch/undo while editing

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

    def _content_offset(self) -> tuple:
        """How far the image is inset from the drawing area's top-left
        corner. The drawing area can end up larger than the image - a
        small capture is narrower than the toolbar's natural width, and
        Gtk.Box (packed with fill=True) stretches every child to that
        width - so without this, a small capture used to sit pinned to
        the corner with a lopsided gap on the right/bottom instead of
        looking centered.
        """
        img_h, img_w = self._base_image.shape[:2]
        alloc = self._drawing_area.get_allocation()
        return max(0, (alloc.width - img_w) // 2), max(0, (alloc.height - img_h) // 2)

    def _on_draw(self, widget, ctx):
        offset_x, offset_y = self._content_offset()
        ctx.translate(offset_x, offset_y)
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
        x, y = int(event.x) - offset_x, int(event.y) - offset_y

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
                self._drag_shape = create_freehand_shape(self._drag_points, self._default_style)
            else:
                self._drag_shape = create_shape_from_drag(
                    self.tool, (x, y), (x, y), self._default_style, amount=self._default_obfuscate_amount
                )
        else:
            self.selected_shape = None
        widget.queue_draw()
        return True

    def _on_motion(self, widget, event):
        offset_x, offset_y = self._content_offset()
        x, y = int(event.x) - offset_x, int(event.y) - offset_y
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
                self._drag_shape = create_freehand_shape(self._drag_points, self._default_style)
            else:
                self._drag_shape = create_shape_from_drag(
                    self.tool, self._drag_origin, (x, y), self._default_style, amount=self._default_obfuscate_amount
                )
            widget.queue_draw()
            return True
        return False

    def _on_button_release(self, widget, event):
        offset_x, offset_y = self._content_offset()
        x, y = int(event.x) - offset_x, int(event.y) - offset_y
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
                shape = create_freehand_shape(self._drag_points, self._default_style)
            else:
                shape = create_shape_from_drag(
                    self.tool, self._drag_origin, (x, y), self._default_style,
                    amount=self._default_obfuscate_amount, next_step_number=self._next_step_number(),
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
            else:
                self.undo_redo.push(AddElementMemento(self.layer, shape))
            widget.queue_draw()
            return True
        return False

    def _on_key_press(self, widget, event):
        if self._editing_text_shape is not None:
            return self._handle_text_editing_key(event)

        tool = _TOOL_KEYS.get(event.keyval)
        if tool is not None:
            # set_active(True) fires "toggled", which itself sets
            # self.tool - this just keeps the toolbar's radio buttons
            # in sync with a keyboard-driven tool switch too.
            self._tool_buttons[tool].set_active(True)
            return True

        if event.keyval == Gdk.KEY_Delete:
            self._do_delete()
            return True

        ctrl_held = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
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
        return False

    def _on_destroy(self, widget) -> None:
        app = Gio.Application.get_default()
        if app is not None:
            app.unregister_editor_window(self)
