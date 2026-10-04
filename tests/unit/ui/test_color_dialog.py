"""show_color_picker's modal contract.

The function builds its whole dialog inline and then blocks on
Gtk.Dialog.run, so the only thing standing between it and a test is that
one call. Patching it on the class (PyGObject allows it - checked live)
lets the real dialog be built, which is the point: the build path is most
of the file, and the contract at the end is small but load-bearing.

That contract, from the function's own docstring: OK returns the picked
colour AND adds it to the persisted recent-colours list (Windows'
AddToRecentColors); Cancel returns None. What the docstring does not say,
and what these tests pin, is that Cancel must not touch the recent list -
a picker that remembered colours the user rejected would be quietly
wrong, and nothing else would catch it.

Recent colours are persisted via settings, which tests/conftest.py
isolates to a temp XDG_CONFIG_HOME before collection.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="show_color_picker builds a real Gtk.Dialog - needs a display (CI: xvfb-run)",
)

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from orcshot.settings import get_recent_colors, set_recent_colors
from orcshot.ui import color_dialog
from orcshot.ui.color_dialog import show_color_picker

# A colour with nothing round about it, so a component that got dropped
# or reordered on the way through is visible.
PICKED = (17, 203, 89, 255)


@pytest.fixture
def parent():
    window = Gtk.Window()
    yield window
    window.destroy()


@pytest.fixture
def answer(monkeypatch):
    """Answers the modal instead of blocking on it, and records that the
    dialog was destroyed - a leaked modal is a real bug, and
    show_color_picker destroys in a `finally` specifically so both paths
    are covered.
    """
    destroyed = []
    real_destroy = Gtk.Dialog.destroy

    def _destroy(self):
        destroyed.append(self)
        return real_destroy(self)

    def _answer(response):
        monkeypatch.setattr(color_dialog.Gtk.Dialog, "run", lambda self: response)
        monkeypatch.setattr(color_dialog.Gtk.Dialog, "destroy", _destroy)
        return destroyed

    return _answer


class TestCancelled:
    def test_cancelling_returns_no_colour(self, parent, answer):
        answer(Gtk.ResponseType.CANCEL)

        assert show_color_picker(parent, PICKED) is None

    def test_cancelling_does_not_remember_the_colour(self, parent, answer):
        set_recent_colors([])
        answer(Gtk.ResponseType.CANCEL)

        show_color_picker(parent, PICKED)

        assert get_recent_colors() == []

    def test_cancelling_leaves_an_existing_recent_list_alone(self, parent, answer):
        existing = [(10, 20, 30, 255)]
        set_recent_colors(existing)
        answer(Gtk.ResponseType.CANCEL)

        show_color_picker(parent, PICKED)

        assert get_recent_colors() == existing

    def test_the_dialog_is_destroyed_on_the_cancel_path(self, parent, answer):
        destroyed = answer(Gtk.ResponseType.CANCEL)

        show_color_picker(parent, PICKED)

        assert destroyed


class TestAccepted:
    def test_accepting_returns_the_initial_colour_when_nothing_was_changed(self, parent, answer):
        answer(Gtk.ResponseType.OK)

        assert show_color_picker(parent, PICKED) == PICKED

    def test_accepting_remembers_the_colour(self, parent, answer):
        set_recent_colors([])
        answer(Gtk.ResponseType.OK)

        show_color_picker(parent, PICKED)

        assert PICKED in get_recent_colors()

    def test_the_dialog_is_destroyed_on_the_accept_path(self, parent, answer):
        destroyed = answer(Gtk.ResponseType.OK)

        show_color_picker(parent, PICKED)

        assert destroyed


class TestBuildsForEitherTransparencyMode:
    @pytest.mark.parametrize("allow_transparent", [True, False])
    def test_it_builds_and_answers_either_way(self, parent, answer, allow_transparent):
        answer(Gtk.ResponseType.OK)

        result = show_color_picker(parent, PICKED, allow_transparent=allow_transparent)

        assert result == PICKED

    def test_a_fully_transparent_initial_colour_survives_the_round_trip(self, parent, answer):
        transparent = (0, 0, 0, 0)
        answer(Gtk.ResponseType.OK)

        assert show_color_picker(parent, transparent, allow_transparent=True) == transparent
