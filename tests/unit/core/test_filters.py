import numpy as np

from greenshot_linux.core.filters import box_blur, pixelize
from greenshot_linux.core.geometry import Rect


def solid_image(width, height, r, g, b, a=255):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = (r, g, b, a)
    return image


def full_rect(image):
    return Rect(left=0, top=0, right=image.shape[1], bottom=image.shape[0])


class ZeroRng:
    """Stub RNG: no grid jitter, no noise — makes pixelize deterministic."""

    def integers(self, low, high=None, size=None):
        if size is None:
            return 0
        return np.zeros(size, dtype=np.int64)


def checkerboard(size, square=1):
    image = np.zeros((size, size, 4), dtype=np.uint8)
    ys, xs = np.indices((size, size))
    white = ((ys // square + xs // square) % 2).astype(bool)
    image[white] = (255, 255, 255, 255)
    image[~white] = (0, 0, 0, 255)
    return image


class TestBoxBlur:
    def test_radius_of_one_or_less_returns_unchanged_copy(self):
        image = solid_image(4, 4, 10, 20, 30)
        image[1, 1] = (200, 200, 200, 255)

        for radius in (1, 0, -3):
            result = box_blur(image, full_rect(image), radius)
            assert np.array_equal(result, image)
            assert result is not image

    def test_uniform_region_is_unchanged(self):
        image = solid_image(8, 8, 10, 20, 30)

        result = box_blur(image, full_rect(image), 5)

        assert np.array_equal(result, image)

    def test_matches_hand_computed_two_pass_example(self):
        # One row means the vertical passes are identity, isolating the two
        # horizontal passes of the Windows ApplyBoxBlur reference:
        #   [90, 0, 0] --pass1--> [45, 30, 0] --pass2--> [37, 25, 15]
        # (edge windows divide by their clipped size; division truncates)
        image = np.zeros((1, 3, 4), dtype=np.uint8)
        image[0, 0] = (90, 90, 90, 255)
        image[0, 1] = (0, 0, 0, 255)
        image[0, 2] = (0, 0, 0, 255)

        result = box_blur(image, full_rect(image), 3)

        expected = np.zeros((1, 3, 4), dtype=np.uint8)
        expected[0, 0] = (37, 37, 37, 255)
        expected[0, 1] = (25, 25, 25, 255)
        expected[0, 2] = (15, 15, 15, 255)
        assert np.array_equal(result, expected)

    def test_even_radius_behaves_like_next_odd_radius(self):
        rng = np.random.default_rng(42)
        image = rng.integers(0, 256, size=(16, 16, 4), dtype=np.uint8)

        assert np.array_equal(
            box_blur(image, full_rect(image), 4),
            box_blur(image, full_rect(image), 5),
        )

    def test_blur_is_confined_to_rect(self):
        # White region inside a black image: pixels outside the rect must be
        # untouched, and the inside must not bleed in black from outside.
        image = solid_image(10, 10, 0, 0, 0)
        rect = Rect(left=2, top=2, right=8, bottom=8)
        image[rect.top:rect.bottom, rect.left:rect.right] = (255, 255, 255, 255)

        result = box_blur(image, rect, 5)

        assert np.array_equal(result, image)

    def test_rect_outside_image_returns_unchanged_copy(self):
        image = solid_image(4, 4, 10, 20, 30)
        rect = Rect(left=100, top=100, right=200, bottom=200)

        result = box_blur(image, rect, 5)

        assert np.array_equal(result, image)

    def test_input_image_is_not_modified(self):
        image = solid_image(8, 8, 0, 0, 0)
        image[3, 3] = (255, 255, 255, 255)
        original = image.copy()

        box_blur(image, full_rect(image), 5)

        assert np.array_equal(image, original)


class TestPixelize:
    def test_pixel_size_of_one_or_less_returns_unchanged_copy(self):
        image = checkerboard(8)

        for pixel_size in (1, 0, -5):
            result = pixelize(image, full_rect(image), pixel_size, rng=ZeroRng())
            assert np.array_equal(result, image)
            assert result is not image

    def test_solid_region_is_unchanged_even_with_the_real_rng(self):
        # Zero color variation in a block means zero noise by design
        # (scale = maxDiff/32), so solid regions are exactly preserved
        # no matter what the RNG produces.
        image = solid_image(32, 32, 40, 80, 120)

        result = pixelize(image, full_rect(image), 5)

        assert np.array_equal(result, image)

    def test_blocks_become_their_average_color_with_zero_rng(self):
        # 4x4 image, pixel_size 2: four 2x2 blocks. Top-left block has
        # varied grays and alphas; the rest are uniform.
        image = solid_image(4, 4, 0, 0, 0)
        image[0, 0] = (10, 10, 10, 100)
        image[0, 1] = (20, 20, 20, 200)
        image[1, 0] = (30, 30, 30, 150)
        image[1, 1] = (40, 40, 40, 250)
        image[0:2, 2:4] = (200, 100, 50, 255)

        result = pixelize(image, full_rect(image), 2, rng=ZeroRng())

        assert np.array_equal(
            result[0:2, 0:2],
            np.full((2, 2, 4), (25, 25, 25, 175), dtype=np.uint8),
        )
        assert np.array_equal(result[0:2, 2:4], image[0:2, 2:4])
        assert np.array_equal(result[2:4, :], image[2:4, :])

    def test_grid_is_anchored_at_rect_origin_and_outside_is_untouched(self):
        # A 4x4 rect at offset (1,1) tiled with 2x2 blocks of {10,20,30,40}
        # relative to the rect origin: every aligned block averages to 25.
        # A grid anchored at the image origin instead would produce 1px
        # slivers of unmixed values.
        image = solid_image(6, 6, 0, 0, 0)
        tile = np.array([[10, 20], [30, 40]], dtype=np.uint8)
        block = np.tile(tile, (2, 2))
        for channel in range(3):
            image[1:5, 1:5, channel] = block

        result = pixelize(image, Rect(1, 1, 5, 5), 2, rng=ZeroRng())

        assert np.array_equal(
            result[1:5, 1:5],
            np.full((4, 4, 4), (25, 25, 25, 255), dtype=np.uint8),
        )
        expected_outside = image.copy()
        expected_outside[1:5, 1:5] = 0
        result_outside = result.copy()
        result_outside[1:5, 1:5] = 0
        assert np.array_equal(result_outside, expected_outside)

    def test_pixel_size_larger_than_rect_is_clamped_to_one_block(self):
        image = solid_image(3, 3, 0, 0, 0)
        values = np.arange(9, dtype=np.uint8).reshape(3, 3)
        for channel in range(3):
            image[:, :, channel] = values

        result = pixelize(image, full_rect(image), 10, rng=ZeroRng())

        assert np.array_equal(
            result, np.full((3, 3, 4), (4, 4, 4, 255), dtype=np.uint8)
        )

    def test_two_runs_with_the_real_rng_differ_on_varied_content(self):
        image = checkerboard(64)
        rect = full_rect(image)

        first = pixelize(image, rect, 8)
        second = pixelize(image, rect, 8)

        assert first.dtype == np.uint8
        assert first.shape == image.shape
        assert not np.array_equal(first, second)

    def test_rect_outside_image_returns_unchanged_copy(self):
        image = checkerboard(8)

        result = pixelize(image, Rect(100, 100, 200, 200), 4)

        assert np.array_equal(result, image)

    def test_input_image_is_not_modified(self):
        image = checkerboard(16)
        original = image.copy()

        pixelize(image, full_rect(image), 4)

        assert np.array_equal(image, original)
