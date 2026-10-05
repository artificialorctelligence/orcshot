"""X11WindowEnumerator.is_on_current_workspace (BACKLOG #225).

Headless capture refuses a window on another workspace, because neither
platform reads a window's own buffer - both crop a screen grab, and a
window on a workspace that is not showing contributes no pixels to it.
GNOME gets this free from list-windows' own `in_current_workspace`;
X11 has to read it, which is what this covers.

The EWMH properties (_NET_WM_DESKTOP on the window, _NET_CURRENT_DESKTOP
on the root) are faked here rather than driven through a real window
manager. That is deliberate and it is a real limit: these tests prove
the *decision* - which values mean yes, which mean no, what a missing
property does - and prove nothing about whether a given WM sets them.
The live half belongs on the VMs, where a real window really can be
dragged to a second workspace.
"""

import pytest

from orcshot.capture.x11_window import X11WindowEnumerator

# EWMH's "this window is on every workspace" sentinel
# (_NET_WM_DESKTOP = 0xFFFFFFFF), which must never be refused.
STICKY = 0xFFFFFFFF


class _FakeProperty:
    def __init__(self, value):
        # A real python-xlib property carries an array; `None` here means
        # the array is present but empty, which a window manager can
        # genuinely produce for a zero-length property.
        self.value = [] if value is None else [value]


def _enumerator_reading(window_desktop, current_desktop):
    """An X11WindowEnumerator whose two EWMH reads are canned, built
    without touching a real display - __init__ opens one, so it is
    bypassed the way a value object would be.
    """
    enumerator = X11WindowEnumerator.__new__(X11WindowEnumerator)
    enumerator._display = None
    enumerator._root = object()

    def _get_property(window, atom_name):
        if atom_name == "_NET_CURRENT_DESKTOP":
            return None if current_desktop is None else _FakeProperty(current_desktop)
        if atom_name == "_NET_WM_DESKTOP":
            return None if window_desktop is None else _FakeProperty(window_desktop)
        raise AssertionError(f"unexpected property read: {atom_name}")

    enumerator._get_property = _get_property
    enumerator._window_for = lambda window_id: object()
    return enumerator


class TestIsOnCurrentWorkspace:
    def test_a_window_on_the_showing_workspace_is_current(self):
        assert _enumerator_reading(window_desktop=2, current_desktop=2).is_on_current_workspace(1) is True

    def test_a_window_on_a_different_workspace_is_not(self):
        assert _enumerator_reading(window_desktop=3, current_desktop=2).is_on_current_workspace(1) is False

    def test_workspace_zero_is_a_real_workspace_not_a_falsy_value(self):
        """0 is the first workspace. A truthiness test rather than an
        explicit comparison would read it as "unknown" and wave through
        a window on workspace 0 while workspace 4 is showing.
        """
        assert _enumerator_reading(window_desktop=0, current_desktop=0).is_on_current_workspace(1) is True
        assert _enumerator_reading(window_desktop=0, current_desktop=4).is_on_current_workspace(1) is False

    def test_a_sticky_window_is_always_current(self):
        """0xFFFFFFFF means "on all workspaces" - pinned windows are
        visible wherever you are, so refusing one would be wrong.
        """
        assert _enumerator_reading(window_desktop=STICKY, current_desktop=7).is_on_current_workspace(1) is True

    def test_an_empty_property_value_is_treated_as_current(self):
        """A property that exists but carries no value is the same
        unknown as one that is absent. Raising here would surface to the
        user as `orcshot: list index out of range`, and would defeat the
        whole point of tolerating incomplete EWMH.
        """
        enumerator = X11WindowEnumerator.__new__(X11WindowEnumerator)
        enumerator._display = None
        enumerator._root = object()
        enumerator._window_for = lambda window_id: object()
        enumerator._get_property = lambda window, atom_name: _FakeProperty(None)

        assert enumerator.is_on_current_workspace(1) is True

    @pytest.mark.parametrize(
        "window_desktop,current_desktop",
        [(None, 2), (2, None), (None, None)],
    )
    def test_an_absent_property_is_treated_as_current(self, window_desktop, current_desktop):
        """Not every EWMH window manager publishes these. Answering "no"
        on missing data would refuse every capture on such a WM, which is
        worse than the narrow case this guards - so the unknown answer is
        "go ahead", and that is a deliberate hole, recorded in #225.
        """
        assert _enumerator_reading(window_desktop, current_desktop).is_on_current_workspace(1) is True
