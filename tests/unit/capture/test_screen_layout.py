"""Multi-monitor layout logic, tested against synthetic configurations.

Deliberately covers layouts beyond whatever hardware the developer has:
single screen, side-by-side with mismatched heights, vertical stacks,
right-to-left arrangements and layouts with uncovered gaps.
"""

import pytest

from greenshot_linux.capture.backend import Monitor, ScreenLayout
from greenshot_linux.core.geometry import Rect


def monitor(name, left, top, width, height, primary=False):
    return Monitor(
        name=name,
        bounds=Rect(left, top, left + width, top + height),
        is_primary=primary,
    )


SINGLE = [monitor("eDP-1", 0, 0, 1920, 1080, primary=True)]

# Mismatched heights leave dead space below the shorter screen.
SIDE_BY_SIDE_MIXED = [
    monitor("HDMI-0", 0, 0, 1920, 1080),
    monitor("DP-2", 1920, 0, 2560, 1440, primary=True),
]

STACKED = [
    monitor("DP-1", 0, 0, 2560, 1440, primary=True),
    monitor("DP-2", 0, 1440, 2560, 1440),
]

# Primary on the right, secondary to its left: the layout must not assume
# the primary sits at the origin.
PRIMARY_ON_RIGHT = [
    monitor("DP-1", 0, 0, 1280, 1024),
    monitor("DP-2", 1280, 0, 1920, 1080, primary=True),
]

TRIPLE = [
    monitor("DP-1", 0, 0, 1920, 1080),
    monitor("DP-2", 1920, 0, 1920, 1080, primary=True),
    monitor("DP-3", 3840, 0, 1920, 1080),
]

ALL_LAYOUTS = [SINGLE, SIDE_BY_SIDE_MIXED, STACKED, PRIMARY_ON_RIGHT, TRIPLE]


class TestVirtualBounds:
    def test_single_monitor_bounds_are_its_own(self):
        assert ScreenLayout(SINGLE).virtual_bounds == Rect(0, 0, 1920, 1080)

    def test_side_by_side_spans_full_width_and_tallest_height(self):
        assert ScreenLayout(SIDE_BY_SIDE_MIXED).virtual_bounds == Rect(0, 0, 4480, 1440)

    def test_stacked_spans_full_height(self):
        assert ScreenLayout(STACKED).virtual_bounds == Rect(0, 0, 2560, 2880)

    def test_triple_wide_spans_all_three(self):
        assert ScreenLayout(TRIPLE).virtual_bounds == Rect(0, 0, 5760, 1080)

    @pytest.mark.parametrize("monitors", ALL_LAYOUTS)
    def test_every_monitor_is_inside_the_virtual_bounds(self, monitors):
        bounds = ScreenLayout(monitors).virtual_bounds
        for mon in monitors:
            assert bounds.intersect(mon.bounds) == mon.bounds

    def test_empty_layout_is_rejected(self):
        with pytest.raises(ValueError):
            ScreenLayout([])


class TestPrimary:
    @pytest.mark.parametrize("monitors", ALL_LAYOUTS)
    def test_primary_is_the_flagged_monitor(self, monitors):
        expected = next(m for m in monitors if m.is_primary)
        assert ScreenLayout(monitors).primary == expected

    def test_falls_back_to_first_monitor_when_none_is_flagged(self):
        monitors = [monitor("DP-1", 0, 0, 800, 600), monitor("DP-2", 800, 0, 800, 600)]
        assert ScreenLayout(monitors).primary == monitors[0]


class TestMonitorAt:
    def test_finds_the_monitor_containing_a_point(self):
        layout = ScreenLayout(SIDE_BY_SIDE_MIXED)

        assert layout.monitor_at(100, 100).name == "HDMI-0"
        assert layout.monitor_at(2000, 100).name == "DP-2"

    def test_boundary_pixel_belongs_to_the_right_hand_monitor(self):
        layout = ScreenLayout(SIDE_BY_SIDE_MIXED)

        assert layout.monitor_at(1919, 0).name == "HDMI-0"
        assert layout.monitor_at(1920, 0).name == "DP-2"

    def test_point_in_dead_space_has_no_monitor(self):
        # Below the shorter 1080-tall screen but inside the virtual bounds.
        layout = ScreenLayout(SIDE_BY_SIDE_MIXED)

        assert layout.virtual_bounds.contains(500, 1200)
        assert layout.monitor_at(500, 1200) is None

    def test_point_outside_the_virtual_bounds_has_no_monitor(self):
        assert ScreenLayout(SINGLE).monitor_at(9999, 9999) is None


class TestClamp:
    def test_rect_fully_inside_is_unchanged(self):
        layout = ScreenLayout(SIDE_BY_SIDE_MIXED)
        rect = Rect(100, 100, 200, 200)

        assert layout.clamp(rect) == rect

    def test_rect_overhanging_an_edge_is_trimmed(self):
        layout = ScreenLayout(SINGLE)

        assert layout.clamp(Rect(1800, 1000, 2200, 1300)) == Rect(1800, 1000, 1920, 1080)

    def test_rect_entirely_outside_clamps_to_none(self):
        # Matters for replaying a stored "last region" after the monitor
        # layout has changed.
        assert ScreenLayout(SINGLE).clamp(Rect(5000, 5000, 5100, 5100)) is None
