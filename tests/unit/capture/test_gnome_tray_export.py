"""Pure coverage for the tray Gio.Menu structure - the actual D-Bus
export needs a real running Gio.Application with a live D-Bus
connection, only verified live (see Task 7). Matches this project's
own established split between headless-testable pure logic and
live-verified D-Bus behavior (test_gnome_clipboard.py's own docstring
states the same reasoning).

The top-level menu is 4 sections (capture modes / open file /
preferences / quit), not a flat 8-item menu - extension.js renders a
Gtk.SeparatorMenuItem between each section, matching X11's own
_build_tray_menu (three Gtk.SeparatorMenuItems, four visual groups).
See final-review-fix-brief.md Item 1."""
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


def _section(menu: Gio.Menu, index: int) -> Gio.MenuModel:
    section = menu.get_item_link(index, Gio.MENU_LINK_SECTION)
    assert section is not None, f"item {index} has no section link"
    return section


class TestBuildTrayMenu:
    def test_returns_a_real_gio_menu(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        assert isinstance(menu, Gio.Menu)

    def test_top_level_menu_has_exactly_4_sections(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        assert menu.get_n_items() == 4
        for i in range(4):
            _section(menu, i)  # asserts non-None

    def test_section_0_has_the_5_capture_modes_in_order_with_icons(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        section = _section(menu, 0)
        assert section.get_n_items() == 5
        label = section.get_item_attribute_value(0, "label", None).get_string()
        action = section.get_item_attribute_value(0, "action", None).get_string()
        assert label == "Capture Region"
        assert action == "app.tray-region"
        for i in range(5):
            icon_value = section.get_item_attribute_value(i, "icon", None)
            assert icon_value is not None, f"capture-mode item {i} has no icon"

    def test_section_1_is_open_file_alone_with_an_icon(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        section = _section(menu, 1)
        assert section.get_n_items() == 1
        label = section.get_item_attribute_value(0, "label", None).get_string()
        action = section.get_item_attribute_value(0, "action", None).get_string()
        icon_value = section.get_item_attribute_value(0, "icon", None)
        assert label == "Open File"
        assert action == "app.tray-open-file"
        assert icon_value is not None

    def test_section_2_is_preferences_alone_with_an_icon(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        section = _section(menu, 2)
        assert section.get_n_items() == 1
        label = section.get_item_attribute_value(0, "label", None).get_string()
        action = section.get_item_attribute_value(0, "action", None).get_string()
        icon_value = section.get_item_attribute_value(0, "icon", None)
        assert label == "Preferences"
        assert action == "app.tray-preferences"
        assert icon_value is not None

    def test_section_3_is_quit_alone_with_an_icon(self):
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        section = _section(menu, 3)
        assert section.get_n_items() == 1
        label = section.get_item_attribute_value(0, "label", None).get_string()
        action = section.get_item_attribute_value(0, "action", None).get_string()
        icon_value = section.get_item_attribute_value(0, "icon", None)
        assert label == "Quit"
        assert action == "app.tray-quit"
        assert icon_value is not None

    def test_total_item_count_across_all_sections_is_still_8(self):
        # Cheap regression guard: nothing dropped when this restructured
        # from a flat 8-item menu into 4 sections.
        menu = build_tray_menu(_LABELS, (60, 60, 60, 255))
        total = sum(_section(menu, i).get_n_items() for i in range(menu.get_n_items()))
        assert total == 8
