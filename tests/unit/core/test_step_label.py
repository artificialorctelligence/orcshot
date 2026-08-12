"""StepLabelShape: an auto-numbered circle, plus renumbering.

Behavioral port of StepLabelContainer. Its own ClickableAt calls the
shared EllipseClickableAt helper with a *hardcoded literal 0* for the
margin — not line_thickness + 10 the way EllipseContainer's own
ClickableAt uses. Since fill is visible (DarkRed) by default, this
means the hit test is purely the bounding-rect fast path; the outline
check never fires because margin=0 disables it. A real, if slightly
odd, consequence worth pinning explicitly: a transparent-filled step
label has *no* clickable area at all — not even its center — since
neither the fill fast path nor the outline check can fire.

`_drawAsRectangle` in the source is a private field hardcoded to false
and never set anywhere else in the class, so StepLabelContainer is
always drawn/hit-tested as an ellipse in practice; that dead branch
isn't ported.

Auto-numbering (Number, set via Surface.CountStepLabels before every
draw so deleting a label renumbers the rest) is deliberately scoped to
a plain `number` field plus a standalone `renumber_step_labels`
function operating on an explicit sequence, rather than giving the
shape a live reference back to its containing Layer — consistent with
every other shape here being a plain, referentially-transparent value
object with no knowledge of its container.
"""

from orcshot.core.geometry import Rect
from orcshot.core.shapes import ShapeStyle, StepLabelShape, TRANSPARENT, renumber_step_labels


class TestDefaults:
    def test_default_field_values_match_the_windows_source(self):
        shape = StepLabelShape(bounds=Rect(0, 0, 30, 30), number=1)

        assert shape.style.fill_color == (139, 0, 0, 255)  # DarkRed
        assert shape.style.line_color == (255, 255, 255, 255)  # White
        assert shape.style.line_thickness == 0
        assert shape.style.shadow is False


class TestClickableAt:
    def test_anywhere_in_the_bounding_square_is_clickable_when_filled(self):
        # The bounding-rect fast path, not true ellipse membership —
        # ported faithfully, including its corner-click quirk.
        shape = StepLabelShape(bounds=Rect(0, 0, 30, 30), number=1)
        assert shape.clickable_at(1, 1)  # a corner, outside the visual circle

    def test_nothing_is_clickable_with_a_transparent_fill(self):
        # margin=0 disables the outline check entirely, and there's no
        # fill to fast-path on — so even the exact center misses.
        shape = StepLabelShape(
            bounds=Rect(0, 0, 30, 30), number=1, style=ShapeStyle(fill_color=TRANSPARENT)
        )
        assert not shape.clickable_at(15, 15)

    def test_far_outside_is_never_clickable(self):
        shape = StepLabelShape(bounds=Rect(0, 0, 30, 30), number=1)
        assert not shape.clickable_at(1000, 1000)


class TestRenumberStepLabels:
    def test_assigns_sequential_numbers_starting_at_one_by_default(self):
        labels = [StepLabelShape(bounds=Rect(0, 0, 30, 30), number=99) for _ in range(3)]

        result = renumber_step_labels(labels)

        assert [label.number for label in result] == [1, 2, 3]

    def test_honors_a_custom_start(self):
        labels = [StepLabelShape(bounds=Rect(0, 0, 30, 30), number=0) for _ in range(3)]

        result = renumber_step_labels(labels, start=5)

        assert [label.number for label in result] == [5, 6, 7]

    def test_preserves_the_given_order(self):
        first = StepLabelShape(bounds=Rect(0, 0, 30, 30), number=0)
        second = StepLabelShape(bounds=Rect(50, 50, 80, 80), number=0)

        result = renumber_step_labels([first, second])

        assert result[0].bounds == first.bounds
        assert result[1].bounds == second.bounds

    def test_does_not_mutate_the_original_shapes(self):
        original = StepLabelShape(bounds=Rect(0, 0, 30, 30), number=1)

        renumber_step_labels([original], start=99)

        assert original.number == 1

    def test_empty_list_returns_empty_list(self):
        assert renumber_step_labels([]) == []


# --- Property-based tests -------------------------------------------------

from hypothesis import given
from hypothesis import strategies as st


@given(n=st.integers(min_value=0, max_value=20), start=st.integers(min_value=-100, max_value=100))
def test_renumbering_always_produces_a_consecutive_run_from_start(n, start):
    labels = [StepLabelShape(bounds=Rect(0, 0, 30, 30), number=0) for _ in range(n)]

    result = renumber_step_labels(labels, start=start)

    assert [label.number for label in result] == list(range(start, start + n))
