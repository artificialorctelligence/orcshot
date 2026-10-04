"""The Preferences dialog's five tab builders.

They are module-level functions returning a Gtk.Box, not methods, so
each can be built directly without opening the modal dialog that
normally hosts them (_show_settings_dialog's own Gtk.Dialog.run would
block a test run forever). Between them they are 350 of
editor_window.py's executable lines and none were reached by any test.

What is worth pinning here is not that a box comes back - it is the
wiring. Every checkbox does two things: it reflects the setting's
current value when the tab is built, and it writes the setting back when
toggled. A checkbox wired to the wrong setting, or to a getter but no
setter, looks completely normal on screen and silently discards the
user's choice. The round-trip below is what catches that.

Settings writes land in the temp XDG_CONFIG_HOME that tests/conftest.py
installs before collection, so nothing here touches a real config.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="the tabs are real Gtk widgets - building one needs a display (CI: xvfb-run)",
)

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from orcshot import settings
from orcshot.ui.editor_window import (
    _build_capture_settings_tab,
    _build_destinations_settings_tab,
    _build_general_settings_tab,
    _build_output_settings_tab,
    _build_printer_settings_tab,
)


@pytest.fixture
def parent():
    window = Gtk.Window()
    yield window
    window.destroy()


def _checkboxes(widget, found=None):
    """Every Gtk.CheckButton in a built tab, by its label - the tabs
    nest them in frames inside boxes, so this walks rather than
    iterating one level.
    """
    found = {} if found is None else found
    if isinstance(widget, Gtk.CheckButton):
        found[widget.get_label()] = widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            _checkboxes(child, found)
    return found


# (checkbox label, settings getter, settings setter) - the wiring each
# tab claims to have. Deliberately excludes "Launch Orcshot on startup",
# which is not a setting but a real .desktop file in the autostart dir
# (enable_autostart/disable_autostart), and so is not a round-trip.
CAPTURE_TAB_WIRING = [
    ("Capture mouse cursor", "get_capture_mouse_cursor", "set_capture_mouse_cursor"),
    (
        "Show magnifier while selecting a region",
        "get_show_magnifier_while_selecting",
        "set_show_magnifier_while_selecting",
    ),
    ("Play camera sound", "get_play_capture_sound", "set_play_capture_sound"),
    ("Show notification after capture", "get_show_capture_notification", "set_show_capture_notification"),
    ("Reuse editor window for new captures", "get_reuse_editor", "set_reuse_editor"),
]

GENERAL_TAB_WIRING = [
    ("Use system default proxy", "get_use_default_proxy", "set_use_default_proxy"),
    (
        "Suppress the save dialog when closing the editor",
        "get_suppress_save_dialog_at_close",
        "set_suppress_save_dialog_at_close",
    ),
]


class TestEveryTabBuilds:
    """Each tab on its own, so a failure names the tab rather than
    "the dialog".
    """

    def test_the_capture_tab_builds(self):
        assert isinstance(_build_capture_settings_tab(), Gtk.Box)

    def test_the_general_tab_builds(self, parent):
        assert isinstance(_build_general_settings_tab(parent), Gtk.Box)

    def test_the_output_tab_builds(self, parent):
        assert isinstance(_build_output_settings_tab(parent), Gtk.Box)

    def test_the_destinations_tab_builds(self, parent):
        assert isinstance(_build_destinations_settings_tab(parent), Gtk.Box)

    def test_the_printer_tab_builds(self, parent):
        assert isinstance(_build_printer_settings_tab(), Gtk.Box)


class TestCaptureTabWiring:
    @pytest.mark.parametrize("label,getter,setter", CAPTURE_TAB_WIRING)
    @pytest.mark.parametrize("stored", [True, False])
    def test_the_checkbox_shows_the_stored_setting(self, label, getter, setter, stored):
        getattr(settings, setter)(stored)

        box = _build_capture_settings_tab()

        assert _checkboxes(box)[label].get_active() is stored

    @pytest.mark.parametrize("label,getter,setter", CAPTURE_TAB_WIRING)
    @pytest.mark.parametrize("stored", [True, False])
    def test_toggling_the_checkbox_writes_the_setting(self, label, getter, setter, stored):
        getattr(settings, setter)(stored)
        box = _build_capture_settings_tab()

        _checkboxes(box)[label].set_active(not stored)

        assert getattr(settings, getter)() is (not stored)

    def test_each_checkbox_writes_only_its_own_setting(self):
        """The failure this catches: two checkboxes wired to the same
        setter, which no single-checkbox round-trip above would notice.
        """
        for _label, _getter, setter in CAPTURE_TAB_WIRING:
            getattr(settings, setter)(False)
        box = _build_capture_settings_tab()
        boxes = _checkboxes(box)

        boxes["Play camera sound"].set_active(True)

        assert settings.get_play_capture_sound() is True
        assert settings.get_capture_mouse_cursor() is False
        assert settings.get_show_magnifier_while_selecting() is False
        assert settings.get_show_capture_notification() is False
        assert settings.get_reuse_editor() is False


class TestGeneralTabWiring:
    @pytest.mark.parametrize("label,getter,setter", GENERAL_TAB_WIRING)
    @pytest.mark.parametrize("stored", [True, False])
    def test_the_checkbox_shows_the_stored_setting(self, parent, label, getter, setter, stored):
        getattr(settings, setter)(stored)

        box = _build_general_settings_tab(parent)

        assert _checkboxes(box)[label].get_active() is stored

    @pytest.mark.parametrize("label,getter,setter", GENERAL_TAB_WIRING)
    @pytest.mark.parametrize("stored", [True, False])
    def test_toggling_the_checkbox_writes_the_setting(self, parent, label, getter, setter, stored):
        getattr(settings, setter)(stored)
        box = _build_general_settings_tab(parent)

        _checkboxes(box)[label].set_active(not stored)

        assert getattr(settings, getter)() is (not stored)
