"""The post-capture destination picker: a Gtk.Menu context menu shown
at the pointer immediately after every capture completes, offering a
choice of what to do with it.

This matches Windows Greenshot's *actual* default behavior, not what
this port originally shipped: reading Greenshot.Base/Core/
ICoreConfiguration.cs and Greenshot/Destinations/PickerDestination.cs
in the Windows source confirmed OutputDestinations defaults to
"Picker" - a context menu of active destinations - not "always open
the editor," which is what this port unconditionally did before this
module existed.

Item order matches Windows' own destination priority ordering (File
priority 0, Editor priority 1, Clipboard/Printer priority 2, ties
broken alphabetically by description - so Save, Save As, Editor,
Clipboard, Printer) with one deliberate change: Copy to Clipboard is
pulled to the very top, per explicit user request. Everything else
keeps its relative Windows order. Email/Office/cloud destinations are
out of scope (cut in REQUIREMENTS.md), so this offers only the five
that exist here.

Save vs Save As mirrors Windows' own two-tier save: Save writes
silently to the configured output directory (settings.py,
user-configurable from the editor - see editor_window.py's save-
location button) with a generated timestamp filename and no dialog;
Save As opens a file chooser, like this port's original single Save
button did (still true for EditorWindow's own Save button).

Not unit tested for the same reason region_select.py/window_picker.py
aren't: GTK glue driving a live popup menu, with no meaningful
headless test. Verified by running it and clicking each item.

Popup positioning deliberately does *not* use Gtk.Menu.popup_at_pointer
(None) - a real bug caught live: right after the full-screen capture
overlay closes, the pointer is back over whatever real window was
underneath it, which almost never belongs to this app. popup_at_pointer
needs to resolve a GDK-known window at the pointer position to anchor
against, and GDK generally can't resolve windows it doesn't own, so
that resolution silently fails (confirmed by reproducing it directly:
Gtk-CRITICAL "assertion 'GDK_IS_WINDOW (rect_window)' failed", menu
never becomes visible/mapped) - the picker just never appeared.
Anchoring to the screen's root window instead (always resolvable,
regardless of what else is running) at the raw pointer coordinates
fixes it; confirmed by reproducing the same scenario with this fix in
place and observing the menu actually becomes visible/mapped.

``cursor_shape``, if given (see ui/capture_modes.py's
capture_cursor_shape), is the auto-captured mouse cursor as a
CursorShape. Windows bakes the cursor into the Surface it exports
regardless of destination (Surface.cs:552-565 adds it as an element
before any destination runs), so every non-Edit destination here
composites it into a flat copy of the image via ui/composite.py -
the same rendering pipeline the live editor uses, so what gets
saved/copied/printed is pixel-identical to what editing would show.
Edit instead adds it as a live, movable/deletable/auto-selected Layer
element (matching CursorContainer's real behavior - it's not baked
into the base image there), the same tail pattern
editor_window.py's _do_insert_image uses.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from greenshot_linux.capture.clipboard import ClipboardBackend
from greenshot_linux.core.drawing import Layer
from greenshot_linux.core.shapes import CursorShape
from greenshot_linux.settings import get_output_directory, quick_save_filename
from greenshot_linux.ui.composite import composite_to_numpy
from greenshot_linux.ui.file_export import save_image_to_file
from greenshot_linux.ui.printing import print_image


def _flattened(image: np.ndarray, cursor_shape: CursorShape = None) -> np.ndarray:
    if cursor_shape is None:
        return image
    layer = Layer()
    layer.add(cursor_shape)
    return composite_to_numpy(image, layer)


def _open_editor(image: np.ndarray, cursor_shape: CursorShape = None) -> None:
    from greenshot_linux.ui.editor_window import EditorWindow
    from greenshot_linux.core.history import AddElementMemento

    editor = EditorWindow(image)
    if cursor_shape is not None:
        editor.layer.add(cursor_shape)
        editor.selected_shape = cursor_shape
        editor.undo_redo.push(AddElementMemento(editor.layer, cursor_shape))
    editor.show_all()


def _quick_save(image: np.ndarray, cursor_shape: CursorShape = None) -> None:
    directory = get_output_directory()
    directory.mkdir(parents=True, exist_ok=True)
    save_image_to_file(_flattened(image, cursor_shape), directory / quick_save_filename(datetime.now()))


def _save_as(image: np.ndarray, cursor_shape: CursorShape = None) -> None:
    dialog = Gtk.FileChooserDialog(title="Save Screenshot As", action=Gtk.FileChooserAction.SAVE)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
    )
    dialog.set_current_folder(str(get_output_directory()))
    dialog.set_current_name(quick_save_filename(datetime.now()))
    dialog.set_do_overwrite_confirmation(True)
    try:
        if dialog.run() == Gtk.ResponseType.OK:
            save_image_to_file(_flattened(image, cursor_shape), dialog.get_filename())
    finally:
        dialog.destroy()


def show_destination_picker(
    image: np.ndarray, clipboard_backend: ClipboardBackend = None, cursor_shape: CursorShape = None,
    anchor_window: Gdk.Window = None, anchor_local_pos: tuple[int, int] = None,
    refresh_image=None,
) -> Gtk.Menu:
    """Pops up the picker at the current pointer position. Returns the
    Gtk.Menu - callers don't need it (GTK keeps it alive while shown),
    but tests/scripts may want to inspect it.

    ``anchor_window``/``anchor_local_pos`` are for Wayland callers only
    (see ui/region_select_wayland.py): the screen's root window - the
    default anchor below, and the only option that works under X11 -
    isn't a valid popup parent under Wayland at all ("Couldn't map as
    window ... as popup because it doesn't have a parent", confirmed
    live), so a real, still-alive window and a position already local
    to it must be supplied instead there.

    ``refresh_image``, given by Wayland's window-picker only (see
    window_picker_wayland.py's module docstring), is a zero-argument
    callable that fetches the real, activated-window pixels - called
    lazily, only once the user actually picks a destination, instead
    of ``image`` (used as an immediate placeholder in that case).
    Wayland's popup grab must be requested synchronously from within
    the input event that triggered it (confirmed live: deferring the
    popup call itself broke it - "no trigger event for menu popup"),
    but the activate()+fresh-grab portal round trip that produces the
    real pixels can't safely run from inside that same handler either
    (confirmed live: hangs indefinitely - a reentrancy problem, not
    latency). Showing the menu immediately with a placeholder, then
    resolving the real pixels only once an item is chosen - itself a
    fresh, non-nested dispatch by the time it fires - satisfies both
    constraints at once.
    """
    if clipboard_backend is None:
        from greenshot_linux.capture.backend_select import default_clipboard_backend

        clipboard_backend = default_clipboard_backend()

    menu = Gtk.Menu()

    def add_item(label: str, handler) -> None:
        item = Gtk.MenuItem(label=label)

        def on_activate(_item):
            final_image = refresh_image() if refresh_image is not None else image
            handler(final_image, cursor_shape)

        item.connect("activate", on_activate)
        menu.append(item)

    add_item("Copy to Clipboard", lambda img, cs: clipboard_backend.set_image(_flattened(img, cs)))
    add_item("Save", _quick_save)
    add_item("Save As...", _save_as)
    add_item("Edit", _open_editor)
    add_item("Print", lambda img, cs: print_image(_flattened(img, cs)))

    menu.show_all()
    if anchor_window is not None:
        x, y = anchor_local_pos
        anchor = anchor_window
    else:
        seat = Gdk.Display.get_default().get_default_seat()
        _screen, x, y = seat.get_pointer().get_position()
        anchor = Gdk.Screen.get_default().get_root_window()
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = x, y, 1, 1
    menu.popup_at_rect(anchor, rect, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.NORTH_WEST, None)
    return menu
