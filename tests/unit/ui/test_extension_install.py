"""Pure coverage for ui/extension_install.py: which channel/desktop pair
gets which redirect, and the one InstallRemoteExtension call. The
dialogs themselves need a display and are verified live (plan Task 7)."""

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib
import pytest

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
        self._reply = reply

    def call_sync(self, dest, path, iface, method, args, reply_type, flags, timeout, cancellable):
        self.calls.append((dest, path, iface, method, args.unpack()))
        return GLib.Variant("(s)", (self._reply,))


def test_request_gnome_install_asks_the_shell():
    bus = FakeBus()
    assert request_gnome_install("orcshot@orcshot.org", bus=bus) == "successful"
    (dest, path, iface, method, args), = bus.calls
    assert (dest, path, iface, method, args) == (
        "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", "InstallRemoteExtension",
        ("orcshot@orcshot.org",),
    )


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
