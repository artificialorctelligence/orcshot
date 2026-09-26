"""Detail-level tests for ui/xapp_tray.py: the values and names a typo
would silently break, rather than the happy paths (those are
test_xapp_tray.py). Every survivor these kill was a change to a signal
name, an icon name, a delay, a button number or a menu link type that the
happy-path tests could not see.

XApp's own typelib is faked. It is installed on a Cinnamon dev machine, so
without the fake `from gi.repository import XApp` succeeds and
create_status_icon puts a real icon on the live tray of whoever runs the
suite; the real icon is verified live instead (VERIFICATION.md). Gtk is
initialised headless - a Gtk.Menu builds without a display, only showing
one needs it. Helpers are copied from test_xapp_tray.py rather than
imported: pytest's importlib mode means test modules must not import each
other.
"""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from orcshot.ui import xapp_tray

_UNSET = object()


def _model():
    menu = Gio.Menu()
    section = Gio.Menu()
    section.append("Capture Region", "app.tray-region")
    section.append("Capture Full Screen", "app.tray-full_screen")
    menu.append_section(None, section)
    menu.append("Quit", "app.tray-quit")
    return menu


class _FakeStatusIcon:
    """Records what create_status_icon does to the icon. Deliberately not a
    GObject: connect() here only has to remember the signal name, which is
    the contract with XApp that a typo would silently break."""

    def __init__(self):
        self.icon_name = _UNSET
        self.tooltip = _UNSET
        self.secondary_menu = _UNSET
        self.connections = []

    def set_icon_name(self, name):
        self.icon_name = name

    def set_tooltip_text(self, text):
        self.tooltip = text

    def set_secondary_menu(self, menu):
        self.secondary_menu = menu

    def connect(self, signal, handler):
        self.connections.append((signal, handler))


class _FakeApp:
    """Stands in for the Gio.Application: the same lookup_action() and
    activate_action() surface create_status_icon uses, nothing else."""

    def __init__(self, model):
        self._tray_menu = model
        self.activated = []
        self._actions = Gio.SimpleActionGroup()

    def add_real_action(self, name, enabled=True):
        action = Gio.SimpleAction.new(name, None)
        action.set_enabled(enabled)
        self._actions.add_action(action)
        return action

    def lookup_action(self, name):
        return self._actions.lookup_action(name)

    def activate_action(self, name, param):
        self.activated.append((name, param))


def _with_fake_xapp(monkeypatch):
    """Makes `from gi.repository import XApp` inside create_status_icon hand
    back a recorder, and records the gi.require_version call it makes first.
    Returns (required_versions, icons_created). Setting the attribute on
    gi.repository is what keeps the real typelib out of it: gi.repository's
    lazy importer only runs when normal attribute lookup fails."""
    import gi as gi_module
    from gi import repository

    required = []
    real_require = gi_module.require_version

    def recording_require(namespace, version):
        required.append((namespace, version))
        if namespace == "XApp":
            return None
        return real_require(namespace, version)

    created = []

    class FakeXApp:
        class StatusIcon:
            @staticmethod
            def new():
                icon = _FakeStatusIcon()
                created.append(icon)
                return icon

    monkeypatch.setattr(gi_module, "require_version", recording_require)
    monkeypatch.setattr(repository, "XApp", FakeXApp, raising=False)
    return required, created


def _capture_timeouts(monkeypatch):
    """Intercepts what build_menu's proxy hands GLib.timeout_add, so the
    deferred forward can be run by hand. Synchronous on purpose: a real
    main loop swallows an exception raised inside the callback (it reaches
    GLib, which prints it and carries on), and a callback that wrongly
    reports SOURCE_CONTINUE leaks a repeating timeout into every later
    test - which, under `mutmut run`'s one-process-many-mutants model,
    aborted the whole run."""
    scheduled = []

    def fake_timeout_add(delay, callback=None, *args):
        scheduled.append((delay, callback, args))
        return len(scheduled)

    monkeypatch.setattr(xapp_tray.GLib, "timeout_add", fake_timeout_add)
    return scheduled


def _tray_app():
    model = Gio.Menu()
    section = Gio.Menu()
    section.append("Capture Region", "app.tray-region")
    section.append("Repeat Last Region", "app.tray-repeat_region")
    model.append_section(None, section)
    model.append("Quit", "app.tray-quit")
    app = _FakeApp(model)
    app.add_real_action("tray-region")
    app.add_real_action("tray-repeat_region", enabled=False)  # no capture yet
    app.add_real_action("tray-quit")
    return app


def test_proxy_action_names_descends_into_submenus():
    inner = Gio.Menu()
    inner.append("5 seconds", "app.tray-delay_5")
    outer = Gio.Menu()
    outer.append_submenu("Delayed Capture", inner)
    assert xapp_tray.proxy_action_names(outer) == ["tray-delay_5"]


def test_proxy_action_names_ignores_an_action_attribute_that_is_not_a_string():
    # The "s" VariantType handed to get_item_attribute_value is what makes a
    # malformed model skip the item instead of crashing the whole tray build
    # on a None from Variant.get_string().
    model = Gio.Menu()
    broken = Gio.MenuItem.new("Broken", None)
    broken.set_attribute_value("action", GLib.Variant("i", 7))
    model.append_item(broken)
    model.append("Quit", "app.tray-quit")
    assert xapp_tray.proxy_action_names(model) == ["tray-quit"]


def test_build_menu_schedules_the_forward_with_the_measured_150ms_delay(monkeypatch):
    # 150 ms is the measured-live figure the module docstring rests on: any
    # less and the still-fading popup lands in the capture it started.
    Gtk.init_check([])
    scheduled = _capture_timeouts(monkeypatch)
    menu = xapp_tray.build_menu(_model(), lambda name: None)
    menu.get_action_group("app").activate_action("tray-region", None)
    assert [delay for delay, _callback, _args in scheduled] == [150]


def test_the_scheduled_callback_forwards_the_name_once_and_disarms_itself(monkeypatch):
    # The timeout callback reports SOURCE_REMOVE itself rather than letting
    # the forward's own return value decide. Hand the timeout the forward
    # directly and any forward that happens to return something truthy
    # re-fires the action every delay_ms, forever.
    Gtk.init_check([])
    scheduled = _capture_timeouts(monkeypatch)
    calls = []

    def forward(name):
        calls.append(name)
        return True

    menu = xapp_tray.build_menu(_model(), forward, delay_ms=10)
    menu.get_action_group("app").activate_action("tray-full_screen", None)

    delay, callback, args = scheduled[0]
    assert delay == 10
    assert callback(*args) is GLib.SOURCE_REMOVE
    assert calls == ["tray-full_screen"]


def test_create_status_icon_requires_the_xapp_typelib_by_its_exact_name(monkeypatch):
    Gtk.init_check([])
    required, _created = _with_fake_xapp(monkeypatch)
    assert xapp_tray.create_status_icon(_tray_app()) is not None
    assert required == [("XApp", "1.0")]


def test_create_status_icon_sets_the_orcshot_icon_and_tooltip(monkeypatch):
    Gtk.init_check([])
    _required, created = _with_fake_xapp(monkeypatch)
    icon = xapp_tray.create_status_icon(_tray_app())
    assert created == [icon]
    assert icon.icon_name == "orcshot"
    assert icon.tooltip == "Orcshot"


def test_create_status_icon_hangs_the_forwarding_menu_off_the_icon(monkeypatch):
    Gtk.init_check([])
    _required, _created = _with_fake_xapp(monkeypatch)
    app = _tray_app()
    icon = xapp_tray.create_status_icon(app)

    assert isinstance(icon.secondary_menu, Gtk.Menu)
    group = icon.secondary_menu.get_action_group("app")
    assert set(group.list_actions()) == {"tray-region", "tray-repeat_region", "tray-quit"}

    scheduled = _capture_timeouts(monkeypatch)
    group.activate_action("tray-quit", None)
    assert app.activated == []          # deferred, so the menu is gone first
    _delay, callback, args = scheduled[0]
    callback(*args)
    assert app.activated == [("tray-quit", None)]


def test_create_status_icon_binds_the_menus_enabled_states_to_the_app(monkeypatch):
    Gtk.init_check([])
    _required, _created = _with_fake_xapp(monkeypatch)
    icon = xapp_tray.create_status_icon(_tray_app())
    group = icon.secondary_menu.get_action_group("app")
    assert group.lookup_action("tray-repeat_region").get_enabled() is False
    assert group.lookup_action("tray-region").get_enabled() is True


def test_create_status_icon_connects_activate_and_only_left_click_captures(monkeypatch):
    Gtk.init_check([])
    _required, _created = _with_fake_xapp(monkeypatch)
    app = _tray_app()
    icon = xapp_tray.create_status_icon(app)

    assert [signal for signal, _handler in icon.connections] == ["activate"]
    handler = icon.connections[0][1]

    handler(icon, 1, 0)
    assert app.activated == [("tray-region", None)]
    for other_button in (2, 3):
        handler(icon, other_button, 0)
    assert app.activated == [("tray-region", None)]


def test_running_on_cinnamon_reads_the_real_environment_by_default(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "X-Cinnamon")
    assert xapp_tray.running_on_cinnamon() is True
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    assert xapp_tray.running_on_cinnamon() is False
