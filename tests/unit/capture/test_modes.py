"""Pure region-resolution logic for each capture mode: given a
CaptureBackend/WindowEnumerator, what Rect should get grabbed. Kept
separate from the actual grab + launch-EditorWindow glue
(ui/capture_modes.py) so it's unit testable against the fakes without
needing GTK.
"""

from orcshot.capture.fake import FakeCaptureBackend, FakeWindowEnumerator
from orcshot.capture.modes import active_window_region, full_screen_region
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
        assert active_window_region(backend, enumerator) == Rect(100, 100, 500, 400)

    def test_returns_none_when_nothing_is_focused(self):
        backend = FakeCaptureBackend()
        enumerator = FakeWindowEnumerator(windows=[], active=None)
        assert active_window_region(backend, enumerator) is None

    def test_clamps_a_window_extending_past_the_screen(self):
        backend = FakeCaptureBackend(monitors=[Monitor("A", Rect(0, 0, 1920, 1080), is_primary=True)])
        active = window(Rect(1800, 900, 2200, 1300))  # extends past both edges
        enumerator = FakeWindowEnumerator(windows=[active], active=active)
        assert active_window_region(backend, enumerator) == Rect(1800, 900, 1920, 1080)

    def test_returns_none_for_a_window_entirely_off_screen(self):
        backend = FakeCaptureBackend(monitors=[Monitor("A", Rect(0, 0, 1920, 1080), is_primary=True)])
        active = window(Rect(5000, 5000, 5100, 5100))
        enumerator = FakeWindowEnumerator(windows=[active], active=active)
        assert active_window_region(backend, enumerator) is None
