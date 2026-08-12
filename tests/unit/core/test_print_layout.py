"""Print layout math - pure rotate/scale/center computation. See
core/print_layout.py's module docstring for the Windows-source
citation this is ported from.
"""

from orcshot.core.print_layout import compute_print_layout, should_rotate_for_orientation


class TestShouldRotateForOrientation:
    def test_landscape_page_portrait_image_rotates(self):
        assert should_rotate_for_orientation(800, 600, 300, 400) is True

    def test_portrait_page_landscape_image_rotates(self):
        assert should_rotate_for_orientation(600, 800, 400, 300) is True

    def test_matching_orientations_do_not_rotate(self):
        assert should_rotate_for_orientation(800, 600, 400, 300) is False
        assert should_rotate_for_orientation(600, 800, 300, 400) is False

    def test_a_square_page_or_image_never_triggers_rotation(self):
        assert should_rotate_for_orientation(600, 600, 300, 400) is False
        assert should_rotate_for_orientation(800, 600, 300, 300) is False


class TestComputePrintLayout:
    def test_no_shrink_no_enlarge_prints_at_natural_size(self):
        layout = compute_print_layout(
            image_width=400, image_height=300, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=True,
        )
        assert (layout.width, layout.height) == (400, 300)
        assert layout.rotate is False

    def test_shrink_applies_when_content_is_bigger_than_the_page(self):
        layout = compute_print_layout(
            image_width=1600, image_height=1200, page_width=800, page_height=600,
            allow_shrink=True, allow_enlarge=False, center=True,
        )
        assert (layout.width, layout.height) == (800, 600)

    def test_shrink_disabled_overflows_the_page(self):
        layout = compute_print_layout(
            image_width=1600, image_height=1200, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=True,
        )
        assert (layout.width, layout.height) == (1600, 1200)

    def test_enlarge_applies_when_content_is_smaller_than_the_page(self):
        layout = compute_print_layout(
            image_width=200, image_height=150, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=True, center=True,
        )
        assert (layout.width, layout.height) == (800, 600)

    def test_enlarge_disabled_leaves_small_content_small(self):
        layout = compute_print_layout(
            image_width=200, image_height=150, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=True,
        )
        assert (layout.width, layout.height) == (200, 150)

    def test_aspect_ratio_is_always_preserved_when_scaling(self):
        layout = compute_print_layout(
            image_width=1000, image_height=250, page_width=800, page_height=600,
            allow_shrink=True, allow_enlarge=False, center=True,
        )
        assert abs(layout.width / layout.height - 1000 / 250) < 1e-9

    def test_centered_position_is_symmetric(self):
        layout = compute_print_layout(
            image_width=400, image_height=300, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=True,
        )
        assert layout.x == (800 - 400) / 2
        assert layout.y == (600 - 300) / 2

    def test_not_centered_and_not_rotated_aligns_top_left(self):
        layout = compute_print_layout(
            image_width=400, image_height=300, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=False,
        )
        assert (layout.x, layout.y) == (0.0, 0.0)

    def test_not_centered_and_rotated_aligns_top_right(self):
        # a portrait image on a landscape page rotates; Windows flips
        # TopLeft to TopRight after a rotate so the result isn't
        # visually pinned to the wrong corner.
        layout = compute_print_layout(
            image_width=300, image_height=400, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=False,
        )
        assert layout.rotate is True
        assert layout.y == 0.0
        assert layout.x == 800 - layout.width

    def test_rotation_swaps_content_dimensions_before_scaling(self):
        # a 300x400 (portrait) image on an 800x600 (landscape) page
        # rotates, so its effective content size for layout is 400x300.
        layout = compute_print_layout(
            image_width=300, image_height=400, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=True,
        )
        assert layout.rotate is True
        assert (layout.width, layout.height) == (400, 300)

    def test_allow_rotate_defaults_to_true(self):
        layout = compute_print_layout(
            image_width=300, image_height=400, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=True,
        )
        assert layout.rotate is True

    def test_allow_rotate_false_never_rotates_even_with_a_real_mismatch(self):
        layout = compute_print_layout(
            image_width=300, image_height=400, page_width=800, page_height=600,
            allow_shrink=False, allow_enlarge=False, center=True, allow_rotate=False,
        )
        assert layout.rotate is False
        assert (layout.width, layout.height) == (300, 400)  # natural, unrotated size
