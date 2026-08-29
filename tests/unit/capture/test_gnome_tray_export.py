"""Pure coverage for the tray Gio.Menu structure - the actual D-Bus
export needs a real running Gio.Application with a live D-Bus
connection, only verified live (see Task 7). Matches this project's
own established split between headless-testable pure logic and
live-verified D-Bus behavior (test_gnome_clipboard.py's own docstring
states the same reasoning)."""
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from orcshot.capture.gnome_tray_export import build_tray_menu

_LABELS = {
    "region": "Capture Region",
    "full_screen": "Capture Full Screen",
    "active_window": "Capture Active Window",
    "window_picker": "Capture Window...",
    "repeat_region": "Repeat Last Region",
    "open_file": "Open File",
    "preferences": "Preferences",
    "quit": "Quit",
}


class TestBuildTrayMenu:
    def test_returns_a_real_gio_menu(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        assert isinstance(menu, Gio.Menu)

    def test_has_one_item_per_capture_mode_plus_the_fixed_items(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        # 5 capture modes + open-file + preferences + quit = 8
        assert menu.get_n_items() == 8

    def test_first_item_matches_the_first_label_and_correct_action(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        label = menu.get_item_attribute_value(0, "label", None).get_string()
        action = menu.get_item_attribute_value(0, "action", None).get_string()
        assert label == "Capture Region"
        assert action == "app.tray-region"

    def test_every_capture_mode_item_has_an_icon_attribute(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        for i in range(5):
            icon_value = menu.get_item_attribute_value(i, "icon", None)
            assert icon_value is not None, f"item {i} has no icon"

    def test_open_file_preferences_and_quit_also_have_an_icon_attribute(self):
        # Task 7 live-verification finding: the X11 `_build_tray_menu`
        # gives all 8 items an icon (5 hand-drawn capture-mode icons +
        # 3 stock_icon_image lookalikes for Open File/Preferences/
        # Quit) - task #146's "every icon in the wayland version must
        # look like the x11 version, no exceptions" means these three
        # need one too, not just the 5 capture modes.
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        for i in range(5, 8):
            icon_value = menu.get_item_attribute_value(i, "icon", None)
            assert icon_value is not None, f"item {i} has no icon"

    def test_quit_is_the_last_item_with_the_right_action(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        n = menu.get_n_items()
        action = menu.get_item_attribute_value(n - 1, "action", None).get_string()
        assert action == "app.tray-quit"
