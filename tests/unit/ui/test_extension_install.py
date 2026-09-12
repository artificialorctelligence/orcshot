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
    ("flatpak", "cinnamon", "flatpak-cinnamon"),
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
