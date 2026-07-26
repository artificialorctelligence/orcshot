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


# --- Property-based tests -------------------------------------------------
# The example-based tests above cover 5 hand-picked layouts. These check
# the same invariants across arbitrary random layouts (including ones
# where monitors overlap, which ScreenLayout doesn't forbid), which the
# 5 fixed examples can't exercise.

from hypothesis import given
from hypothesis import strategies as st

_coord = st.integers(min_value=-5_000, max_value=5_000)
_dim = st.integers(min_value=1, max_value=4_000)


@st.composite
def _monitor_lists(draw, min_size=1, max_size=5):
    count = draw(st.integers(min_size, max_size))
    monitors = []
    for i in range(count):
        left, top = draw(_coord), draw(_coord)
        width, height = draw(_dim), draw(_dim)
        monitors.append(Monitor(f"mon{i}", Rect(left, top, left + width, top + height)))
    return monitors


@given(_monitor_lists())
def test_virtual_bounds_always_contains_every_monitor(monitors):
    layout = ScreenLayout(monitors)
    for monitor in monitors:
        assert layout.virtual_bounds.intersect(monitor.bounds) == monitor.bounds


@given(_monitor_lists())
def test_primary_is_always_one_of_the_monitors(monitors):
    layout = ScreenLayout(monitors)
    assert layout.primary in monitors


@given(_monitor_lists())
def test_monitor_at_a_monitors_own_top_left_corner_finds_a_monitor_containing_it(monitors):
    layout = ScreenLayout(monitors)
    for monitor in monitors:
        # top-left is always inside its own bounds (contains is
        # right/bottom-exclusive, so this holds regardless of overlap).
        found = layout.monitor_at(monitor.bounds.left, monitor.bounds.top)
        assert found is not None
        assert found.bounds.contains(monitor.bounds.left, monitor.bounds.top)


@given(_monitor_lists())
def test_clamping_the_virtual_bounds_to_itself_is_a_no_op(monitors):
    layout = ScreenLayout(monitors)
    assert layout.clamp(layout.virtual_bounds) == layout.virtual_bounds


@given(_monitor_lists())
def test_clamp_never_returns_something_outside_virtual_bounds(monitors):
    layout = ScreenLayout(monitors)
    # A rect straddling the virtual bounds' edge should clamp to
    # something entirely contained within it.
    vb = layout.virtual_bounds
    straddling = Rect(vb.right - 1, vb.top, vb.right + 100, vb.bottom)
    result = layout.clamp(straddling)
    if result is not None:
        assert vb.intersect(result) == result
