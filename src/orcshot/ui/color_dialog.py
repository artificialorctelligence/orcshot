"""The editor's color picker - faithful port of
Greenshot.Editor.Forms.ColorDialog (ColorDialog.cs): a single custom
dialog (not a small dropdown-then-system-dialog flow) with a 13x11
hue-shaded palette grid, a row of recently-used colors, an RGB/Alpha/
hex text entry, a Transparent quick-pick, and an eyedropper. Both the
editor's line-color and fill-color buttons (ui/editor_window.py) open
this same dialog - Windows shares one ColorDialog between them too,
distinguished only by their default colors, not by dialog behavior.

Not unit tested for the same reason other Gtk.Dialog-building ui/
modules aren't: GTK glue with no meaningful headless test - the pure
palette-generation and recent-colors logic this wires together is
tested separately (core/color_palette.py). Verified live (see
REQUIREMENTS.md's "Color picker" section).
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from orcshot.core.color_palette import add_recent_color, color_palette_grid
from orcshot.settings import get_recent_colors, set_recent_colors
from orcshot.ui.eyedropper import start_eyedropper

_SWATCH_SIZE = 15


def _color_to_hex(color) -> str:
    r, g, b, _a = color
    return f"#{r:02X}{g:02X}{b:02X}"


def _hex_to_color(text: str, alpha: int):
    text = text.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None
    return (r, g, b, alpha)


def _make_swatch(color, on_pick, on_commit) -> Gtk.EventBox:
    """A small solid-color clickable swatch - single click previews
    (matching ColorDialog's per-button Click), double click applies
    and closes (matching its DoubleClick, ColorDialog.cs:133-137).
    """
    box = Gtk.EventBox()
    box.set_size_request(_SWATCH_SIZE, _SWATCH_SIZE)
    rgba = Gdk.RGBA()
    rgba.red, rgba.green, rgba.blue, rgba.alpha = color[0] / 255, color[1] / 255, color[2] / 255, color[3] / 255
    box.override_background_color(Gtk.StateFlags.NORMAL, rgba)

    def on_press(widget, event):
        on_pick(color)
        if event.type == Gdk.EventType._2BUTTON_PRESS:
            on_commit(color)
        return True

    box.connect("button-press-event", on_press)
    return box


def show_color_picker(
    parent: Gtk.Window, initial_color, allow_transparent: bool = True, capture_backend=None,
):
    """Runs the dialog modally; returns the picked (r, g, b, a) color,
    or None if cancelled. A committed pick (Apply, or double-clicking
    a swatch) is added to the persisted recent-colors list
    (settings.py), matching AddToRecentColors (ColorDialog.cs:182-192).
    """
    dialog = Gtk.Dialog(title="Select Color", transient_for=parent)
    dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Apply", Gtk.ResponseType.OK)
    content = dialog.get_content_area()
    content.set_border_width(10)
    content.set_spacing(8)

    state = {"color": initial_color, "updating": False}

    main_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    content.pack_start(main_row, True, True, 0)

    # --- left: palette grid + recent colors ---
    left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    grid = Gtk.Grid(row_spacing=0, column_spacing=0)

    preview = Gtk.DrawingArea()
    preview.set_size_request(70, 50)
    hex_entry = Gtk.Entry()
    hex_entry.set_width_chars(8)
    r_spin = Gtk.SpinButton.new_with_range(0, 255, 1)
    g_spin = Gtk.SpinButton.new_with_range(0, 255, 1)
    b_spin = Gtk.SpinButton.new_with_range(0, 255, 1)
    a_spin = Gtk.SpinButton.new_with_range(0, 255, 1)

    def refresh_fields() -> None:
        state["updating"] = True
        r, g, b, a = state["color"]
        preview.queue_draw()
        hex_entry.set_text(_color_to_hex(state["color"]))
        r_spin.set_value(r)
        g_spin.set_value(g)
        b_spin.set_value(b)
        a_spin.set_value(a)
        state["updating"] = False

    def apply_color(color) -> None:
        state["color"] = color
        refresh_fields()

    def commit_and_close(color) -> None:
        state["color"] = color
        dialog.response(Gtk.ResponseType.OK)

    for col_idx, column in enumerate(color_palette_grid()):
        for row_idx, color in enumerate(column):
            swatch = _make_swatch(color, apply_color, commit_and_close)
            grid.attach(swatch, col_idx, row_idx, 1, 1)
    left_box.pack_start(grid, False, False, 0)

    recent_label = Gtk.Label(label="Recently used colors")
    recent_label.set_xalign(0)
    left_box.pack_start(recent_label, False, False, 0)
    recent_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
    for color in get_recent_colors():
        recent_row.pack_start(_make_swatch(color, apply_color, commit_and_close), False, False, 0)
    left_box.pack_start(recent_row, False, False, 0)

    main_row.pack_start(left_box, False, False, 0)

    # --- right: preview, RGB/hex fields, Transparent, Eyedropper ---
    right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

    def on_preview_draw(widget, ctx):
        r, g, b, a = state["color"]
        ctx.set_source_rgba(r / 255, g / 255, b / 255, a / 255)
        ctx.paint()
        return False

    preview.connect("draw", on_preview_draw)
    right_box.pack_start(preview, False, False, 0)

    fields_grid = Gtk.Grid(row_spacing=4, column_spacing=6)
    fields_grid.attach(Gtk.Label(label="Hex:"), 0, 0, 1, 1)
    fields_grid.attach(hex_entry, 1, 0, 1, 1)
    for row, (label, spin) in enumerate((("R:", r_spin), ("G:", g_spin), ("B:", b_spin), ("A:", a_spin)), start=1):
        fields_grid.attach(Gtk.Label(label=label), 0, row, 1, 1)
        fields_grid.attach(spin, 1, row, 1, 1)
    right_box.pack_start(fields_grid, False, False, 0)

    def on_hex_activate(entry) -> None:
        if state["updating"]:
            return
        color = _hex_to_color(entry.get_text(), state["color"][3])
        if color is not None:
            apply_color(color)

    hex_entry.connect("activate", on_hex_activate)

    def on_rgba_changed(_spin) -> None:
        if state["updating"]:
            return
        apply_color((int(r_spin.get_value()), int(g_spin.get_value()), int(b_spin.get_value()), int(a_spin.get_value())))

    for spin in (r_spin, g_spin, b_spin, a_spin):
        spin.connect("value-changed", on_rgba_changed)

    if allow_transparent:
        transparent_button = Gtk.Button(label="Transparent")
        transparent_button.connect("clicked", lambda _b: apply_color((0, 0, 0, 0)))
        right_box.pack_start(transparent_button, False, False, 0)

    eyedropper_button = Gtk.Button(label="Eyedropper")

    def on_eyedropper_clicked(widget):
        start_eyedropper(widget, apply_color, capture_backend=capture_backend)

    eyedropper_button.connect("clicked", on_eyedropper_clicked)
    right_box.pack_start(eyedropper_button, False, False, 0)

    main_row.pack_start(right_box, True, True, 0)

    refresh_fields()
    dialog.show_all()
    try:
        if dialog.run() != Gtk.ResponseType.OK:
            return None
        final_color = state["color"]
        set_recent_colors(add_recent_color(get_recent_colors(), final_color))
        return final_color
    finally:
        dialog.destroy()
