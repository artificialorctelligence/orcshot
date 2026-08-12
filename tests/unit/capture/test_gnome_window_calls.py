"""Pure coverage for gnome_window_calls.py's JSON-parsing logic - the
D-Bus call itself needs a real GNOME/Wayland session with the
window-calls extension enabled, only verified live (see
REQUIREMENTS.md's Wayland window-picker section).
"""

from orcshot.capture.gnome_window_calls import parse_window_info
from orcshot.capture.window import WindowInfo
from orcshot.core.geometry import Rect


def _raw(**overrides):
    base = {
        "id": 12345,
        "title": "Text Editor",
        "wm_class": "org.gnome.TextEditor",
        "x": 67, "y": 43, "width": 700, "height": 520,
        "minimized": False,
        "window_type": 0,
        "pid": 999,
    }
    base.update(overrides)
    return base


class TestParseWindowInfo:
    def test_maps_basic_fields(self):
        info = parse_window_info(_raw())
        assert info == WindowInfo(
            window_id=12345,
            title="Text Editor",
            class_name="org.gnome.TextEditor",
            bounds=Rect(67, 43, 767, 563),
            is_minimized=False,
            window_type="normal",
            process_id=999,
        )

    def test_window_type_zero_is_normal(self):
        assert parse_window_info(_raw(window_type=0)).window_type == "normal"

    def test_window_type_dock_is_excluded_category(self):
        # index 2 in Meta.WindowType's ordering
        assert parse_window_info(_raw(window_type=2)).window_type == "dock"

    def test_unknown_window_type_value_falls_back_safely(self):
        assert parse_window_info(_raw(window_type=999)).window_type == "unknown"

    def test_missing_window_type_falls_back_safely(self):
        raw = _raw()
        del raw["window_type"]
        assert parse_window_info(raw).window_type == "unknown"

    def test_minimized_flag_is_carried_through(self):
        assert parse_window_info(_raw(minimized=True)).is_minimized is True

    def test_missing_title_becomes_empty_string_not_none(self):
        raw = _raw()
        raw["title"] = None
        assert parse_window_info(raw).title == ""

    def test_bounds_derived_from_position_and_size(self):
        info = parse_window_info(_raw(x=10, y=20, width=100, height=50))
        assert info.bounds == Rect(10, 20, 110, 70)
