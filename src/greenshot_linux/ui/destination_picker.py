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
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from greenshot_linux.capture.clipboard import ClipboardBackend
from greenshot_linux.settings import get_output_directory, quick_save_filename
from greenshot_linux.ui.file_export import save_image_to_file
from greenshot_linux.ui.printing import print_image


def _default_clipboard_backend() -> ClipboardBackend:
    from greenshot_linux.capture.x11_clipboard import X11ClipboardBackend

    return X11ClipboardBackend()


def _open_editor(image: np.ndarray) -> None:
    from greenshot_linux.ui.editor_window import EditorWindow

    editor = EditorWindow(image)
    editor.show_all()


def _quick_save(image: np.ndarray) -> None:
    directory = get_output_directory()
    directory.mkdir(parents=True, exist_ok=True)
    save_image_to_file(image, directory / quick_save_filename(datetime.now()))


def _save_as(image: np.ndarray) -> None:
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
            save_image_to_file(image, dialog.get_filename())
    finally:
        dialog.destroy()


def show_destination_picker(image: np.ndarray, clipboard_backend: ClipboardBackend = None) -> Gtk.Menu:
    """Pops up the picker at the current pointer position. Returns the
    Gtk.Menu - callers don't need it (GTK keeps it alive while shown),
    but tests/scripts may want to inspect it.
    """
    if clipboard_backend is None:
        clipboard_backend = _default_clipboard_backend()

    menu = Gtk.Menu()

    def add_item(label: str, handler) -> None:
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _item: handler(image))
        menu.append(item)

    add_item("Copy to Clipboard", clipboard_backend.set_image)
    add_item("Save", _quick_save)
    add_item("Save As...", _save_as)
    add_item("Edit", _open_editor)
    add_item("Print", print_image)

    menu.show_all()
    menu.popup_at_pointer(None)
    return menu
