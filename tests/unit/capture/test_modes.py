"""Pure region-resolution logic for each capture mode: given a
CaptureBackend/WindowEnumerator, what Rect should get grabbed. Kept
separate from the actual grab + launch-EditorWindow glue
(ui/capture_modes.py) so it's unit testable against the fakes without
needing GTK.
"""

from orcshot.capture.fake import FakeCaptureBackend, FakeWindowEnumerator
from orcshot.capture.modes import active_window_info, full_screen_region
from orcshot.capture.backend import Monitor
from orcshot.capture.window import WindowInfo
from orcshot.core.geometry import Rect


def window(bounds, title="Some Window", minimized=False):
    return WindowInfo(
        window_id=1, title=title, class_name="app", bounds=bounds,
        is_minimized=minimized, window_type="normal", process_id=123,
    )


class TestFullScreenRegion:
    def test_is_the_virtual_bounds(self):
        monitors = [Monitor("A", Rect(0, 0, 1920, 1080), is_primary=True), Monitor("B", Rect(1920, 0, 4480, 1440))]
        backend = FakeCaptureBackend(monitors=monitors)
        assert full_screen_region(backend) == Rect(0, 0, 4480, 1440)

    def test_matches_a_single_monitor_layout(self):
        backend = FakeCaptureBackend(monitors=[Monitor("A", Rect(0, 0, 800, 600), is_primary=True)])
        assert full_screen_region(backend) == Rect(0, 0, 800, 600)


class TestActiveWindowRegion:
    def test_returns_the_focused_windows_bounds(self):
        backend = FakeCaptureBackend()
        active = window(Rect(100, 100, 500, 400))
        enumerator = FakeWindowEnumerator(windows=[active], active=active)
        assert active_window_info(backend, enumerator).bounds == Rect(100, 100, 500, 400)

    def test_returns_the_focused_windows_title(self):
        backend = FakeCaptureBackend()
        active = window(Rect(100, 100, 500, 400), title="Notes - GNOME Text Editor")
        enumerator = FakeWindowEnumerator(windows=[active], active=active)
        assert active_window_info(backend, enumerator).title == "Notes - GNOME Text Editor"

    def test_returns_none_when_nothing_is_focused(self):
        backend = FakeCaptureBackend()
        enumerator = FakeWindowEnumerator(windows=[], active=None)
        assert active_window_info(backend, enumerator) is None

    def test_clamps_a_window_extending_past_the_screen(self):
        backend = FakeCaptureBackend(monitors=[Monitor("A", Rect(0, 0, 1920, 1080), is_primary=True)])
        active = window(Rect(1800, 900, 2200, 1300))  # extends past both edges
        enumerator = FakeWindowEnumerator(windows=[active], active=active)
        assert active_window_info(backend, enumerator).bounds == Rect(1800, 900, 1920, 1080)

    def test_returns_none_for_a_window_entirely_off_screen(self):
        backend = FakeCaptureBackend(monitors=[Monitor("A", Rect(0, 0, 1920, 1080), is_primary=True)])
        active = window(Rect(5000, 5000, 5100, 5100))
        enumerator = FakeWindowEnumerator(windows=[active], active=active)
        assert active_window_info(backend, enumerator) is None


# --------------------------------------------------------------------
# Headless window resolution (BACKLOG #225)
#
# The safety property of `orcshot --capture-to PATH --window TITLE`.
# Neither X11 nor GNOME reads a window's own buffer - both grab the
# screen and crop to a rect - so a window that is minimised, on another
# workspace, or covered by something else does not yield its own pixels.
# It yields whatever is actually there, confidently and wrongly. For a
# tool whose whole purpose is letting Claude look at the screen instead
# of asking a person, that is worse than refusing, so this refuses.
#
# Pure: a list of WindowInfo and a predicate. No display, no bus, no GTK.
# --------------------------------------------------------------------

import pytest  # noqa: E402

from orcshot.capture.modes import (  # noqa: E402
    HeadlessCaptureError,
    resolve_window_for_headless_capture,
)


def _win(window_id, title, bounds, minimized=False):
    return WindowInfo(
        window_id=window_id, title=title, class_name="app", bounds=bounds,
        is_minimized=minimized, window_type="normal", process_id=1000 + window_id,
    )


# Bottom-to-top, the order WindowEnumerator.list_windows() promises.
EVERYWHERE = lambda _window: True  # noqa: E731 - every window is on the current workspace


class TestFindingTheWindow:
    def test_a_matching_window_is_returned(self):
        editor = _win(1, "notes.txt — Text Editor", Rect(0, 0, 800, 600))

        assert resolve_window_for_headless_capture([editor], EVERYWHERE, "Text Editor") is editor

    def test_the_match_is_a_case_insensitive_substring(self):
        firefox = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))

        assert resolve_window_for_headless_capture([firefox], EVERYWHERE, "firefox") is firefox

    def test_no_match_is_refused_by_name(self):
        with pytest.raises(HeadlessCaptureError, match="Inkscape"):
            resolve_window_for_headless_capture([_win(1, "Mozilla Firefox", Rect(0, 0, 8, 6))], EVERYWHERE, "Inkscape")

    def test_an_empty_desktop_is_refused(self):
        with pytest.raises(HeadlessCaptureError):
            resolve_window_for_headless_capture([], EVERYWHERE, "anything")

    def test_several_matches_resolve_to_the_topmost(self):
        """list_windows() is bottom-to-top, so the last match is the one
        actually on top - the same "last match wins" rule the window
        picker's hover already uses.
        """
        lower = _win(1, "Mozilla Firefox — Inbox", Rect(0, 0, 400, 300))
        upper = _win(2, "Mozilla Firefox — Calendar", Rect(900, 900, 1400, 1300))

        assert resolve_window_for_headless_capture([lower, upper], EVERYWHERE, "Firefox") is upper


class TestRefusingWhatCannotBeCapturedCorrectly:
    def test_a_minimised_window_is_refused(self):
        hidden = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600), minimized=True)

        with pytest.raises(HeadlessCaptureError, match="minimi"):
            resolve_window_for_headless_capture([hidden], EVERYWHERE, "Firefox")

    def test_a_window_on_another_workspace_is_refused(self):
        elsewhere = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))

        with pytest.raises(HeadlessCaptureError, match="workspace"):
            resolve_window_for_headless_capture([elsewhere], lambda _w: False, "Firefox")

    def test_a_window_covered_by_one_above_it_is_refused(self):
        target = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))
        on_top = _win(2, "Text Editor", Rect(400, 300, 1200, 900))

        with pytest.raises(HeadlessCaptureError, match="cover|occlu"):
            resolve_window_for_headless_capture([target, on_top], EVERYWHERE, "Firefox")

    def test_a_window_below_the_target_does_not_occlude_it(self):
        """Stacking order is the whole point: only what is *above* the
        target can be covering it.
        """
        underneath = _win(1, "Text Editor", Rect(400, 300, 1200, 900))
        target = _win(2, "Mozilla Firefox", Rect(0, 0, 800, 600))

        assert resolve_window_for_headless_capture([underneath, target], EVERYWHERE, "Firefox") is target

    def test_a_window_above_that_does_not_overlap_does_not_occlude(self):
        target = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))
        beside_it = _win(2, "Text Editor", Rect(900, 0, 1600, 600))

        assert resolve_window_for_headless_capture([target, beside_it], EVERYWHERE, "Firefox") is target

    def test_a_minimised_window_above_is_not_an_occluder(self):
        """It is in the list and above in stacking order, but it is not
        on screen, so it covers nothing.
        """
        target = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))
        iconified = _win(2, "Text Editor", Rect(400, 300, 1200, 900), minimized=True)

        assert resolve_window_for_headless_capture([target, iconified], EVERYWHERE, "Firefox") is target

    def test_a_window_above_on_another_workspace_is_not_an_occluder(self):
        target = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))
        elsewhere = _win(2, "Text Editor", Rect(400, 300, 1200, 900))
        on_this_workspace = lambda w: w.window_id != elsewhere.window_id  # noqa: E731

        assert resolve_window_for_headless_capture([target, elsewhere], on_this_workspace, "Firefox") is target

    def test_touching_edges_do_not_count_as_covering(self):
        """Rect.intersect returns None for a zero-area overlap, so a
        window flush against the target's edge is beside it, not over it.
        """
        target = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))
        flush = _win(2, "Text Editor", Rect(800, 0, 1600, 600))

        assert resolve_window_for_headless_capture([target, flush], EVERYWHERE, "Firefox") is target

    def test_the_refusal_names_the_window_so_a_script_can_report_it(self):
        with pytest.raises(HeadlessCaptureError, match="Firefox"):
            resolve_window_for_headless_capture(
                [_win(1, "Mozilla Firefox", Rect(0, 0, 8, 6), minimized=True)], EVERYWHERE, "Firefox"
            )
