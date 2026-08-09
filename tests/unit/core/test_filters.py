import numpy as np

from greenshot_linux.core.filters import box_blur, pixelize, scramble, solid_fill
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


class ZeroRng2D:
    """Stub RNG for scramble: Generator.normal(loc, scale, size) with no
    actual randomness - always returns loc broadcast to size, so the
    synthesized fill is exactly the region's own per-channel mean,
    making scramble deterministic for tests."""

    def normal(self, loc, scale, size):
        return np.broadcast_to(loc, size).astype(np.float64)


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


class TestSolidFill:
    def test_fills_rect_with_the_given_color(self):
        image = checkerboard(8)

        result = solid_fill(image, Rect(2, 2, 6, 6), (10, 20, 30, 255))

        assert np.array_equal(
            result[2:6, 2:6], np.full((4, 4, 4), (10, 20, 30, 255), dtype=np.uint8),
        )

    def test_leaves_everything_outside_the_rect_unchanged(self):
        image = checkerboard(8)

        result = solid_fill(image, Rect(2, 2, 6, 6), (10, 20, 30, 255))

        expected_outside = image.copy()
        expected_outside[2:6, 2:6] = 0
        result_outside = result.copy()
        result_outside[2:6, 2:6] = 0
        assert np.array_equal(result_outside, expected_outside)

    def test_no_original_pixel_survives_inside_the_rect(self):
        # The whole point of solid_fill: every covered pixel is fully
        # replaced by the caller-supplied color, regardless of what was
        # underneath - unlike every other filter here, whose output
        # still depends on the original content in some way.
        image = checkerboard(8, square=1)

        result = solid_fill(image, full_rect(image), (128, 64, 200, 255))

        assert np.all(result == (128, 64, 200, 255))

    def test_rect_outside_image_returns_unchanged_copy(self):
        image = checkerboard(8)

        result = solid_fill(image, Rect(100, 100, 200, 200), (0, 0, 0, 255))

        assert np.array_equal(result, image)

    def test_input_image_is_not_modified(self):
        image = checkerboard(8)
        original = image.copy()

        solid_fill(image, full_rect(image), (0, 0, 0, 255))

        assert np.array_equal(image, original)


class TestScramble:
    def test_preserves_shape_and_dtype(self):
        image = checkerboard(16)

        result = scramble(image, full_rect(image), rng=ZeroRng2D())

        assert result.shape == image.shape
        assert result.dtype == image.dtype

    def test_leaves_everything_outside_the_rect_unchanged(self):
        image = checkerboard(16)

        result = scramble(image, Rect(2, 2, 10, 10), rng=ZeroRng2D())

        expected_outside = image.copy()
        expected_outside[2:10, 2:10] = 0
        result_outside = result.copy()
        result_outside[2:10, 2:10] = 0
        assert np.array_equal(result_outside, expected_outside)

    def test_forces_full_opacity_inside_the_rect_even_with_translucent_input(self):
        image = solid_image(8, 8, 50, 60, 70, a=100)

        result = scramble(image, full_rect(image), rng=ZeroRng2D())

        assert np.all(result[:, :, 3] == 255)

    def test_rect_outside_image_returns_unchanged_copy(self):
        image = checkerboard(8)

        result = scramble(image, Rect(100, 100, 200, 200))

        assert np.array_equal(result, image)

    def test_input_image_is_not_modified(self):
        image = checkerboard(16)
        original = image.copy()

        scramble(image, full_rect(image))

        assert np.array_equal(image, original)

    def test_a_solid_color_region_is_not_returned_unchanged(self):
        # Unlike pixelize/box_blur, a uniform input region is *not* a
        # no-op here by design - the noise floor (_SCRAMBLE_MIN_SPREAD)
        # exists specifically so a flat-color region doesn't degenerate
        # into an equally flat, still fully-revealing fill (see
        # scramble's own docstring).
        image = solid_image(16, 16, 40, 80, 120)

        result = scramble(image, full_rect(image))

        assert not np.array_equal(result, image)

    def test_output_mean_color_tracks_the_input_mean_color(self):
        # The one deliberately-accepted leak: coarse aggregate color
        # survives into the output, even though no single input pixel
        # does. A generously wide tolerance - this checks the intended
        # statistical relationship holds, not an exact value.
        image = solid_image(64, 64, 200, 50, 20)

        result = scramble(image, full_rect(image))

        mean = result[:, :, :3].astype(np.float64).mean(axis=(0, 1))
        assert np.allclose(mean, [200, 50, 20], atol=20)

    def test_two_runs_with_the_real_rng_differ_on_varied_content(self):
        image = checkerboard(64)
        rect = full_rect(image)

        first = scramble(image, rect)
        second = scramble(image, rect)

        assert not np.array_equal(first, second)


# --- Property-based tests -------------------------------------------------
# Generalizes the "uniform region is unchanged" examples above across the
# whole color/dimension/radius space instead of the one hand-picked case
# each — a bug that only shows up for, say, an odd width or a specific
# color channel wouldn't be caught by a single example.

from hypothesis import given, settings
from hypothesis import strategies as st

_channel = st.integers(min_value=0, max_value=255)
_dim = st.integers(min_value=1, max_value=24)
_blur_radius = st.integers(min_value=1, max_value=15)
_pixel_size = st.integers(min_value=1, max_value=15)


@settings(deadline=None)
@given(_dim, _dim, _channel, _channel, _channel, _channel, _blur_radius)
def test_box_blur_never_changes_a_uniform_image(width, height, r, g, b, a, radius):
    image = np.full((height, width, 4), (r, g, b, a), dtype=np.uint8)

    result = box_blur(image, full_rect(image), radius)

    assert np.array_equal(result, image)


@settings(deadline=None)
@given(_dim, _dim, _blur_radius)
def test_box_blur_preserves_shape_and_dtype(width, height, radius):
    image = np.zeros((height, width, 4), dtype=np.uint8)

    result = box_blur(image, full_rect(image), radius)

    assert result.shape == image.shape
    assert result.dtype == image.dtype


@settings(deadline=None)
@given(_dim, _dim, _channel, _channel, _channel, _channel, _pixel_size)
def test_pixelize_never_changes_a_uniform_image_even_with_the_real_rng(
    width, height, r, g, b, a, pixel_size
):
    # Deliberately using the real (unseeded) RNG here, not the ZeroRng
    # stub: this is exactly the property that makes the noise-injection
    # design safe — zero color variation means zero noise regardless of
    # what the RNG produces, so this must hold with real randomness too.
    image = np.full((height, width, 4), (r, g, b, a), dtype=np.uint8)

    result = pixelize(image, full_rect(image), pixel_size)

    assert np.array_equal(result, image)


@settings(deadline=None)
@given(_dim, _dim, _pixel_size)
def test_pixelize_preserves_shape_and_dtype(width, height, pixel_size):
    image = np.zeros((height, width, 4), dtype=np.uint8)

    result = pixelize(image, full_rect(image), pixel_size)

    assert result.shape == image.shape
    assert result.dtype == image.dtype


# --- Cross-check against scipy (trusted external reference) ---------------
# box_blur already has a hand-computed exact worked example and a
# uniform-invariance property test, but both only exercise specific
# cases. This checks the general N-wide clipped average against
# scipy.ndimage.uniform_filter1d — a trusted, independently-implemented
# reference — for arbitrary radius and random data, at pixels where the
# window is fully in-bounds (so boundary-handling conventions, which
# genuinely differ between the two implementations, can't cause a
# mismatch). scipy computes an exact float mean; our _box_blur_pass does
# truncating integer division, so the comparison floors scipy's result
# to match rather than asserting float equality.

from scipy.ndimage import uniform_filter1d

from greenshot_linux.core.filters import _box_blur_pass


@settings(deadline=None)
@given(
    width=st.integers(min_value=20, max_value=40),
    height=st.integers(min_value=20, max_value=40),
    radius=st.integers(min_value=1, max_value=8),
    seed=st.integers(min_value=0, max_value=10_000),
    axis=st.sampled_from([0, 1]),
)
def test_interior_matches_scipy_uniform_filter1d(width, height, radius, seed, axis):
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    window = radius * 2 + 1

    ours = _box_blur_pass(image, radius, axis)

    theirs_float = uniform_filter1d(image.astype(np.float64), size=window, axis=axis, mode="nearest")
    theirs = np.floor(theirs_float + 1e-9).astype(np.uint8)

    # Only pixels at least `radius` from every edge along the filtered
    # axis have a window that's fully in-bounds for both implementations.
    if axis == 1:
        ours, theirs = ours[:, radius:width - radius], theirs[:, radius:width - radius]
    else:
        ours, theirs = ours[radius:height - radius, :], theirs[radius:height - radius, :]

    assert np.array_equal(ours, theirs)
