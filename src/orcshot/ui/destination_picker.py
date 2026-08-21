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

from orcshot.capture.clipboard import ClipboardBackend
from orcshot.core.drawing import Layer
from orcshot.core.filename_pattern import resolve_filename_pattern
from orcshot.core.shapes import CursorShape
from orcshot.settings import (
    consume_filename_counter,
    get_excluded_destinations,
    get_external_commands,
    get_filename_counter,
    get_output_directory,
    get_output_settings,
)
from orcshot.ui.composite import composite_to_numpy
from orcshot.ui.external_commands import run_external_command
from orcshot.ui.file_export import save_image_to_file
from orcshot.ui.icons import destination_icon_image
from orcshot.ui.printing import print_image


def _rgba_to_color(rgba: Gdk.RGBA) -> tuple:
    return (round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255), round(rgba.alpha * 255))


def _flattened(image: np.ndarray, cursor_shape: CursorShape = None) -> np.ndarray:
    if cursor_shape is None:
        return image
    layer = Layer()
    layer.add(cursor_shape)
    return composite_to_numpy(image, layer)


def _open_editor(image: np.ndarray, cursor_shape: CursorShape = None, title: str = "") -> None:
    from orcshot.ui.editor_window import EditorWindow
    from orcshot.core.history import AddElementMemento

    editor = EditorWindow(image, window_title=title)
    if cursor_shape is not None:
        editor.layer.add(cursor_shape)
        editor.selected_shape = cursor_shape
        editor.undo_redo.push(AddElementMemento(editor.layer, cursor_shape))
    editor.show_all()
    # Task #157 follow-up: this "Edit" destination is the one path
    # reached from a Shell-native capture (region-select/window-picker/
    # CaptureRect) - the editor gets constructed and shown from an
    # async D-Bus reply callback, not a direct response to a real
    # input event in this process. Live-observed on the VM: an editor
    # opened this way once landed pinned to the screen's top-left
    # corner (x=0) with focus=false, rather than the normal centered
    # placement a directly-constructed EditorWindow gets (confirmed
    # separately, same session - a standalone script's own
    # show_all()-only EditorWindow positioned normally). Not
    # reproduced/isolated further (no synthetic input available to
    # drive the actual Shell-native interaction), but present() -
    # unlike show_all() alone - is specifically GTK's way of asking the
    # compositor to actually raise/focus a window, which is plausibly
    # what a window shown from this kind of indirect trigger is
    # missing. Cheap and safe to add regardless of whether it's the
    # full explanation.
    editor.present()


def _quick_save(image: np.ndarray, cursor_shape: CursorShape = None, title: str = "") -> None:
    """Task #95's Output tab - now uses the same settings.OutputSettings
    (filename pattern/primary format/JPEG quality/copy-path-to-
    clipboard) as EditorWindow._do_quick_save, not the older fixed
    ``.png``/timestamp-only pattern - this destination and that one are
    the same conceptual action (Windows' own FileDestination), just
    reached from a different entry point (picker menu vs. menu bar),
    and had drifted out of sync while that menu-bar path was built.

    ``title`` (task #139) is the captured window's title (active-
    window/window-picker capture only, "" otherwise) - fills in
    core/filename_pattern.py's ``${title}`` token.
    """
    output_settings = get_output_settings()
    directory = get_output_directory()
    directory.mkdir(parents=True, exist_ok=True)
    counter = consume_filename_counter()
    filename = (
        resolve_filename_pattern(
            output_settings.filename_pattern, datetime.now(), counter, title=title, mode=output_settings.filename_pattern_mode,
        )
        + "." + output_settings.primary_format
    )
    path = directory / filename
    save_image_to_file(_flattened(image, cursor_shape), path, jpeg_quality=output_settings.jpeg_quality)
    if output_settings.copy_path_to_clipboard:
        Gtk.Clipboard.get_default(Gdk.Display.get_default()).set_text(str(path), -1)


def _save_as(image: np.ndarray, cursor_shape: CursorShape = None, title: str = "") -> None:
    """See _quick_save's own note - same drift, same fix (primary
    format now drives the suggested extension, JPEG quality is
    applied, path-to-clipboard is honored). ``title`` - see
    _quick_save's own docstring."""
    output_settings = get_output_settings()
    dialog = Gtk.FileChooserDialog(title="Save Screenshot As", action=Gtk.FileChooserAction.SAVE)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
    )
    dialog.set_current_folder(str(get_output_directory()))
    # Peek, don't consume - the counter should only advance once a save
    # actually happens (below), not just because a dialog with a
    # suggested name was shown and possibly cancelled.
    suggested = resolve_filename_pattern(
        output_settings.filename_pattern, datetime.now(), get_filename_counter(),
        title=title, mode=output_settings.filename_pattern_mode,
    )
    dialog.set_current_name(f"{suggested}.{output_settings.primary_format}")
    dialog.set_do_overwrite_confirmation(True)
    try:
        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            save_image_to_file(_flattened(image, cursor_shape), path, jpeg_quality=output_settings.jpeg_quality)
            consume_filename_counter()
            if output_settings.copy_path_to_clipboard:
                Gtk.Clipboard.get_default(Gdk.Display.get_default()).set_text(str(path), -1)
    finally:
        dialog.destroy()


# Shared between show_destination_picker's own Gtk.Menu (X11 and the
# WaylandRegionSelect fallback) and dispatch_destination (the Shell-
# native picker's own result, see ui/region_select_gnome_shell.py) -
# one table of (id, label, handler) so both paths stay in sync and
# neither duplicates the actual destination logic. Order/labels match
# Windows' own destination priority (see this module's own docstring).
_DESTINATION_TABLE = [
    ("clipboard", "Copy to Clipboard", lambda img, cs, clipboard_backend, title: clipboard_backend.set_image(_flattened(img, cs))),
    ("save", "Save", lambda img, cs, clipboard_backend, title: _quick_save(img, cs, title)),
    ("save_as", "Save As...", lambda img, cs, clipboard_backend, title: _save_as(img, cs, title)),
    ("edit", "Edit", lambda img, cs, clipboard_backend, title: _open_editor(img, cs, title)),
    ("print", "Print", lambda img, cs, clipboard_backend, title: print_image(_flattened(img, cs))),
]


def _external_command_entry(command):
    def handler(img, cs, _clipboard_backend, _title, command=command):
        run_external_command(command, _flattened(img, cs))

    return (f"external:{command.name}", command.name, handler)


# Real Windows' actual Office destination inserts the image straight
# into a document via COM automation - a Windows-only mechanism with
# no Linux equivalent. This is a new addition, not a port (task #95's
# Destinations tab, direflail's own request), scoped to the nearest
# faithful-in-spirit equivalent available here: open the image in
# LibreOffice/OpenOffice Draw, the same "hand it to the office suite
# and let the user work with it" outcome. soffice checked first -
# virtually every modern install (including ones still branded
# "OpenOffice" via a LibreOffice-based fork) uses that binary name;
# ooffice/openoffice.org are the legacy Apache OpenOffice ones, kept
# as a fallback for the rare install that still has one.
_OFFICE_CANDIDATES = (("LibreOffice Draw", "soffice"), ("OpenOffice Draw", "ooffice"), ("OpenOffice Draw", "openoffice.org"))


def _find_office_command():
    import shutil

    for name, path_command in _OFFICE_CANDIDATES:
        if shutil.which(path_command):
            return name, path_command
    return None


def _office_entry():
    found = _find_office_command()
    if found is None:
        return None
    name, path_command = found

    def handler(img, cs, _clipboard_backend, _title, path_command=path_command):
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        from orcshot.ui.file_export import orcshot_cache_dir

        fd, path_str = tempfile.mkstemp(suffix=".png", prefix="orcshot-office-", dir=str(orcshot_cache_dir()))
        os.close(fd)
        path = Path(path_str)
        save_image_to_file(_flattened(img, cs), path)
        subprocess.Popen([path_command, "--draw", str(path)])

    return ("office", name, handler)


def _all_destinations(include_excluded: bool = False) -> list:
    """_DESTINATION_TABLE plus the Office destination (if LibreOffice/
    OpenOffice is installed) plus one entry per configured external
    command (task #110, ui/external_commands.py) - computed fresh on
    every call (not cached at import time) so a command added/removed/
    renamed via Preferences (or LibreOffice getting installed/removed)
    shows up immediately without an app restart, the same way Windows'
    own Destinations() re-enumerates ExternalCommandConfig.Commands
    each time the picker is built (ExternalCommandPlugin.cs:69-75).
    User-added/detected entries appended after the five built-ins
    rather than interleaved by Windows' own priority ordering - they
    read naturally as "extra stuff" tacked onto the end.

    Filtered by settings.get_excluded_destinations() (task #95's
    Destinations tab checklist) unless ``include_excluded`` is set - an
    *exclude* list, so anything new here is enabled by default. The
    real picker menu (show_destination_picker/dispatch_destination)
    always wants the filtered view; the Preferences checklist itself
    needs the unfiltered one, or an unchecked/excluded destination
    would vanish from its own settings UI with no way to re-enable it.
    """
    entries = list(_DESTINATION_TABLE)
    office = _office_entry()
    if office is not None:
        entries.append(office)
    entries += [_external_command_entry(command) for command in get_external_commands()]
    if include_excluded:
        return entries
    excluded = get_excluded_destinations()
    return [entry for entry in entries if entry[0] not in excluded]


def dispatch_destination(
    destination_id: str, image: np.ndarray, cursor_shape: CursorShape = None, clipboard_backend: ClipboardBackend = None,
    title: str = "",
) -> None:
    """Runs whichever destination action ``destination_id`` names (one
    of _all_destinations()'s ids) - the Shell-native picker's own
    counterpart to a menu item's "activate" handler, for callers that
    already know which destination was chosen (see
    ui/region_select_gnome_shell.py) rather than needing to show a
    picker of their own. A blank/unrecognized id is a no-op - matches
    the picker being dismissed without a choice.

    ``title`` (task #139) - the captured window's title, threaded
    through to whichever handler cares (_quick_save/_save_as/
    _open_editor); every other handler accepts and ignores it, one
    shared calling convention for every destination.
    """
    if clipboard_backend is None:
        from orcshot.capture.backend_select import default_clipboard_backend

        clipboard_backend = default_clipboard_backend()

    for item_id, _label, handler in _all_destinations():
        if item_id == destination_id:
            handler(image, cursor_shape, clipboard_backend, title)
            return


def show_destination_picker(
    image: np.ndarray, clipboard_backend: ClipboardBackend = None, cursor_shape: CursorShape = None,
    anchor_window: Gdk.Window = None, anchor_local_pos: tuple[int, int] = None,
    refresh_image=None, title: str = "",
) -> Gtk.Menu:
    """Pops up the picker at the current pointer position. Returns the
    Gtk.Menu - callers don't need it (GTK keeps it alive while shown),
    but tests/scripts may want to inspect it.

    ``title`` (task #139) - see dispatch_destination's own docstring.

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
        from orcshot.capture.backend_select import default_clipboard_backend

        clipboard_backend = default_clipboard_backend()

    menu = Gtk.Menu()
    # Query a throwaway top-level Gtk.Window's style context, not
    # menu's own - a freshly constructed, not-yet-parented Gtk.Menu
    # has no inherited CSS context yet and resolves to a wrong/
    # transparent color (confirmed live: rendered every icon in this
    # popup invisible on Wayland). A top-level window's own context
    # resolves correctly even pre-realize (same fix as
    # editor_window.py's own _build_menu_bar, task #127/#128
    # feedback) - a throwaway Gtk.Window() rather than reusing the
    # editor's own, since this picker is also reachable with no
    # editor window open at all (tray icon, hotkey).
    icon_color = _rgba_to_color(Gtk.Window().get_style_context().get_color(Gtk.StateFlags.NORMAL))
    for item_id, label, _handler in _all_destinations():
        item = Gtk.MenuItem()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.pack_start(destination_icon_image(item_id, icon_color), False, False, 0)
        box.pack_start(Gtk.Label(label=label), False, False, 0)
        item.add(box)

        def on_activate(_item, item_id=item_id) -> None:
            final_image = refresh_image() if refresh_image is not None else image
            dispatch_destination(item_id, final_image, cursor_shape, clipboard_backend, title=title)

        item.connect("activate", on_activate)
        menu.append(item)

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
