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

REQUIREMENTS.md calls for hotkey auto-configuration "on first run with
a one-time user confirmation" - that confirmation UI (and actually
calling hotkey_setup.configure_hotkey, which writes to the user's real
desktop keybinding configuration) is intentionally not wired up here
yet; see hotkey_setup.py's module docstring for why.
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

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self._tray_icon = self._build_tray_icon()

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
        select, matching Greenshot's Windows tray default."""
        self.start_region_capture()

    def _remember_region(self, rect) -> None:
        self.last_region = rect

    def start_region_capture(self) -> None:
        start_region_capture(on_captured=self._remember_region)

    def start_full_screen_capture(self) -> None:
        start_full_screen_capture(on_captured=self._remember_region)

    def start_active_window_capture(self) -> None:
        start_active_window_capture(on_captured=self._remember_region)

    def start_window_picker(self) -> None:
        start_window_picker(on_captured=self._remember_region)

    def start_last_region_capture(self) -> None:
        # Deliberately not chained through _remember_region: the
        # region being repeated already *is* self.last_region, so
        # there's nothing new to record.
        start_last_region_capture(self.last_region)

    def _build_tray_icon(self) -> Gtk.StatusIcon:
        icon = Gtk.StatusIcon()
        icon.set_from_icon_name("applets-screenshooter")
        icon.set_tooltip_text("Greenshot Linux")
        icon.connect("activate", lambda _icon: self.start_capture())

        menu = Gtk.Menu()
        region_item = Gtk.MenuItem(label="Capture Region")
        region_item.connect("activate", lambda _item: self.start_region_capture())
        menu.append(region_item)

        full_screen_item = Gtk.MenuItem(label="Capture Full Screen")
        full_screen_item.connect("activate", lambda _item: self.start_full_screen_capture())
        menu.append(full_screen_item)

        active_window_item = Gtk.MenuItem(label="Capture Active Window")
        active_window_item.connect("activate", lambda _item: self.start_active_window_capture())
        menu.append(active_window_item)

        window_picker_item = Gtk.MenuItem(label="Capture Window...")
        window_picker_item.connect("activate", lambda _item: self.start_window_picker())
        menu.append(window_picker_item)

        self._repeat_item = Gtk.MenuItem(label="Repeat Last Region")
        self._repeat_item.connect("activate", lambda _item: self.start_last_region_capture())
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
    app = GreenshotApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
