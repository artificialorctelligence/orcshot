"""Pure coverage for ui/extension_install.py: which channel/desktop pair
gets which redirect, and the one InstallRemoteExtension call. The
dialogs themselves need a display and are verified live (plan Task 7)."""

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
import pytest

from orcshot.ui import extension_install
from orcshot.ui.extension_install import plan_install, request_gnome_install


@pytest.mark.parametrize("channel,desktop,expected", [
    ("deb", "gnome", None),
    ("deb", "cinnamon", None),
    ("flatpak", "gnome", "flatpak-gnome"),
    ("flatpak", "cinnamon", None),
    ("snap", "gnome", "snap-gnome"),
    ("snap", "cinnamon", None),
    ("flatpak", None, None),
    ("flatpak", "kde", None),
])
def test_plan_install(channel, desktop, expected):
    assert plan_install(channel, desktop) == expected


class FakeBus:
    def __init__(self, reply="successful"):
        self.calls = []
        self.call_kwargs = []
        self._reply = reply

    def call_sync(self, dest, path, iface, method, args, reply_type, flags, timeout, cancellable):
        self.calls.append((dest, path, iface, method, args.unpack()))
        self.call_kwargs.append((reply_type, flags, timeout, cancellable))
        return GLib.Variant("(s)", (self._reply,))


def test_request_gnome_install_asks_the_shell():
    bus = FakeBus()
    assert request_gnome_install("orcshot@orcshot.org", bus=bus) == "successful"
    (dest, path, iface, method, args), = bus.calls
    assert (dest, path, iface, method, args) == (
        "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", "InstallRemoteExtension",
        ("orcshot@orcshot.org",),
    )


def test_request_gnome_install_declares_the_reply_type_and_the_long_timeout():
    """GNOME shows its own 'Install extension?' dialog before it answers, so
    the call has to outlast a user reading it - the default 25s timeout
    would abort a dialog the user is still looking at. The reply type is
    declared so a shell that answers with something else fails here rather
    than in unpack()."""
    bus = FakeBus()
    request_gnome_install("orcshot@orcshot.org", bus=bus)
    (reply_type, flags, timeout, cancellable), = bus.call_kwargs
    assert reply_type.dup_string() == "(s)"
    assert flags == Gio.DBusCallFlags.NONE
    assert timeout == 120000
    assert cancellable is None


def test_request_gnome_install_uses_the_session_bus_when_given_none(monkeypatch):
    """The shell lives on the session bus; the bus= argument only exists so
    tests do not need one. No real bus is touched here."""
    asked = []
    bus = FakeBus()

    def fake_bus_get_sync(*args):
        asked.append(args)
        return bus

    monkeypatch.setattr(extension_install.Gio, "bus_get_sync", fake_bus_get_sync)
    assert request_gnome_install("orcshot@orcshot.org") == "successful"
    assert asked == [(Gio.BusType.SESSION, None)]
    assert bus.calls


def test_show_install_dialog_is_a_no_op_when_the_extension_already_said_hello(monkeypatch):
    """Found live on the 26.04 VM: Hello arrives the moment the app owns
    its bus name, before first-run has built any dialog, so a listener
    registered by the dialog never fires and the dialog sits there asking
    the user to install something that is already running."""
    from orcshot.capture import shell_bridge
    from orcshot.ui import extension_install

    class Bridge:
        capabilities = frozenset({"tray"})
        def on_capabilities_changed(self, cb): pytest.fail("must not subscribe")

    monkeypatch.setattr(shell_bridge, "_bridge", Bridge())
    monkeypatch.setattr(extension_install.Gtk, "Dialog", lambda **kw: pytest.fail("must not build a dialog"))
    extension_install.show_install_dialog("flatpak-gnome")
