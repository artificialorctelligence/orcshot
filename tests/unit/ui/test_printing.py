"""ui/printing.py's print-time pixel pre-processing and footer.

`print_image` itself ends in Gtk.PrintOperation.run, which opens a real
print dialog, so it is not what these tests drive. The two functions
below are where the decisions live, both take plain values and return
plain values, and neither needs a display.

_apply_color_mode's precedence is documented here rather than pinned, and
the difference matters. The monochrome branch is an `if`/`elif` against
grayscale, so asking for both gives monochrome - but turning that elif
into a second `if` changes nothing observable, because monochrome_image
emits only 0 and 255, leaving R=G=B, and grayscale_image over that is the
identity. Confirmed by planting exactly that defect on 2026-09-26: all 12
tests still passed. It is an equivalent mutant, not a gap in the tests,
and a future mutation run will report it as a survivor that cannot be
killed. Recorded so nobody spends an afternoon on it.
"""

from datetime import datetime

import numpy as np

from orcshot.settings import PrintOptions
from orcshot.ui.printing import _apply_color_mode, _footer_text


def _photo(width: int = 40, height: int = 30) -> np.ndarray:
    """Opaque, with a light half and a dark half, so a threshold has
    something real to split and a grayscale pass has real colour to
    collapse.
    """
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    image[:, : width // 2, 0] = 220
    image[:, : width // 2, 1] = 40
    image[:, width // 2 :, 2] = 200
    return image


class TestApplyColorMode:
    def test_no_effect_requested_returns_the_image_unchanged(self):
        original = _photo()

        result = _apply_color_mode(original, PrintOptions())

        assert np.array_equal(result, original)

    def test_grayscale_collapses_the_channels(self):
        result = _apply_color_mode(_photo(), PrintOptions(grayscale=True))

        assert np.array_equal(result[:, :, 0], result[:, :, 1])
        assert np.array_equal(result[:, :, 1], result[:, :, 2])

    def test_monochrome_leaves_only_black_and_white(self):
        result = _apply_color_mode(_photo(), PrintOptions(monochrome=True))

        assert set(np.unique(result[:, :, :3])) <= {0, 255}

    def test_monochrome_wins_over_grayscale_when_both_are_asked_for(self):
        """Documents the documented precedence. It cannot distinguish the
        elif from a second if - see this module's docstring - so it is
        here to state intent, and the two assertions below are what
        actually hold.
        """
        both = _apply_color_mode(_photo(), PrintOptions(monochrome=True, grayscale=True))
        monochrome_only = _apply_color_mode(_photo(), PrintOptions(monochrome=True))

        assert np.array_equal(both, monochrome_only)

    def test_the_monochrome_threshold_moves_the_split(self):
        low = _apply_color_mode(_photo(), PrintOptions(monochrome=True, monochrome_threshold=20))
        high = _apply_color_mode(_photo(), PrintOptions(monochrome=True, monochrome_threshold=235))

        assert low[:, :, 0].sum() > high[:, :, 0].sum()

    def test_invert_applies_on_its_own(self):
        original = _photo()

        result = _apply_color_mode(original, PrintOptions(inverted=True))

        assert not np.array_equal(result[:, :, :3], original[:, :, :3])

    def test_invert_applies_on_top_of_monochrome(self):
        monochrome = _apply_color_mode(_photo(), PrintOptions(monochrome=True))

        inverted = _apply_color_mode(_photo(), PrintOptions(monochrome=True, inverted=True))

        assert set(np.unique(inverted[:, :, :3])) <= {0, 255}
        assert not np.array_equal(inverted[:, :, :3], monochrome[:, :, :3])

    def test_the_caller_s_image_is_never_modified_in_place(self):
        """PrintHelper.ApplyEffects works on a print-time copy, never the
        saved image - see the function's docstring.
        """
        original = _photo()
        before = original.copy()

        _apply_color_mode(original, PrintOptions(monochrome=True, inverted=True))

        assert np.array_equal(original, before)


class TestFooterText:
    def test_it_formats_the_given_moment_with_the_given_pattern(self):
        when = datetime(2026, 9, 26, 14, 5, 9)

        assert _footer_text(when, "%Y-%m-%d %H:%M:%S") == "2026-09-26 14:05:09"

    def test_a_month_boundary_is_not_off_by_one(self):
        when = datetime(2026, 12, 31, 23, 59, 59)

        assert _footer_text(when, "%Y-%m-%d") == "2026-12-31"

    def test_literal_text_in_the_pattern_survives(self):
        when = datetime(2026, 9, 26, 9, 0, 0)

        assert _footer_text(when, "Printed on %Y-%m-%d") == "Printed on 2026-09-26"

    def test_a_pattern_with_no_directives_is_returned_as_is(self):
        assert _footer_text(datetime(2026, 9, 26), "Orcshot") == "Orcshot"


# --- the options dialog and the print entry point -------------------
#
# These need a display (real Gtk widgets), unlike everything above, so
# they carry their own skip rather than one at module level.

import os  # noqa: E402

import pytest  # noqa: E402

needs_display = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="builds a real Gtk.Dialog - needs a display (CI: xvfb-run)",
)

if os.environ.get("DISPLAY"):
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    from orcshot.ui import printing as printing_module
    from orcshot.ui.printing import _show_print_options_dialog, print_image


@pytest.fixture
def parent():
    window = Gtk.Window()
    yield window
    window.destroy()


@pytest.fixture
def answer(monkeypatch):
    def _answer(response):
        monkeypatch.setattr(printing_module.Gtk.Dialog, "run", lambda self: response)

    return _answer


# Deliberately non-default on every field the dialog can edit, so a
# widget seeded from the wrong option, or a result field read from the
# wrong widget, changes the round-trip.
NON_DEFAULT = PrintOptions(
    prompt_options=True,
    allow_shrink=False,
    allow_enlarge=True,
    allow_rotate=True,
    center=False,
    footer=False,
    grayscale=True,
    monochrome=False,
    monochrome_threshold=137,
    inverted=True,
)


@needs_display
class TestShowPrintOptionsDialog:
    def test_cancelling_returns_no_options(self, parent, answer):
        answer(Gtk.ResponseType.CANCEL)

        assert _show_print_options_dialog(parent, NON_DEFAULT) is None

    def test_accepting_without_touching_anything_round_trips_every_field(self, parent, answer):
        """Each checkbox and radio is seeded from the options passed in
        and read back out again, so an untouched dialog must return what
        it was given. This is what catches a widget wired to the wrong
        field - the failure mode a per-field test of the dataclass alone
        cannot see.
        """
        answer(Gtk.ResponseType.OK)

        result = _show_print_options_dialog(parent, NON_DEFAULT)

        assert result == NON_DEFAULT

    @pytest.mark.parametrize(
        "field",
        ["allow_shrink", "allow_enlarge", "allow_rotate", "center", "footer", "inverted"],
    )
    @pytest.mark.parametrize("value", [True, False])
    def test_each_layout_field_is_wired_to_its_own_widget(self, parent, answer, field, value):
        """One field at a time, against a baseline where every other
        field holds the opposite value.

        The whole-dataclass round-trip above cannot do this job: with
        seven booleans some of them necessarily share a value, so a field
        read from a neighbour's widget returns the right answer by
        accident. Proven on 2026-09-26 - mis-wiring `center` to
        footer_check passed all 21 tests, because NON_DEFAULT had both set
        to False. This parametrisation makes every field's wiring
        independently observable.
        """
        answer(Gtk.ResponseType.OK)
        baseline = {
            "allow_shrink": not value,
            "allow_enlarge": not value,
            "allow_rotate": not value,
            "center": not value,
            "footer": not value,
            "inverted": not value,
        }
        options = PrintOptions(**{**baseline, field: value})

        result = _show_print_options_dialog(parent, options)

        assert getattr(result, field) is value
        for other, other_value in baseline.items():
            if other != field:
                assert getattr(result, other) is other_value, f"{other} changed when only {field} was set"

    def test_the_monochrome_threshold_passes_through_untouched(self, parent, answer):
        """The dialog has no control for it, so it must come back from
        the input rather than from a default.
        """
        answer(Gtk.ResponseType.OK)

        result = _show_print_options_dialog(parent, NON_DEFAULT)

        assert result.monochrome_threshold == 137

    @pytest.mark.parametrize("mode", ["grayscale", "monochrome", "full_colour"])
    def test_each_colour_mode_round_trips(self, parent, answer, mode):
        answer(Gtk.ResponseType.OK)
        options = PrintOptions(
            grayscale=(mode == "grayscale"), monochrome=(mode == "monochrome")
        )

        result = _show_print_options_dialog(parent, options)

        assert result.grayscale is (mode == "grayscale")
        assert result.monochrome is (mode == "monochrome")


@needs_display
class TestPrintImage:
    def test_cancelling_the_options_dialog_starts_no_print_job(self, parent, monkeypatch):
        """print_image must return before constructing a
        Gtk.PrintOperation - otherwise cancelling the options dialog
        would still open the printer dialog.
        """
        monkeypatch.setattr(printing_module, "get_print_options", lambda: PrintOptions(prompt_options=True))
        monkeypatch.setattr(printing_module, "_show_print_options_dialog", lambda parent, options: None)
        started = []
        monkeypatch.setattr(
            printing_module.Gtk, "PrintOperation", lambda *a, **k: started.append(1) or object()
        )

        print_image(_photo(), parent)

        assert started == []

    def test_accepting_the_options_dialog_persists_them_and_prints(self, parent, monkeypatch):
        monkeypatch.setattr(printing_module, "get_print_options", lambda: PrintOptions(prompt_options=True))
        monkeypatch.setattr(printing_module, "_show_print_options_dialog", lambda parent, options: NON_DEFAULT)
        saved = []
        monkeypatch.setattr(printing_module, "set_print_options", lambda opts: saved.append(opts))
        ran = []

        class FakeOperation:
            def set_n_pages(self, n):
                self.pages = n

            def connect(self, signal, handler):
                self.signal = signal

            def run(self, action, parent):
                ran.append(action)

        monkeypatch.setattr(printing_module.Gtk, "PrintOperation", lambda *a, **k: FakeOperation())

        print_image(_photo(), parent)

        assert saved == [NON_DEFAULT]
        assert ran == [Gtk.PrintOperationAction.PRINT_DIALOG]

    def test_a_user_who_asked_not_to_be_prompted_is_not_prompted(self, parent, monkeypatch):
        monkeypatch.setattr(printing_module, "get_print_options", lambda: PrintOptions(prompt_options=False))
        prompted = []
        monkeypatch.setattr(
            printing_module,
            "_show_print_options_dialog",
            lambda parent, options: prompted.append(1) or None,
        )

        class FakeOperation:
            def set_n_pages(self, n):
                pass

            def connect(self, signal, handler):
                pass

            def run(self, action, parent):
                pass

        monkeypatch.setattr(printing_module.Gtk, "PrintOperation", lambda *a, **k: FakeOperation())

        print_image(_photo(), parent)

        assert prompted == []
