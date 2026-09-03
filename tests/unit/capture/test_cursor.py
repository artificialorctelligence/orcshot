"""default_cursor_backend() - the shared, defensive factory every
capture-mode caller uses instead of constructing X11CursorBackend
directly. See its own docstring in capture/cursor.py for why this
needs to exist: X11CursorBackend()'s constructor connects to an X11
display eagerly, and on a session with no reachable X11/XWayland
display that's a real, live-observed crash (Xlib.error.DisplayNameError
propagating all the way up through a capture-mode call, seen live on a
pure-Wayland GNOME session with no DISPLAY set) rather than the
graceful "no cursor overlay this time" the CursorBackend protocol
already documents as valid for cursor_snapshot() itself.
"""

from orcshot.capture.cursor import default_cursor_backend


def test_returns_a_working_backend_when_x11_is_available(monkeypatch):
    from orcshot.capture.fake import FakeCursorBackend

    fake = FakeCursorBackend()
    monkeypatch.setattr("orcshot.capture.x11_cursor.X11CursorBackend", lambda: fake)

    backend = default_cursor_backend()

    assert backend is fake


def test_returns_none_when_no_x11_display_is_reachable(monkeypatch):
    from Xlib.error import DisplayNameError

    def _raise():
        raise DisplayNameError("")

    monkeypatch.setattr("orcshot.capture.x11_cursor.X11CursorBackend", _raise)

    assert default_cursor_backend() is None


def test_returns_none_when_display_is_set_but_unreachable(monkeypatch):
    # DisplayConnectionError: DISPLAY names a real address but nothing
    # answers there - a different failure mode than DisplayNameError
    # (bad/missing name), both real DisplayError subclasses, both must
    # degrade the same way.
    from Xlib.error import DisplayConnectionError

    def _raise():
        raise DisplayConnectionError("", "")

    monkeypatch.setattr("orcshot.capture.x11_cursor.X11CursorBackend", _raise)

    assert default_cursor_backend() is None
