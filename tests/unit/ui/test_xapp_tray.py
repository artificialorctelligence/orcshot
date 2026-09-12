"""Pure coverage for ui/xapp_tray.py. Gtk is initialised headless
(Gtk.init_check) - a Gtk.Menu can be built without a display; only
showing it needs one. XApp itself is never imported here: the icon
factory is tested for its no-XApp path, and the real icon is verified
live on a Cinnamon panel (VERIFICATION.md)."""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk
import pytest

from orcshot.ui import xapp_tray


def _model():
    menu = Gio.Menu()
    section = Gio.Menu()
    section.append("Capture Region", "app.tray-region")
    section.append("Capture Full Screen", "app.tray-full_screen")
    menu.append_section(None, section)
    menu.append("Quit", "app.tray-quit")
    return menu


def _spin(ms):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, loop.quit)
    loop.run()


def test_proxy_action_names_walks_sections_without_duplicates():
    assert xapp_tray.proxy_action_names(_model()) == ["tray-region", "tray-full_screen", "tray-quit"]


def test_build_menu_forwards_after_the_delay_not_synchronously():
    Gtk.init_check([])
    forwarded = []
    menu = xapp_tray.build_menu(_model(), forwarded.append, delay_ms=50)
    group = menu.get_action_group("app")
    assert set(group.list_actions()) == {"tray-region", "tray-full_screen", "tray-quit"}
    group.activate_action("tray-full_screen", None)
    assert forwarded == []            # nothing yet - the menu is still popping down
    _spin(120)
    assert forwarded == ["tray-full_screen"]


def test_build_menu_default_delay_is_150ms():
    Gtk.init_check([])
    forwarded = []
    menu = xapp_tray.build_menu(_model(), forwarded.append)
    menu.get_action_group("app").activate_action("tray-region", None)
    _spin(100)
    assert forwarded == []            # 100 ms < 150 ms
    _spin(100)
    assert forwarded == ["tray-region"]


def test_bind_action_enabled_states_mirrors_the_real_actions_enabled_flag():
    Gtk.init_check([])
    real_actions = Gio.SimpleActionGroup()  # stand-in for the app: same lookup_action() as Gio.Application
    disabled = Gio.SimpleAction.new("tray-repeat_region", None)
    disabled.set_enabled(False)
    real_actions.add_action(disabled)

    model = Gio.Menu()
    model.append("Repeat Last Region", "app.tray-repeat_region")
    menu = xapp_tray.build_menu(model, lambda name: None)

    xapp_tray.bind_action_enabled_states(menu, real_actions)
    proxy = menu.get_action_group("app").lookup_action("tray-repeat_region")
    assert proxy.get_enabled() is False

    disabled.set_enabled(True)
    assert proxy.get_enabled() is True


def test_create_status_icon_without_xapp_returns_none_and_logs(monkeypatch, capsys):
    import gi as gi_module
    real = gi_module.require_version

    def refuse(namespace, version):
        if namespace == "XApp":
            raise ValueError("Namespace XApp not available")
        return real(namespace, version)

    monkeypatch.setattr(gi_module, "require_version", refuse)

    class App:
        _tray_menu = _model()
        def activate_action(self, name, param): pass

    assert xapp_tray.create_status_icon(App()) is None
    assert "XApp" in capsys.readouterr().err


@pytest.mark.parametrize("value,expected", [
    ("X-Cinnamon", True),
    ("Cinnamon", True),
    ("X-Cinnamon:GNOME", True),
    ("ubuntu:GNOME", False),
    ("", False),
])
def test_running_on_cinnamon_reads_xdg_current_desktop(value, expected):
    assert xapp_tray.running_on_cinnamon({"XDG_CURRENT_DESKTOP": value}) is expected


def test_running_on_cinnamon_with_no_variable_is_false():
    assert xapp_tray.running_on_cinnamon({}) is False
