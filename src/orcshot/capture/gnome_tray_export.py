"""Publishes Orcshot's Wayland tray menu as a real Gio.Menu, exported
over D-Bus on this app's own already-owned connection - the
replacement for the AyatanaAppIndicator3/dbusmenu path on Wayland (see
docs/superpowers/specs/2026-08-28-wayland-capture-redesign-design.md).

Deliberately doesn't export a new Gio.SimpleActionGroup or own a new
bus name: app.py's own _register_tray_actions() already exports every
tray action automatically via GApplication's standard org.gtk.Actions
interface at /org/orcshot/Orcshot, since this app is already a
registered Gio.Application - this module only needs to publish the
*menu structure* referencing those already-exported actions by name
("app.tray-<mode>", the standard GApplication action-group prefix).
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from orcshot.core.shapes import Color
from orcshot.ui.icons import capture_mode_gicon, stock_icon_gicon

TRAY_MENU_PATH = "/org/orcshot/Orcshot/TrayMenu"

# Same stock icon names app.py's _build_tray_menu (the X11/AppIndicator3
# Gtk.Menu builder) already uses via icons.py's stock_icon_image - task
# #146's "every icon in the wayland version must look like the x11
# version, no exceptions" applies to these three fixed items too, not
# just the 5 hand-drawn capture-mode icons above.
_FIXED_ITEM_ICON_NAMES = {
    "open_file": "document-open-symbolic",
    "preferences": "preferences-system-symbolic",
    "quit": "application-exit-symbolic",
}

# Same 5 capture modes as app.py's _tray_action_handlers(), same
# order _build_tray_menu (the X11/AppIndicator3 Gtk.Menu builder)
# already uses - keep these in sync if that ordering ever changes.
_CAPTURE_MODES = ("region", "full_screen", "active_window", "window_picker", "repeat_region")


def build_tray_menu(labels: dict[str, str], color: Color) -> Gio.Menu:
    """labels maps each of _CAPTURE_MODES to its already-translated
    display text, plus "open_file"/"preferences"/"quit" for the three
    fixed items below the capture modes - same set app.py's
    _build_tray_menu (the Gtk.Menu builder) already needs, so callers
    typically already have all of these translated strings on hand.

    Built as 4 sections (5 capture modes, then Open File, Preferences,
    Quit each alone), not one flat 8-item menu - Gio.Menu.append_section
    is the standard GMenu idiom for "render a divider between these
    groups", matching X11's own _build_tray_menu (three
    Gtk.SeparatorMenuItems between the same four groups) and the old,
    now-deleted Shell-native menu it replaced. extension.js walks these
    section links to insert a PopupSeparatorMenuItem between each group -
    see its own _rebuild for the consuming side.
    """
    capture_modes = Gio.Menu()
    for mode in _CAPTURE_MODES:
        item = Gio.MenuItem.new(labels[mode], f"app.tray-{mode}")
        item.set_icon(capture_mode_gicon(mode, color))
        capture_modes.append_item(item)

    menu = Gio.Menu()
    menu.append_section(None, capture_modes)

    for key, action in (
        ("open_file", "app.tray-open-file"),
        ("preferences", "app.tray-preferences"),
        ("quit", "app.tray-quit"),
    ):
        item = Gio.MenuItem.new(labels[key], action)
        item.set_icon(stock_icon_gicon(_FIXED_ITEM_ICON_NAMES[key], color))
        section = Gio.Menu()
        section.append_item(item)
        menu.append_section(None, section)
    return menu


def export_tray_menu(app: Gio.Application, menu: Gio.Menu, object_path: str = TRAY_MENU_PATH) -> int:
    """Exports on the app's own already-connected D-Bus connection -
    Gio.Application.get_dbus_connection() only returns non-None once
    the application is actually registered (after Gio.Application.run()
    has started, or a manual register() call) - callers must call this
    after that point, not during __init__.
    """
    connection = app.get_dbus_connection()
    return connection.export_menu_model(object_path, menu)
