"""One contract every window enumerator must satisfy.

Runs against the in-memory fake always, and against the real X11
enumerator whenever a display is available, so the fake cannot quietly
drift from how the real enumerator behaves.
"""

import os

import pytest

from orcshot.capture.fake import FakeWindowEnumerator
from orcshot.capture.window import WindowEnumerator, is_capturable
from orcshot.core.geometry import Rect

pytestmark = pytest.mark.parametrize(
    "enumerator_name", ["fake", pytest.param("x11", marks=pytest.mark.x11)]
)


@pytest.fixture
def enumerator(enumerator_name):
    if enumerator_name == "x11":
        if not os.environ.get("DISPLAY"):
            pytest.skip("no X11 display available")
        from orcshot.capture.x11_window import X11WindowEnumerator

        return X11WindowEnumerator()
    return FakeWindowEnumerator(
        windows=[
            _window(2, "Browser"),
            _window(1, "Editor"),  # last = topmost, matching real stacking-order semantics
        ],
        active=_window(1, "Editor"),
    )


def _window(window_id, title):
    from orcshot.capture.window import WindowInfo

    return WindowInfo(
        window_id=window_id,
        title=title,
        class_name="app",
        bounds=Rect(0, 0, 800, 600),
        is_minimized=False,
        window_type="normal",
        process_id=1000 + window_id,
    )


def test_satisfies_the_enumerator_protocol(enumerator):
    assert isinstance(enumerator, WindowEnumerator)


def test_every_listed_window_is_capturable(enumerator):
    for window in enumerator.list_windows():
        assert is_capturable(window)


def test_every_listed_window_has_a_unique_id(enumerator):
    ids = [w.window_id for w in enumerator.list_windows()]
    assert len(ids) == len(set(ids))


def test_every_listed_window_has_positive_area(enumerator):
    for window in enumerator.list_windows():
        assert window.bounds.width > 0
        assert window.bounds.height > 0


def test_active_window_if_present_is_capturable(enumerator):
    active = enumerator.active_window()
    if active is not None:
        assert is_capturable(active)


def test_active_window_is_last_in_list_windows_stacking_order(enumerator):
    # list_windows() is expected to be bottom-to-top stacking order, so
    # a currently-focused (necessarily topmost) window should be the
    # last entry - this is what a window picker relies on to resolve
    # overlapping/maximized windows to whichever one is actually
    # visible, not an arbitrary EWMH client-list order. Caught a real
    # bug: X11WindowEnumerator originally read _NET_CLIENT_LIST (no
    # ordering guarantee) instead of _NET_CLIENT_LIST_STACKING.
    active = enumerator.active_window()
    listed_ids = [w.window_id for w in enumerator.list_windows()]
    if active is not None and active.window_id in listed_ids:
        assert listed_ids[-1] == active.window_id
