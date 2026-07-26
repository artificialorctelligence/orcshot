from greenshot_linux.core.geometry import Rect


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
