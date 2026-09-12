"""The Cinnamon tray: an XApp.StatusIcon owned by this process, showing
the same Gio.Menu the GNOME Shell extension renders. Replaces the
retired Cinnamon panel applet (see BACKLOG #208): a panel applet
always carries Cinnamon's own About/Remove entries, a status icon
does not, and a status icon needs nothing installed on any channel.

Two things were verified on a real Cinnamon panel before this existed
(spec docs/superpowers/specs/2026-09-12-xapp-status-icon-design.md):
Gtk.Menu.new_from_model renders the model's per-item icons, and a
capture started from the menu contains the menu unless the menu is
popped down and the action delayed - hence build_menu's proxy.
"""

from __future__ import annotations

import sys
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from orcshot.i18n import _

ICON_NAME = "orcshot"
LEFT_CLICK_ACTION = "tray-region"


def proxy_action_names(model: Gio.MenuModel) -> list[str]:
    """Bare names of every `app.<name>` action the model references,
    depth-first through section and submenu links, first occurrence
    wins."""
    names: list[str] = []

    def walk(m: Gio.MenuModel) -> None:
        for i in range(m.get_n_items()):
            action = m.get_item_attribute_value(i, "action", GLib.VariantType("s"))
            if action is not None:
                name = action.get_string()
                if name.startswith("app."):
                    bare = name[4:]
                    if bare not in names:
                        names.append(bare)
            for link in ("section", "submenu"):
                sub = m.get_item_link(i, link)
                if sub is not None:
                    walk(sub)

    walk(model)
    return names


def build_menu(model: Gio.MenuModel, forward: Callable[[str], None], delay_ms: int = 150) -> Gtk.Menu:
    """A Gtk.Menu for the model whose `app.*` actions are proxied: each
    pops the menu down and calls forward(bare_name) delay_ms later. The
    delay is what keeps the menu out of the capture it starts - the
    app's own one-main-loop-turn deferral (app.py's _defer) is not
    enough for a popup that is still fading, measured 2026-09-12."""
    menu = Gtk.Menu.new_from_model(model)
    proxy = Gio.SimpleActionGroup()
    for name in proxy_action_names(model):
        action = Gio.SimpleAction.new(name, None)

        def fire(_action, _param, name=name):
            menu.popdown()
            GLib.timeout_add(delay_ms, _forward_once, forward, name)

        action.connect("activate", fire)
        proxy.add_action(action)
    menu.insert_action_group("app", proxy)
    menu.show_all()
    return menu


def _forward_once(forward, name) -> bool:
    forward(name)
    return GLib.SOURCE_REMOVE


def create_status_icon(app):
    """The icon, or None (with one stderr line) when the XApp typelib is
    not installed - a Cinnamon machine without gir1.2-xapp-1.0 gets no
    tray rather than a crash. Kept on the app by the caller so it lives
    exactly as long as the process; nothing to tear down on quit."""
    try:
        gi.require_version("XApp", "1.0")
        from gi.repository import XApp
    except (ImportError, ValueError) as error:
        print(f"[orcshot] XApp status icon unavailable ({error}); no Cinnamon tray icon", file=sys.stderr, flush=True)
        return None

    icon = XApp.StatusIcon.new()
    icon.set_icon_name(ICON_NAME)
    icon.set_tooltip_text(_("Orcshot"))
    icon.set_secondary_menu(build_menu(app._tray_menu, lambda name: app.activate_action(name, None)))

    def on_activate(_icon, button, _time):
        if button == 1:
            app.activate_action(LEFT_CLICK_ACTION, None)

    icon.connect("activate", on_activate)
    return icon
