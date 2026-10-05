"""The GNOME Wayland half of headless capture (BACKLOG #225).

The Shell extension is the only route here, not the preferred one: this
project's own SpikePortalGnome proved xdg-desktop-portal answers "Only
the focused app is allowed to show a system access dialog" to any process
without a focused window, which a headless CLI never has.

The session and bridge are injected, so the flow - capability gate, window
resolution, the request, and how the bytes reach disk - is exercised with
no bus and no GNOME Shell. What these cannot prove is in #225: a headless
GNOME Shell in CI has no real compositor, so nothing here says the real
stage screenshot behaves the same from a connection with no visible UI.
"""

import json

import pytest

from orcshot.capture.backend import Monitor, ScreenLayout
from orcshot.capture.gnome_headless import CAPABILITY, capture_png_to
from orcshot.core.geometry import Rect
from orcshot.capture.modes import HeadlessCaptureError

# A real 2x2 RGBA PNG with four distinct pixels, so the decode path gets
# something it can actually read and a wrong decode would be visible by
# value rather than only by shape.
PNG_2X2 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000200000002080600000072b60d24"
    "0000001449444154789c63f8cfc0f01f0c81341030340000474b087913f160d000"
    "00000049454e44ae426082"
)


# Two monitors side by side, so virtual_bounds is wider than either and
# a single-monitor answer would be visibly wrong.
SCREEN = ScreenLayout([
    Monitor("HDMI-1", Rect(0, 0, 1920, 1080), is_primary=True),
    Monitor("DP-1", Rect(1920, 0, 2560, 720)),
])


def _raw_window(window_id, title, x, y, width, height, minimized=False, in_current_workspace=True):
    return {
        "id": window_id, "title": title, "wm_class": "app", "pid": 1000 + window_id,
        "x": x, "y": y, "width": width, "height": height,
        "minimized": minimized, "in_current_workspace": in_current_workspace,
        "window_type": 0, "focus": False,
    }


class FakeBridge:
    def __init__(self, capabilities=(CAPABILITY, "list-windows"), windows=()):
        self._capabilities = frozenset(capabilities)
        self._windows = list(windows)
        self.requests = []

    def has(self, kind):
        return kind in self._capabilities

    def request(self, kind, params=None, timeout_ms=None):
        self.requests.append((kind, params))
        if kind == "list-windows":
            return {"windows": json.dumps(self._windows)}
        if kind == CAPABILITY:
            return {"ok": True, "pngBytes": PNG_2X2}
        raise AssertionError(f"unexpected request {kind}")


class FakeSession:
    def __init__(self, bridge):
        self.bridge = bridge
        self.closed = False

    def open(self, timeout_ms=None):
        return self.bridge

    def close(self):
        self.closed = True


class TestTheCapabilityGate:
    def test_an_extension_without_the_capability_is_refused(self, tmp_path):
        """Decision #3 fails closed: until extensions.gnome.org accepts a
        version carrying the handler, this reports unavailable rather
        than assuming it works.
        """
        session = FakeSession(FakeBridge(capabilities=("list-windows",)))

        with pytest.raises(HeadlessCaptureError, match="extension"):
            capture_png_to(str(tmp_path / "a.png"), None, session=session, screen_layout=SCREEN)

    def test_the_session_is_closed_even_when_refused(self, tmp_path):
        session = FakeSession(FakeBridge(capabilities=()))

        with pytest.raises(HeadlessCaptureError):
            capture_png_to(str(tmp_path / "a.png"), None, session=session, screen_layout=SCREEN)

        assert session.closed is True


class TestWritingTheBytes:
    def test_a_png_destination_gets_the_shell_s_bytes_verbatim(self, tmp_path):
        """No decode and re-encode: the Shell already produced a PNG and
        nothing here consumes the pixels in between.
        """
        target = tmp_path / "shot.png"
        session = FakeSession(FakeBridge())

        capture_png_to(str(target), None, session=session, screen_layout=SCREEN)

        assert target.read_bytes() == PNG_2X2

    def test_an_uppercase_extension_is_still_a_png(self, tmp_path):
        target = tmp_path / "shot.PNG"

        capture_png_to(str(target), None, session=FakeSession(FakeBridge()), screen_layout=SCREEN)

        assert target.read_bytes() == PNG_2X2

    def test_another_format_is_decoded_and_re_encoded(self, tmp_path, monkeypatch):
        converted = {}
        monkeypatch.setattr(
            "orcshot.capture.gnome_headless.save_image_to_file",
            lambda image, path: converted.update(shape=image.shape, path=str(path)),
        )
        target = tmp_path / "shot.jpg"

        capture_png_to(str(target), None, session=FakeSession(FakeBridge()), screen_layout=SCREEN)

        assert converted["path"] == str(target)
        assert converted["shape"][:2] == (2, 2)

    def test_the_session_is_closed_after_a_successful_capture(self, tmp_path):
        session = FakeSession(FakeBridge())

        capture_png_to(str(tmp_path / "a.png"), None, session=session, screen_layout=SCREEN)

        assert session.closed is True


class TestFullScreen:
    def test_no_windows_are_listed_for_a_full_screen_capture(self, tmp_path):
        bridge = FakeBridge()

        capture_png_to(str(tmp_path / "a.png"), None, session=FakeSession(bridge), screen_layout=SCREEN)

        assert [kind for kind, _params in bridge.requests] == [CAPABILITY]

    def test_a_real_rectangle_is_sent_not_an_empty_one(self, tmp_path):
        """The handler destructures {x, y, width, height} and has no
        fallback, so sending {} would hand composite_to_stream four
        undefineds and fail inside the Shell - on the commonest path
        there is. Found in review, 2026-09-27.
        """
        bridge = FakeBridge()

        capture_png_to(str(tmp_path / "a.png"), None, session=FakeSession(bridge), screen_layout=SCREEN)

        _kind, params = bridge.requests[-1]
        assert set(params) == {"x", "y", "width", "height"}
        assert params["width"] > 0 and params["height"] > 0

    def test_the_rectangle_is_the_whole_virtual_screen(self, tmp_path):
        """Multi-monitor included: virtual_bounds spans every output, so
        a full-screen capture is the whole desktop, not one monitor.
        """
        bridge = FakeBridge()

        capture_png_to(str(tmp_path / "a.png"), None, session=FakeSession(bridge), screen_layout=SCREEN)

        _kind, params = bridge.requests[-1]
        assert params == {"x": 0, "y": 0, "width": 2560, "height": 1080}


class TestByWindowTitle:
    def test_the_window_s_own_rect_is_requested(self, tmp_path):
        bridge = FakeBridge(windows=[_raw_window(1, "Mozilla Firefox", 100, 50, 800, 600)])

        capture_png_to(str(tmp_path / "a.png"), "Firefox", session=FakeSession(bridge))

        kind, params = bridge.requests[-1]
        assert kind == CAPABILITY
        assert params == {"x": 100, "y": 50, "width": 800, "height": 600}

    def test_a_minimised_window_is_refused_before_any_capture(self, tmp_path):
        bridge = FakeBridge(windows=[_raw_window(1, "Mozilla Firefox", 0, 0, 800, 600, minimized=True)])

        with pytest.raises(HeadlessCaptureError, match="minimi"):
            capture_png_to(str(tmp_path / "a.png"), "Firefox", session=FakeSession(bridge))

        assert CAPABILITY not in [kind for kind, _ in bridge.requests]

    def test_workspace_comes_from_the_shell_s_own_field(self, tmp_path):
        """GNOME answers this directly - list-windows already carries
        in_current_workspace, so nothing has to be derived.
        """
        bridge = FakeBridge(
            windows=[_raw_window(1, "Mozilla Firefox", 0, 0, 800, 600, in_current_workspace=False)]
        )

        with pytest.raises(HeadlessCaptureError, match="workspace"):
            capture_png_to(str(tmp_path / "a.png"), "Firefox", session=FakeSession(bridge))

    def test_a_covered_window_is_refused(self, tmp_path):
        bridge = FakeBridge(windows=[
            _raw_window(1, "Mozilla Firefox", 0, 0, 800, 600),
            _raw_window(2, "Text Editor", 400, 300, 800, 600),
        ])

        with pytest.raises(HeadlessCaptureError, match="cover"):
            capture_png_to(str(tmp_path / "a.png"), "Firefox", session=FakeSession(bridge))

    def test_nothing_is_written_when_the_window_is_refused(self, tmp_path):
        target = tmp_path / "a.png"
        bridge = FakeBridge(windows=[_raw_window(1, "Mozilla Firefox", 0, 0, 800, 600, minimized=True)])

        with pytest.raises(HeadlessCaptureError):
            capture_png_to(str(target), "Firefox", session=FakeSession(bridge))

        assert not target.exists()
