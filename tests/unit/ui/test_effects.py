"""ui/effects.py's two whole-image effects.

This module's own docstring said it was "not unit tested for the same
reason other Cairo/GdkPixbuf-touching ui/ modules aren't - verified live
instead". That reasoning held while nothing could construct the GTK
stack in a test; it does not hold for these two functions, which take a
numpy array and return one. Neither needs a window, so neither needs a
display - only GdkPixbuf and Cairo, both importable headless.

torn_edge_image is deliberately random (Windows' own unseeded
Random.Next - see its docstring), so the tests here either seed
random for a repeatable run or assert on the properties that hold for
every seed, never on specific pixel values.
"""

import random

import numpy as np
import pytest

from orcshot.ui.effects import _torn_points, resize_image, torn_edge_image


def _photo(width: int = 80, height: int = 60) -> np.ndarray:
    """An opaque image with per-pixel variation, so a resample that
    silently returned a crop or a flat fill would be visible.
    """
    xs = np.linspace(0, 255, width, dtype=np.uint8)
    ys = np.linspace(0, 255, height, dtype=np.uint8)
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, 0] = xs[None, :]
    image[:, :, 1] = ys[:, None]
    image[:, :, 2] = 64
    image[:, :, 3] = 255
    return image


class TestResizeImage:
    def test_downscaling_returns_exactly_the_requested_size(self):
        result = resize_image(_photo(800, 600), 200, 150)

        assert result.shape[:2] == (150, 200)

    def test_upscaling_returns_exactly_the_requested_size(self):
        result = resize_image(_photo(40, 30), 160, 120)

        assert result.shape[:2] == (120, 160)

    def test_a_resize_to_the_same_size_keeps_the_image_recognisable(self):
        original = _photo(64, 48)

        result = resize_image(original, 64, 48)

        # HYPER is a resampling filter, not a copy, so this is a
        # closeness assertion rather than an equality one.
        assert np.allclose(result[:, :, :3].astype(int), original[:, :, :3].astype(int), atol=8)

    def test_downscaling_actually_resamples_rather_than_cropping(self):
        original = _photo(80, 60)

        result = resize_image(original, 40, 30)

        # A crop of the top-left quarter would keep the original's
        # first row verbatim; a resample cannot.
        assert not np.array_equal(result[0, :, 0], original[0, :40, 0])

    def test_downscaling_averages_neighbours_rather_than_dropping_them(self):
        """resize_image picks InterpType.HYPER deliberately - the
        highest-quality filter GdkPixbuf offers, chosen as the nearest
        available stand-in for GDI+'s HighQualityBicubic (see the
        function's docstring). A nearest-neighbour downscale would
        satisfy every other test in this class, so this is the one that
        actually holds that choice in place: halving a hard-edged
        checkerboard by averaging must produce values between the two
        source levels, which picking single pixels never can.
        """
        board = np.zeros((64, 64, 4), dtype=np.uint8)
        board[:, :, 3] = 255
        board[::2, ::2, :3] = 255
        board[1::2, 1::2, :3] = 255

        result = resize_image(board, 32, 32)

        mid = result[:, :, 0]
        assert ((mid > 16) & (mid < 239)).any()

    def test_an_opaque_image_stays_opaque_through_a_resize(self):
        result = resize_image(_photo(100, 100), 50, 50)

        assert (result[:, :, 3] == 255).all()


class TestTornPoints:
    """The jagged-edge point generator - the one piece of the torn-edge
    algorithm with a boundary worth pinning.
    """

    @pytest.mark.parametrize("count", [0, -1, -20])
    def test_a_non_positive_region_count_yields_no_points(self, count):
        assert _torn_points(0.0, 100.0, count, 12) == []

    def test_it_yields_one_point_fewer_than_the_region_count(self):
        points = _torn_points(0.0, 100.0, 5, 12)

        assert len(points) == 4

    def test_every_point_is_displaced_inward_by_less_than_the_tooth_height(self):
        random.seed(1974)

        jitters = [jitter for _pos, jitter in _torn_points(0.0, 400.0, 20, 12)]

        assert jitters
        assert all(1 <= jitter < 12 for jitter in jitters)

    def test_a_tooth_height_of_one_leaves_a_straight_edge(self):
        # randint(1, 0) would raise, so this boundary has its own branch.
        jitters = [jitter for _pos, jitter in _torn_points(0.0, 100.0, 8, 1)]

        assert jitters == [0] * 7

    def test_points_advance_evenly_across_the_edge(self):
        points = _torn_points(0.0, 100.0, 4, 12)

        assert [pos for pos, _jitter in points] == [25.0, 50.0, 75.0]

    def test_it_walks_backwards_when_the_edge_runs_backwards(self):
        # The bottom and left edges are generated end-to-start, so a
        # negative step has to work.
        points = _torn_points(100.0, 0.0, 4, 12)

        assert [pos for pos, _jitter in points] == [75.0, 50.0, 25.0]


class TestTornEdgeImage:
    def test_a_shadowed_result_grows_by_the_shadow_size_twice_over(self):
        """shadow_size is applied to the canvas twice: once here, where
        ``pad = shadow_size`` sizes the Cairo surface, and again inside
        drop_shadow_image, which pads by its own ``size`` because it
        builds its own canvas (core/effects.py: ``pad = size``). So a
        shadowed torn edge grows by 4x shadow_size in each dimension,
        not 2x. Pinned as observed behaviour, not endorsed - the first
        of the two pads reserves room that the second one makes for
        itself (see test_no_shadow_still_grows_the_image below).
        """
        random.seed(7)

        result = torn_edge_image(_photo(80, 60), shadow_size=7)

        assert result.shape[:2] == (60 + 28, 80 + 28)

    def test_the_growth_follows_a_custom_shadow_size(self):
        random.seed(7)

        result = torn_edge_image(_photo(80, 60), shadow_size=3)

        assert result.shape[:2] == (60 + 12, 80 + 12)

    def test_no_shadow_still_grows_the_image_by_the_shadow_size(self):
        """Declining the shadow does not decline the room reserved for
        it: the Cairo canvas is padded by shadow_size regardless, so the
        caller gets a transparent margin sized by a shadow that was
        never drawn. Surprising rather than obviously correct; pinned
        here so a deliberate change to it is visible as a test change.
        """
        random.seed(7)

        result = torn_edge_image(_photo(80, 60), generate_shadow=False, shadow_size=7)

        assert result.shape[:2] == (60 + 14, 80 + 14)

    def test_tearing_eats_into_the_image_so_a_corner_is_transparent(self):
        random.seed(11)

        result = torn_edge_image(_photo(120, 90), generate_shadow=False)

        assert result[0, 0, 3] == 0

    def test_it_returns_a_four_channel_image(self):
        random.seed(3)

        result = torn_edge_image(_photo(40, 40), generate_shadow=False)

        assert result.shape[2] == 4

    def test_asking_for_no_shadow_leaves_the_padding_fully_transparent(self):
        random.seed(5)

        result = torn_edge_image(_photo(60, 60), generate_shadow=False, shadow_size=7)

        # With no shadow drawn, the outermost ring is untouched canvas.
        assert (result[0, :, 3] == 0).all()

    def test_generating_a_shadow_darkens_the_padding_the_shadow_falls_on(self):
        random.seed(5)
        plain = torn_edge_image(_photo(60, 60), generate_shadow=False, shadow_size=7)
        random.seed(5)

        shadowed = torn_edge_image(_photo(60, 60), generate_shadow=True, shadow_size=7)

        assert shadowed[:, :, 3].sum() > plain[:, :, 3].sum()

    def test_tearing_no_edges_keeps_the_full_image_area_opaque(self):
        result = torn_edge_image(
            _photo(60, 60), edges=(False, False, False, False), generate_shadow=False, shadow_size=7
        )

        # The image is drawn at (pad, pad); with nothing torn the whole
        # rectangle survives.
        assert (result[7:67, 7:67, 3] == 255).all()
