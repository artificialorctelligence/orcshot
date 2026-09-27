"""The X11 half of headless capture (BACKLOG #225).

Backends are injectable, the same way ui/window_picker.py's
start_window_picker already takes them, so the whole flow - full screen,
window by title, refusal, clamping, writing - is exercised against the
fakes with no display at all.
"""

import numpy as np
import pytest

from orcshot.capture.backend import Monitor
from orcshot.capture.fake import FakeCaptureBackend
from orcshot.capture.headless_x11 import capture_to_file
from orcshot.capture.modes import HeadlessCaptureError
from orcshot.capture.window import WindowInfo
from orcshot.core.geometry import Rect

MONITORS = [Monitor("HDMI-1", Rect(0, 0, 1920, 1080), is_primary=True)]


def _win(window_id, title, bounds, minimized=False):
    return WindowInfo(
        window_id=window_id, title=title, class_name="app", bounds=bounds,
        is_minimized=minimized, window_type="normal", process_id=1000 + window_id,
    )


class _Enumerator:
    """A WindowEnumerator that also answers the workspace question, the
    way the real X11 one does."""

    def __init__(self, windows, elsewhere=()):
        self._windows = list(windows)
        self._elsewhere = set(elsewhere)

    def list_windows(self):
        return list(self._windows)

    def active_window(self):
        return self._windows[-1] if self._windows else None

    def is_on_current_workspace(self, window_id):
        return window_id not in self._elsewhere


@pytest.fixture
def written(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        "orcshot.capture.headless_x11.save_image_to_file",
        lambda image, path: saved.update(image=image, path=str(path)),
    )
    return saved


class TestFullScreen:
    def test_it_grabs_the_whole_virtual_screen(self, written, tmp_path):
        backend = FakeCaptureBackend(monitors=MONITORS)

        capture_to_file(str(tmp_path / "shot.png"), None, capture_backend=backend)

        assert written["image"].shape[:2] == (1080, 1920)

    def test_it_writes_to_the_path_the_caller_named(self, written, tmp_path):
        target = tmp_path / "somewhere" / "shot.png"

        capture_to_file(str(target), None, capture_backend=FakeCaptureBackend(monitors=MONITORS))

        assert written["path"] == str(target)

    def test_no_window_is_enumerated_for_a_full_screen_capture(self, written, tmp_path):
        """Enumeration can raise on a WM with no EWMH support, so a
        full-screen capture must not reach for it at all.
        """
        def explode():
            raise AssertionError("list_windows must not be called for a full-screen capture")

        class _Exploding:
            list_windows = staticmethod(explode)

        capture_to_file(
            str(tmp_path / "a.png"), None,
            capture_backend=FakeCaptureBackend(monitors=MONITORS), window_enumerator=_Exploding(),
        )


class TestByWindowTitle:
    def test_it_grabs_the_window_s_own_rectangle(self, written, tmp_path):
        target = _win(1, "Mozilla Firefox", Rect(100, 50, 900, 650))

        capture_to_file(
            str(tmp_path / "a.png"), "Firefox",
            capture_backend=FakeCaptureBackend(monitors=MONITORS), window_enumerator=_Enumerator([target]),
        )

        assert written["image"].shape[:2] == (600, 800)

    def test_a_window_hanging_off_screen_is_clamped_not_rejected(self, written, tmp_path):
        """A window dragged partly off the edge still has real pixels on
        screen; grabbing past virtual_bounds would raise.
        """
        half_off = _win(1, "Mozilla Firefox", Rect(1620, 0, 2420, 600))

        capture_to_file(
            str(tmp_path / "a.png"), "Firefox",
            capture_backend=FakeCaptureBackend(monitors=MONITORS), window_enumerator=_Enumerator([half_off]),
        )

        assert written["image"].shape[:2] == (600, 300)

    def test_a_refusal_reaches_the_caller(self, tmp_path):
        hidden = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600), minimized=True)

        with pytest.raises(HeadlessCaptureError, match="minimi"):
            capture_to_file(
                str(tmp_path / "a.png"), "Firefox",
                capture_backend=FakeCaptureBackend(monitors=MONITORS), window_enumerator=_Enumerator([hidden]),
            )

    def test_nothing_is_written_when_the_window_is_refused(self, written, tmp_path):
        hidden = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600), minimized=True)

        with pytest.raises(HeadlessCaptureError):
            capture_to_file(
                str(tmp_path / "a.png"), "Firefox",
                capture_backend=FakeCaptureBackend(monitors=MONITORS), window_enumerator=_Enumerator([hidden]),
            )

        assert written == {}

    def test_the_workspace_answer_comes_from_the_enumerator(self, tmp_path):
        elsewhere = _win(1, "Mozilla Firefox", Rect(0, 0, 800, 600))

        with pytest.raises(HeadlessCaptureError, match="workspace"):
            capture_to_file(
                str(tmp_path / "a.png"), "Firefox",
                capture_backend=FakeCaptureBackend(monitors=MONITORS),
                window_enumerator=_Enumerator([elsewhere], elsewhere=[1]),
            )
