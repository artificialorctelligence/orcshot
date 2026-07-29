"""The persistent background application: a tray icon plus a
Gio.Application-based single-instance mechanism, so re-invoking this
entry point (e.g. from a hotkey binding) gets routed to the already-
running instance instead of spawning a duplicate process. This is
GIO's standard, built-in behavior for a fixed application_id - the
first ``run()`` registers a D-Bus name and owns it; a later ``run()``
with the same application_id detects that name is already owned and
forwards its command line to the running instance's do_command_line
instead of starting a new one. Verified empirically before writing
this file: a probe app running in one process, invoked a second time
from another process, showed both invocations landing in the first
process's PID, not two separate processes.

self.last_region tracks the absolute Rect from whichever capture mode
ran most recently (every start_*_capture wires its launch function's
on_captured callback to _remember_region), backing "Repeat Last
Region" - a fresh re-grab of that same spatial region, not cached
pixels, matching the Windows source's Shift+PrintScreen behavior. The
tray menu item is disabled until something's actually been captured.

Not unit tested for the same reason editor_window.py/region_select.py
aren't: GTK/GIO glue driving a live process and an on-screen tray icon,
with no meaningful headless test. Verified by actually running it.

do_startup calls ui.first_run_setup.maybe_run_first_run_setup(), which
shows a one-time confirmation dialog (REQUIREMENTS.md's "on first run
with a one-time user confirmation") offering to enable autostart and
the four capture hotkeys - see that module's docstring for why this is
the only place in the codebase allowed to write to the user's real
desktop configuration, and only via a human clicking a real button.
"""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from greenshot_linux.ui.capture_modes import (
    start_active_window_capture,
    start_full_screen_capture,
    start_last_region_capture,
)
from greenshot_linux.resources import LOGO_PATH
from greenshot_linux.ui.first_run_setup import maybe_run_first_run_setup
from greenshot_linux.ui.region_select import start_region_capture
from greenshot_linux.ui.window_picker import start_window_picker

APPLICATION_ID = "org.greenshotlinux.GreenshotLinux"
CAPTURE_REGION_OPTION = "capture-region"
CAPTURE_FULL_SCREEN_OPTION = "capture-full-screen"
CAPTURE_ACTIVE_WINDOW_OPTION = "capture-active-window"
CAPTURE_WINDOW_PICKER_OPTION = "capture-window-picker"
CAPTURE_LAST_REGION_OPTION = "capture-last-region"


class GreenshotApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APPLICATION_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._tray_icon = None
        self.add_main_option(
            CAPTURE_REGION_OPTION, ord("r"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Start a region capture", None,
        )
        self.add_main_option(
            CAPTURE_FULL_SCREEN_OPTION, ord("f"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Capture the whole screen", None,
        )
        self.add_main_option(
            CAPTURE_ACTIVE_WINDOW_OPTION, ord("w"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Capture the active window", None,
        )
        self.add_main_option(
            CAPTURE_WINDOW_PICKER_OPTION, ord("p"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Pick a window to capture", None,
        )
        self.add_main_option(
            CAPTURE_LAST_REGION_OPTION, ord("l"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Repeat the last captured region", None,
        )
        self.last_region = None
        self._repeat_item = None
        self._open_editors = []

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Window.set_default_icon_from_file(str(LOGO_PATH))
        self._tray_icon = self._build_tray_icon()
        maybe_run_first_run_setup()

    def do_command_line(self, command_line):
        self.activate()
        options = command_line.get_options_dict()
        if options.contains(CAPTURE_REGION_OPTION):
            self.start_region_capture()
        elif options.contains(CAPTURE_FULL_SCREEN_OPTION):
            self.start_full_screen_capture()
        elif options.contains(CAPTURE_ACTIVE_WINDOW_OPTION):
            self.start_active_window_capture()
        elif options.contains(CAPTURE_WINDOW_PICKER_OPTION):
            self.start_window_picker()
        elif options.contains(CAPTURE_LAST_REGION_OPTION):
            self.start_last_region_capture()
        return 0

    def do_activate(self):
        # Keeps the app alive with no window of its own; the tray icon
        # is the only always-visible UI. hold()/release() bracket the
        # app's lifetime independent of any window being open.
        self.hold()

    def start_capture(self) -> None:
        """Kept as the default single-click tray action - region
        select, matching Greenshot's Windows tray default. Mouse
        cursor forced off, same as every other tray-triggered capture
        below - see start_region_capture's docstring."""
        self.start_region_capture(capture_mouse_cursor=False)

    def _remember_region(self, rect) -> None:
        self.last_region = rect

    def register_editor_window(self, editor) -> None:
        self._open_editors.append(editor)

    def unregister_editor_window(self, editor) -> None:
        if editor in self._open_editors:
            self._open_editors.remove(editor)

    def _block_if_editor_open(self) -> bool:
        """True (after focusing the existing editor instead) if a new
        capture shouldn't start right now because one's already open.

        Without this, triggering a hotkey while EditorWindow is open
        produces a confusing, silent no-op - reported live: the
        capture overlay/destination-picker flow never visibly
        appeared, though the app didn't hang either. Root cause wasn't
        pinned down precisely (Cinnamon/Muffin focus-stealing
        prevention likely keeps the newly-created override-redirect
        overlay from actually receiving input while the editor already
        has focus), but disallowing overlapping captures avoids the
        whole scenario rather than chasing that edge case, and matches
        the reasonable expectation that starting a new capture
        mid-annotation isn't something you'd want to happen anyway.
        """
        if not self._open_editors:
            return False
        self._open_editors[-1].present()
        return True

    def start_region_capture(self, capture_mouse_cursor: bool = True) -> None:
        """``capture_mouse_cursor`` faithfully replicates Windows'
        own asymmetry (CaptureHelper.cs's ``_captureMouseCursor``
        parameter, see PluginHelper.cs:141): hotkey/CLI invocations
        (do_command_line, the default True here) defer to the
        Preferences "Capture mouse cursor" setting, but every
        tray-icon-triggered capture below passes False, hardcoding
        the cursor off regardless of that setting - matching
        MainForm.cs's tray context-menu handlers, which do the same.
        The reasoning carries over unchanged: by the time you've
        clicked the tray icon or one of its menu items, your mouse is
        over the icon/menu, not your content, so showing it there
        would be misleading. See ui/capture_modes.py's module
        docstring and REQUIREMENTS.md's cursor auto-capture section
        for the full citation trail.
        """
        if self._block_if_editor_open():
            return
        start_region_capture(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_full_screen_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        start_full_screen_capture(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_active_window_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        start_active_window_capture(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_window_picker(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        start_window_picker(on_captured=self._remember_region, capture_mouse_cursor=capture_mouse_cursor)

    def start_last_region_capture(self, capture_mouse_cursor: bool = True) -> None:
        if self._block_if_editor_open():
            return
        # Deliberately not chained through _remember_region: the
        # region being repeated already *is* self.last_region, so
        # there's nothing new to record.
        start_last_region_capture(self.last_region, capture_mouse_cursor=capture_mouse_cursor)

    def _build_tray_icon(self) -> Gtk.StatusIcon:
        icon = Gtk.StatusIcon()
        icon.set_from_file(str(LOGO_PATH))
        icon.set_tooltip_text("Greenshot Linux")
        icon.connect("activate", lambda _icon: self.start_capture())

        menu = Gtk.Menu()
        region_item = Gtk.MenuItem(label="Capture Region")
        region_item.connect("activate", lambda _item: self.start_region_capture(capture_mouse_cursor=False))
        menu.append(region_item)

        full_screen_item = Gtk.MenuItem(label="Capture Full Screen")
        full_screen_item.connect("activate", lambda _item: self.start_full_screen_capture(capture_mouse_cursor=False))
        menu.append(full_screen_item)

        active_window_item = Gtk.MenuItem(label="Capture Active Window")
        active_window_item.connect(
            "activate", lambda _item: self.start_active_window_capture(capture_mouse_cursor=False)
        )
        menu.append(active_window_item)

        window_picker_item = Gtk.MenuItem(label="Capture Window...")
        window_picker_item.connect("activate", lambda _item: self.start_window_picker(capture_mouse_cursor=False))
        menu.append(window_picker_item)

        self._repeat_item = Gtk.MenuItem(label="Repeat Last Region")
        self._repeat_item.connect(
            "activate", lambda _item: self.start_last_region_capture(capture_mouse_cursor=False)
        )
        self._repeat_item.set_sensitive(False)  # no region captured yet
        menu.append(self._repeat_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _item: self.quit())
        menu.append(quit_item)
        menu.show_all()

        icon.connect(
            "popup-menu",
            lambda _icon, button, time: self._show_tray_menu(menu, button, time),
        )
        return icon

    def _show_tray_menu(self, menu: Gtk.Menu, button: int, time: int) -> None:
        self._repeat_item.set_sensitive(self.last_region is not None)
        menu.popup(None, None, None, None, button, time)


def main() -> int:
    # Explicit rather than relying on argv[0]-basename inference (GTK/
    # GLib's default): keeps WM_CLASS ("greenshot-linux") matching the
    # packaged .desktop launcher's StartupWMClass regardless of how
    # this entry point actually gets invoked (bare command on PATH,
    # absolute path, a symlink, etc.) - a real gotcha for interpreted-
    # language GTK apps, confirmed via research before packaging.
    GLib.set_prgname("greenshot-linux")
    app = GreenshotApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
