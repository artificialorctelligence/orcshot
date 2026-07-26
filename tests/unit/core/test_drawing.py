"""The annotation layer: z-order, hit-testing, and bounds aggregation.

Behavioral port of DrawableContainerList from the Windows source. List
position IS z-order (index 0 = bottom, last index = top), matching the
painter's algorithm the Windows editor uses. The multi-select z-order
methods are ported exactly, verified by hand-tracing DrawableContainerList's
PullElementsUp/PushElementsDown/PullElementsToTop/PushElementsToBottom
against several layouts before writing any Python.
"""

from greenshot_linux.core.drawing import Layer, hit_test
from greenshot_linux.core.geometry import Rect


class FakeDrawable:
    """Plain object: identity equality, matching C# reference-type
    semantics for DrawableContainer (two shapes are never equal just
    because their bounds match)."""

    def __init__(self, bounds, name=""):
        self.bounds = bounds
        self.name = name or repr(id(self))

    def __repr__(self):
        return f"FakeDrawable({self.name})"


def shape(left=0, top=0, right=10, bottom=10, name=""):
    return FakeDrawable(Rect(left, top, right, bottom), name)


def layer_of(*names):
    layer = Layer()
    shapes = {name: shape(name=name) for name in names}
    for name in names:
        layer.add(shapes[name])
    return layer, shapes


class TestHitTest:
    def test_point_inside_bounds_hits(self):
        d = shape(0, 0, 10, 10)
        assert hit_test(d, 5, 5)

    def test_point_outside_the_margin_misses(self):
        d = shape(0, 0, 10, 10)
        assert not hit_test(d, 20, 20)

    def test_point_just_outside_bounds_hits_within_the_margin(self):
        # Ported from ClickableAt's Inflate(5, 5): thin shapes (a line,
        # an arrow) stay clickable a few pixels past their edge.
        d = shape(10, 10, 20, 20)
        assert hit_test(d, 8, 15)  # 2px left of the left edge
        assert not hit_test(d, 4, 15)  # 6px left: past the 5px margin


class TestBounds:
    def test_empty_layer_has_no_bounds(self):
        assert Layer().bounds is None

    def test_bounds_is_the_union_of_every_drawable(self):
        layer = Layer()
        layer.add(shape(0, 0, 10, 10))
        layer.add(shape(20, 20, 30, 30))

        assert layer.bounds == Rect(0, 0, 30, 30)


class TestIntersects:
    def test_true_when_a_drawable_overlaps_the_rect(self):
        layer = Layer()
        layer.add(shape(0, 0, 10, 10))

        assert layer.intersects(Rect(5, 5, 15, 15))

    def test_false_when_nothing_overlaps(self):
        layer = Layer()
        layer.add(shape(0, 0, 10, 10))

        assert not layer.intersects(Rect(100, 100, 110, 110))


class TestTopmostAt:
    def test_returns_none_for_an_empty_layer(self):
        assert Layer().topmost_at(5, 5) is None

    def test_returns_the_last_added_of_two_overlapping_shapes(self):
        # Later index = higher z-order = drawn on top = hit first.
        layer, s = layer_of("bottom", "top")
        s["bottom"].bounds = Rect(0, 0, 10, 10)
        s["top"].bounds = Rect(0, 0, 10, 10)

        assert layer.topmost_at(5, 5) is s["top"]

    def test_skips_shapes_that_do_not_contain_the_point(self):
        layer, s = layer_of("a", "b")
        s["a"].bounds = Rect(0, 0, 10, 10)
        s["b"].bounds = Rect(100, 100, 110, 110)

        assert layer.topmost_at(5, 5) is s["a"]


class TestBringForward:
    def test_cannot_bring_forward_an_empty_selection(self):
        layer, s = layer_of("a", "b")
        assert not layer.can_bring_forward([])

    def test_cannot_bring_forward_when_the_whole_layer_is_selected(self):
        layer, s = layer_of("a", "b", "c")
        assert not layer.can_bring_forward([s["a"], s["b"], s["c"]])

    def test_cannot_bring_forward_when_selection_already_occupies_the_top(self):
        # Traced from CanPullUp: elements={D,E} in a 5-element layer sit
        # in the topmost 2 slots already (threshold = 5-2 = 3, and both
        # indices 3,4 are >= 3), so nothing can move further up.
        layer, s = layer_of("a", "b", "c", "d", "e")
        assert not layer.can_bring_forward([s["d"], s["e"]])

    def test_can_bring_forward_when_selection_is_not_yet_on_top(self):
        layer, s = layer_of("a", "b", "c", "d", "e")
        assert layer.can_bring_forward([s["a"], s["c"]])

    def test_single_element_swaps_with_the_element_above_it(self):
        layer, s = layer_of("a", "b", "c")
        layer.bring_forward([s["a"]])
        assert list(layer) == [s["b"], s["a"], s["c"]]

    def test_element_already_on_top_does_not_move(self):
        layer, s = layer_of("a", "b", "c")
        layer.bring_forward([s["c"]])
        assert list(layer) == [s["a"], s["b"], s["c"]]

    def test_a_contiguous_selected_block_moves_up_together(self):
        # Hand-traced: layer [A,B,C,D,E], elements={C,D} ends at
        # [A,B,E,C,D] — the block passes E without C and D swapping
        # with each other.
        layer, s = layer_of("a", "b", "c", "d", "e")
        layer.bring_forward([s["c"], s["d"]])
        assert list(layer) == [s["a"], s["b"], s["e"], s["c"], s["d"]]

    def test_non_adjacent_selected_elements_each_move_up_one(self):
        # Hand-traced: layer [A,B,C,D,E], elements={A,C} ends at
        # [B,A,D,C,E].
        layer, s = layer_of("a", "b", "c", "d", "e")
        layer.bring_forward([s["a"], s["c"]])
        assert list(layer) == [s["b"], s["a"], s["d"], s["c"], s["e"]]


class TestBringToFront:
    def test_moves_selected_elements_to_the_end_preserving_their_order(self):
        # Hand-traced: layer [A,B,C,D,E], elements={A,C} ends at
        # [B,D,E,A,C] — A and C land at the top, A still before C.
        layer, s = layer_of("a", "b", "c", "d", "e")
        layer.bring_to_front([s["a"], s["c"]])
        assert list(layer) == [s["b"], s["d"], s["e"], s["a"], s["c"]]


class TestSendBackward:
    def test_cannot_send_backward_an_empty_selection(self):
        layer, s = layer_of("a", "b")
        assert not layer.can_send_backward([])

    def test_cannot_send_backward_when_the_whole_layer_is_selected(self):
        layer, s = layer_of("a", "b", "c")
        assert not layer.can_send_backward([s["a"], s["b"], s["c"]])

    def test_cannot_send_backward_when_selection_already_occupies_the_bottom(self):
        layer, s = layer_of("a", "b", "c", "d", "e")
        assert not layer.can_send_backward([s["a"], s["b"]])

    def test_can_send_backward_when_selection_is_not_yet_on_bottom(self):
        layer, s = layer_of("a", "b", "c", "d", "e")
        assert layer.can_send_backward([s["c"], s["e"]])

    def test_single_element_swaps_with_the_element_below_it(self):
        layer, s = layer_of("a", "b", "c")
        layer.send_backward([s["c"]])
        assert list(layer) == [s["a"], s["c"], s["b"]]

    def test_element_already_on_bottom_does_not_move(self):
        layer, s = layer_of("a", "b", "c")
        layer.send_backward([s["a"]])
        assert list(layer) == [s["a"], s["b"], s["c"]]

    def test_a_contiguous_selected_block_moves_down_together(self):
        # Mirror of the bring-forward block trace.
        layer, s = layer_of("a", "b", "c", "d", "e")
        layer.send_backward([s["b"], s["c"]])
        assert list(layer) == [s["b"], s["c"], s["a"], s["d"], s["e"]]

    def test_non_adjacent_selected_elements_each_move_down_one(self):
        # Hand-traced mirror: layer [A,B,C,D,E], elements={C,E} ends at
        # [A,C,B,E,D].
        layer, s = layer_of("a", "b", "c", "d", "e")
        layer.send_backward([s["c"], s["e"]])
        assert list(layer) == [s["a"], s["c"], s["b"], s["e"], s["d"]]


class TestSendToBack:
    def test_moves_selected_elements_to_the_start_preserving_their_order(self):
        # Hand-traced: layer [A,B,C,D,E], elements={A,C} ends at
        # [A,C,B,D,E].
        layer, s = layer_of("a", "b", "c", "d", "e")
        layer.send_to_back([s["a"], s["c"]])
        assert list(layer) == [s["a"], s["c"], s["b"], s["d"], s["e"]]


class TestAddRemove:
    def test_add_appends_to_the_top(self):
        layer, s = layer_of("a")
        new = shape(name="b")
        layer.add(new)
        assert list(layer) == [s["a"], new]

    def test_remove_takes_the_drawable_out(self):
        layer, s = layer_of("a", "b")
        layer.remove(s["a"])
        assert list(layer) == [s["b"]]

    def test_len_reflects_the_current_count(self):
        layer, _ = layer_of("a", "b", "c")
        assert len(layer) == 3
