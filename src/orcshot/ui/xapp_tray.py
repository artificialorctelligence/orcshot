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

import os
import sys
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, GObject, Gtk

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


def bind_action_enabled_states(menu: Gtk.Menu, app) -> None:
    """Mirrors each real `app.lookup_action(name)` action's `enabled`
    onto its proxy in menu's "app" action group. Gtk.Menu.new_from_model
    reads item sensitivity from that group, not from app itself, so
    without this a disabled real action (e.g. tray-repeat_region
    before the first capture) renders as clickable and silently drops
    the forwarded activation (GSimpleAction ignores activate() while
    disabled)."""
    proxy = menu.get_action_group("app")
    for name in proxy.list_actions():
        real = app.lookup_action(name)
        if real is not None:
            real.bind_property("enabled", proxy.lookup_action(name), "enabled", GObject.BindingFlags.SYNC_CREATE)


def _forward_once(forward, name) -> bool:
    forward(name)
    return GLib.SOURCE_REMOVE


def running_on_cinnamon(environ=None) -> bool:
    """Whether the session desktop is Cinnamon, from XDG_CURRENT_DESKTOP
    (a colon-separated list; Cinnamon reports "X-Cinnamon"). Deliberately
    not hotkey_setup.cinnamon_keybindings_available(): that reads a host
    GSettings schema, which a Flatpak sandbox cannot see - found live on
    2026-09-12, where it answered False on a real Cinnamon desktop. The
    environment variable crosses the sandbox boundary; the schema does not."""
    if environ is None:
        environ = os.environ
    return any(part.lower() in ("x-cinnamon", "cinnamon") for part in environ.get("XDG_CURRENT_DESKTOP", "").split(":"))


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
    menu = build_menu(app._tray_menu, lambda name: app.activate_action(name, None))
    bind_action_enabled_states(menu, app)
    icon.set_secondary_menu(menu)

    def on_activate(_icon, button, _time):
        if button == 1:
            app.activate_action(LEFT_CLICK_ACTION, None)

    icon.connect("activate", on_activate)
    return icon
