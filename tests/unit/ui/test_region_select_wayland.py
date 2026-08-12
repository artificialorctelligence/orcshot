"""Pure coverage for the multi-monitor coordinate translation math -
the parts that involve real GTK windows, a live event loop, or Cairo
drawing are only verified live, same split as region_select.py and
window_picker.py.
"""

from orcshot.core.geometry import Rect
from orcshot.ui.region_select_wayland import _rect_in_monitor_local


class TestRectInMonitorLocal:
    def test_fully_inside_a_monitor_at_the_origin(self):
        rect = Rect(10, 20, 110, 90)
        monitor = Rect(0, 0, 1920, 1080)

        result = _rect_in_monitor_local(rect, monitor)

        assert result == Rect(10, 20, 110, 90)

    def test_monitor_not_at_the_origin_offsets_correctly(self):
        # A second monitor to the right of a 1920-wide primary.
        rect = Rect(1930, 10, 2030, 110)
        monitor = Rect(1920, 0, 3840, 1080)

        result = _rect_in_monitor_local(rect, monitor)

        assert result == Rect(10, 10, 110, 110)

    def test_monitor_with_negative_origin(self):
        # A monitor to the left of the primary.
        rect = Rect(-1920, 100, -1820, 200)
        monitor = Rect(-1920, 0, 0, 1080)

        result = _rect_in_monitor_local(rect, monitor)

        assert result == Rect(0, 100, 100, 200)

    def test_rect_entirely_outside_the_monitor_returns_none(self):
        rect = Rect(2000, 0, 2100, 100)
        monitor = Rect(0, 0, 1920, 1080)

        assert _rect_in_monitor_local(rect, monitor) is None

    def test_rect_spanning_two_monitors_is_clipped_to_each(self):
        left_monitor = Rect(0, 0, 1920, 1080)
        right_monitor = Rect(1920, 0, 3840, 1080)
        # A selection dragged across the boundary between them.
        rect = Rect(1870, 100, 1970, 200)

        left_result = _rect_in_monitor_local(rect, left_monitor)
        right_result = _rect_in_monitor_local(rect, right_monitor)

        assert left_result == Rect(1870, 100, 1920, 200)
        assert right_result == Rect(0, 100, 50, 200)

    def test_rect_touching_but_not_overlapping_returns_none(self):
        # Rect.intersect treats a zero-width/height overlap as no
        # intersection at all - matches the existing Rect contract.
        rect = Rect(1920, 0, 2020, 100)
        monitor = Rect(0, 0, 1920, 1080)

        assert _rect_in_monitor_local(rect, monitor) is None
