"""The extension-install dialog itself - the mechanism the whole Snap Store
confinement decision was built around (BACKLOG #205), so a silent change
here matters more than the line count suggests.

Everything that leaves the process is faked: the shell bridge (no D-Bus),
Gio.AppInfo.launch_default_for_uri (no browser) and request_gnome_install
(no org.gnome.Shell call). Nothing is written anywhere.

These tests pin the dialog's *observable* build - the title GNOME shows in
the window list, which button Enter activates, the spec-verbatim text, the
margins - because that is what a user sees and what a refactor can break
without any test noticing (plan Task 9, 84 surviving mutants).
"""

import os

import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk
import pytest

from orcshot.capture import shell_bridge
from orcshot.ui import extension_install
from orcshot.ui.extension_install import EGO_URL, EXTENSION_UUID, _TEXT

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="builds real Gtk widgets; needs a display"
)


class FakeBridge:
    """The shell bridge before Hello: no capabilities, and a record of who
    subscribed so the dialog's unsubscribe-on-close can be checked."""

    def __init__(self):
        self.capabilities = frozenset()
        self.subscribed = []
        self.unsubscribed = []

    def on_capabilities_changed(self, callback):
        self.subscribed.append(callback)

    def off_capabilities_changed(self, callback):
        self.unsubscribed.append(callback)


class Dialog:
    """What show_install_dialog actually built, plus the fakes it talked to."""

    def __init__(self, gtk_dialog, bridge, launched, installed):
        self.d = gtk_dialog
        self.bridge = bridge
        self.launched = launched
        self.installed = installed
        self.responses = []
        self.destroyed = False
        # Connected after the dialog's own handler, so a response the dialog
        # reacts to by destroying itself never reaches this recorder - hence
        # the separate destroyed flag.
        self.d.connect("response", lambda _d, response: self.responses.append(response))
        self.d.connect("destroy", lambda _d: setattr(self, "destroyed", True))

    @property
    def labels(self):
        return [c for c in self.d.get_content_area().get_children() if isinstance(c, Gtk.Label)]

    @property
    def heading(self):
        return self.labels[0]

    @property
    def text(self):
        return self.labels[1]

    def button(self, response):
        return self.d.get_widget_for_response(response)

    @property
    def callback(self):
        """The one capabilities listener the dialog registered."""
        (callback,) = self.bridge.subscribed
        return callback


@pytest.fixture
def build(monkeypatch):
    """show_install_dialog(plan, parent) with every boundary faked, handing
    back the dialog it built."""
    built = []
    parents = []

    def _build(plan, install_error=None):
        bridge = FakeBridge()
        monkeypatch.setattr(shell_bridge, "_bridge", bridge)

        launched, installed = [], []
        monkeypatch.setattr(
            extension_install.Gio.AppInfo,
            "launch_default_for_uri",
            lambda *args: launched.append(args),
        )

        def fake_install(uuid):
            installed.append(uuid)
            if install_error is not None:
                raise install_error
            return "successful"

        monkeypatch.setattr(extension_install, "request_gnome_install", fake_install)

        parent = Gtk.Window()
        parents.append(parent)
        # Gtk.Dialog cannot be monkeypatched - gi does isinstance() against
        # the class it finds on the module, so replacing it breaks widget
        # construction. Diff the toplevels instead.
        # Keep real references, and compare by identity: a set of id()s is
        # wrong here, because a wrapper freed between the two calls lets the
        # new dialog be allocated at the same address and look pre-existing.
        before = list(Gtk.Window.list_toplevels())
        extension_install.show_install_dialog(plan, parent)
        (gtk_dialog,) = [
            w for w in Gtk.Window.list_toplevels()
            if isinstance(w, Gtk.Dialog) and not any(w is old for old in before)
        ]
        built.append(gtk_dialog)
        wrapper = Dialog(gtk_dialog, bridge, launched, installed)
        wrapper.parent = parent
        return wrapper

    yield _build
    for dialog in built:
        dialog.destroy()
    for parent in parents:
        parent.destroy()


def test_the_dialog_is_a_child_of_the_window_that_asked_for_it(build):
    """Not transient_for=None: a floating setup dialog on GNOME can end up
    behind the editor with nothing telling the user it is there."""
    dialog = build("snap-gnome")
    assert dialog.d.get_title() == "Orcshot Setup"
    assert dialog.d.get_transient_for() is dialog.parent


def test_enter_means_do_it_not_later(build):
    """GTK focuses the first button added, which is Later - found live on
    the VM, where Enter dismissed the dialog instead of installing."""
    dialog = build("snap-gnome")
    assert dialog.d.get_default_widget() is dialog.button(Gtk.ResponseType.OK)


def test_snap_on_gnome_offers_the_extensions_site(build):
    dialog = build("snap-gnome")
    assert dialog.button(Gtk.ResponseType.CANCEL).get_label() == "Later"
    assert dialog.button(Gtk.ResponseType.OK).get_label() == "Open extensions.gnome.org"


def test_flatpak_on_gnome_offers_the_install_gnome_will_confirm(build):
    dialog = build("flatpak-gnome")
    assert dialog.button(Gtk.ResponseType.CANCEL).get_label() == "Later"
    assert dialog.button(Gtk.ResponseType.OK).get_label() == "Install extension"


@pytest.mark.parametrize("plan", ["snap-gnome", "flatpak-gnome"])
def test_the_heading_is_the_bolded_spec_title(build, plan):
    dialog = build(plan)
    heading = dialog.heading
    assert heading.get_label() == "<b>One more step for the tray icon and Wayland capture</b>"
    assert heading.get_use_markup() is True
    assert heading.get_xalign() == 0.0


@pytest.mark.parametrize("plan", ["snap-gnome", "flatpak-gnome"])
def test_the_body_is_the_spec_text_wrapped_to_seventy_columns(build, plan):
    dialog = build(plan)
    text = dialog.text
    assert text.get_label() == _TEXT[plan][1]
    assert text.get_line_wrap() is True
    assert text.get_xalign() == 0.0
    assert text.get_max_width_chars() == 70


def test_the_snap_body_spells_out_the_manual_steps(build):
    """Snap has no route to GNOME's installer, so the text has to carry the
    whole procedure including the browser-connector caveat (spec 7)."""
    body = build("snap-gnome").text.get_label()
    assert "Click Open extensions.gnome.org below." in body
    assert "switch the toggle to ON" in body
    assert "gnome-browser-connector" in body


def test_both_labels_are_inset_from_the_dialog_edges(build):
    dialog = build("snap-gnome")
    for label in (dialog.heading, dialog.text):
        assert (label.get_margin_start(), label.get_margin_end(), label.get_margin_top()) == (12, 12, 8)


def test_the_heading_comes_before_the_body(build):
    dialog = build("snap-gnome")
    assert len(dialog.labels) == 2
    assert dialog.labels[0].get_use_markup() is True
    assert dialog.labels[1].get_line_wrap() is True


def test_hello_while_the_dialog_is_open_closes_it(build):
    """The dialog closes itself when the extension says Hello - the whole
    point of subscribing, and the only way the user is not left staring at
    a dialog for something that is now running."""
    dialog = build("snap-gnome")
    callback = dialog.callback
    callback(frozenset({"tray", "region"}))
    assert dialog.destroyed is True
    assert dialog.bridge.unsubscribed == [callback]


def test_losing_the_extension_does_not_close_the_dialog(build):
    """The same signal fires with an empty set when the extension goes
    away; that must not be read as 'installed'."""
    dialog = build("snap-gnome")
    dialog.callback(frozenset())
    assert dialog.responses == []
    assert dialog.destroyed is False
    assert dialog.bridge.unsubscribed == []


def test_later_closes_the_dialog_and_unsubscribes(build):
    """Later leaves Orcshot fully usable on the portal path - it must not
    install anything, and it must drop the listener so the destroyed
    dialog is not called back into."""
    dialog = build("snap-gnome")
    callback = dialog.callback
    dialog.d.response(Gtk.ResponseType.CANCEL)
    assert (dialog.launched, dialog.installed) == ([], [])
    assert dialog.destroyed is True
    assert dialog.bridge.unsubscribed == [callback]


def test_open_ego_launches_the_site_through_the_portal_and_stays_open(build):
    """Snap: the url is opened and the dialog deliberately stays open and
    subscribed, waiting for Hello."""
    dialog = build("snap-gnome")
    dialog.d.response(Gtk.ResponseType.OK)
    assert dialog.launched == [(EGO_URL, None)]
    assert dialog.installed == []
    assert dialog.destroyed is False
    assert dialog.bridge.unsubscribed == []


def test_install_extension_asks_gnome_and_stays_open(build):
    """Flatpak: no url, so GNOME is asked to install the extension by uuid
    and the dialog waits for Hello rather than closing on 'successful'."""
    dialog = build("flatpak-gnome")
    dialog.d.response(Gtk.ResponseType.OK)
    assert dialog.installed == [EXTENSION_UUID]
    assert dialog.launched == []
    assert dialog.destroyed is False
    assert dialog.bridge.unsubscribed == []


def test_a_refused_install_is_reported_in_the_dialog(build):
    """GLib.Error out of InstallRemoteExtension must reach the user inside
    the dialog - appended to the body, not replacing it, and not crashing
    the response handler."""
    dialog = build("flatpak-gnome", install_error=GLib.Error("Extension orcshot@orcshot.org not found"))
    dialog.d.response(Gtk.ResponseType.OK)
    assert dialog.text.get_text() == (
        _TEXT["flatpak-gnome"][1]
        + "\n\nGNOME could not install it: Extension orcshot@orcshot.org not found"
    )
    assert dialog.destroyed is False
    assert dialog.bridge.unsubscribed == []
