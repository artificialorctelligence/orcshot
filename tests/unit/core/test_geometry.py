from orcshot.core.geometry import Rect


def test_from_points_normalizes_reversed_drag():
    # user drags from bottom-right to top-left
    rect = Rect.from_points(50, 40, 10, 5)

    assert rect.left == 10
    assert rect.top == 5
    assert rect.right == 50
    assert rect.bottom == 40


def test_from_points_forward_drag_matches_reversed_drag():
    forward = Rect.from_points(10, 5, 50, 40)
    reversed_drag = Rect.from_points(50, 40, 10, 5)

    assert forward == reversed_drag


def test_from_points_same_point_gives_zero_size_rect():
    rect = Rect.from_points(20, 20, 20, 20)

    assert rect.width == 0
    assert rect.height == 0


def test_width_and_height():
    rect = Rect(left=10, top=5, right=50, bottom=40)

    assert rect.width == 40
    assert rect.height == 35


def test_intersect_of_overlapping_rects_returns_the_overlap():
    a = Rect(left=0, top=0, right=10, bottom=10)
    b = Rect(left=5, top=5, right=15, bottom=15)

    assert a.intersect(b) == Rect(left=5, top=5, right=10, bottom=10)


def test_intersect_is_commutative():
    a = Rect(left=0, top=0, right=10, bottom=10)
    b = Rect(left=5, top=5, right=15, bottom=15)

    assert a.intersect(b) == b.intersect(a)


def test_intersect_of_non_overlapping_rects_returns_none():
    a = Rect(left=0, top=0, right=10, bottom=10)
    b = Rect(left=20, top=20, right=30, bottom=30)

    assert a.intersect(b) is None


def test_intersect_of_rects_that_only_touch_at_an_edge_returns_none():
    a = Rect(left=0, top=0, right=10, bottom=10)
    b = Rect(left=10, top=0, right=20, bottom=10)

    assert a.intersect(b) is None


def test_contains_point():
    rect = Rect(left=10, top=10, right=20, bottom=20)

    assert rect.contains(10, 10)
    assert rect.contains(15, 15)
    assert not rect.contains(20, 20)  # right/bottom edges are exclusive
    assert not rect.contains(9, 15)
    assert not rect.contains(15, 25)


def test_union_of_two_rects_covers_both():
    a = Rect(left=0, top=0, right=10, bottom=10)
    b = Rect(left=20, top=5, right=30, bottom=25)

    assert a.union(b) == Rect(left=0, top=0, right=30, bottom=25)


def test_union_is_commutative():
    a = Rect(left=0, top=0, right=10, bottom=10)
    b = Rect(left=20, top=5, right=30, bottom=25)

    assert a.union(b) == b.union(a)


def test_union_with_contained_rect_is_the_container():
    outer = Rect(left=0, top=0, right=100, bottom=100)
    inner = Rect(left=10, top=10, right=20, bottom=20)

    assert outer.union(inner) == outer


def test_union_all_of_a_single_rect_is_that_rect():
    rect = Rect(left=5, top=5, right=15, bottom=15)

    assert Rect.union_all([rect]) == rect


def test_union_all_covers_every_rect():
    rects = [
        Rect(left=0, top=0, right=1920, bottom=1080),
        Rect(left=1920, top=0, right=4480, bottom=1440),
    ]

    assert Rect.union_all(rects) == Rect(left=0, top=0, right=4480, bottom=1440)


def test_union_all_of_empty_sequence_returns_none():
    assert Rect.union_all([]) is None


# --- Property-based tests -------------------------------------------------
# These generalize the example-based tests above across the whole input
# space instead of the specific cases picked by hand, catching classes of
# bugs (e.g. an off-by-one at a boundary the hand-picked examples don't
# happen to hit) that example tests alone would miss.

from hypothesis import given
from hypothesis import strategies as st

_coord = st.integers(min_value=-10_000, max_value=10_000)


@given(_coord, _coord, _coord, _coord)
def test_from_points_always_produces_a_normalized_rect(x1, y1, x2, y2):
    rect = Rect.from_points(x1, y1, x2, y2)
    assert rect.left <= rect.right
    assert rect.top <= rect.bottom


@given(_coord, _coord, _coord, _coord)
def test_from_points_does_not_depend_on_which_point_is_which(x1, y1, x2, y2):
    # Drag direction shouldn't matter: dragging A->B or B->A must yield
    # the same rect.
    assert Rect.from_points(x1, y1, x2, y2) == Rect.from_points(x2, y2, x1, y1)


@given(_coord, _coord, _coord, _coord)
def test_from_points_bounds_always_contain_both_input_points(x1, y1, x2, y2):
    rect = Rect.from_points(x1, y1, x2, y2)
    assert rect.left <= x1 <= rect.right
    assert rect.left <= x2 <= rect.right
    assert rect.top <= y1 <= rect.bottom
    assert rect.top <= y2 <= rect.bottom


@given(_coord, _coord, _coord, _coord, _coord, _coord, _coord, _coord)
def test_intersect_is_always_commutative(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    a = Rect.from_points(ax1, ay1, ax2, ay2)
    b = Rect.from_points(bx1, by1, bx2, by2)
    assert a.intersect(b) == b.intersect(a)


@given(_coord, _coord, _coord, _coord)
def test_intersect_of_a_nondegenerate_rect_with_itself_is_itself(x1, y1, x2, y2):
    rect = Rect.from_points(x1, y1, x2, y2)
    if rect.width == 0 or rect.height == 0:
        return  # a zero-area rect intersected with itself is empty by our contains-is-exclusive rule
    assert rect.intersect(rect) == rect


@given(st.lists(st.tuples(_coord, _coord, _coord, _coord), min_size=1, max_size=10))
def test_union_all_bounds_contain_every_input_rect(coords):
    rects = [Rect.from_points(*c) for c in coords]
    union = Rect.union_all(rects)
    for rect in rects:
        if rect.width == 0 or rect.height == 0:
            continue  # a zero-area rect intersects nothing, not even itself
        assert union.intersect(rect) == rect
