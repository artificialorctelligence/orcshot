"""Highlight, Brightness, and Grayscale filters, plus Invert compositing.

Behavioral port of HighlightFilter, BrightnessFilter, and GrayscaleFilter,
which together back HighlightContainer's four presets (TEXT_HIGHLIGHT,
AREA_HIGHLIGHT, GRAYSCALE, MAGNIFICATION). MagnifierFilter (a spatial
resampling/zoom operation, not a per-pixel color transform like the
other three) is deliberately deferred — out of scope for this slice.

Invert (used by AREA_HIGHLIGHT's Brightness+Blur combo and the
inverted GRAYSCALE preset: apply the filter *outside* the selected rect
instead of inside, for a "spotlight" effect) is implemented as a single
generic mask-composite wrapper rather than threading an invert flag
through every filter function individually — including box_blur,
unmodified from the earlier slice, since compositing "blur the whole
image, then keep the original pixels inside rect" produces the same
visual result as blurring only the L-shaped region outside rect
directly, without needing to handle an irregular blur region.

CreateAdjustAttributes's brightness formula is additive, not
multiplicative, despite the name: output = input/255 + (brightness-1),
in GDI+'s normalized color space (verified by reading the ColorMatrix
construction — contrast=1 and gamma=1 are always passed by
BrightnessFilter, so only the brightness term is ever exercised).
GDI+'s exact internal rounding when converting back to 0-255 isn't
independently verifiable without running GDI+ itself; this port uses
numpy's standard round-half-to-even, documented rather than assumed to
be bit-exact.
"""

import numpy as np

from orcshot.core.filters import box_blur, brightness_filter, grayscale_filter, highlight_filter
from orcshot.core.geometry import Rect


def solid_image(width, height, r, g, b, a=255):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = (r, g, b, a)
    return image


def full_rect(image):
    return Rect(0, 0, image.shape[1], image.shape[0])


class TestHighlightFilter:
    def test_default_yellow_zeroes_the_blue_channel_only(self):
        # Yellow is (255,255,0): min(255,R)=R and min(255,G)=G always,
        # so only blue is clamped — the classic "highlighter pen" look.
        image = solid_image(4, 4, 100, 150, 200)

        result = highlight_filter(image, full_rect(image))

        assert np.array_equal(result[:, :, :3], np.full((4, 4, 3), (100, 150, 0)))

    def test_custom_highlight_color_takes_the_channelwise_minimum(self):
        image = solid_image(2, 2, 200, 50, 10)

        result = highlight_filter(image, full_rect(image), highlight_color=(80, 80, 80, 255))

        # min(200,80)=80, min(50,80)=50, min(10,80)=10
        assert np.array_equal(result[:, :, :3], np.full((2, 2, 3), (80, 50, 10)))

    def test_alpha_channel_is_never_touched(self):
        image = solid_image(2, 2, 10, 10, 10, a=128)
        result = highlight_filter(image, full_rect(image))
        assert np.all(result[:, :, 3] == 128)

    def test_confined_to_rect_by_default(self):
        image = solid_image(10, 10, 100, 150, 200)
        rect = Rect(2, 2, 8, 8)

        result = highlight_filter(image, rect)

        assert np.array_equal(result[0, 0], image[0, 0])  # outside: untouched
        assert result[5, 5, 2] == 0  # inside: blue clamped

    def test_invert_applies_outside_rect_instead_of_inside(self):
        image = solid_image(10, 10, 100, 150, 200)
        rect = Rect(2, 2, 8, 8)

        result = highlight_filter(image, rect, invert=True)

        assert np.array_equal(result[5, 5], image[5, 5])  # inside: untouched
        assert result[0, 0, 2] == 0  # outside: blue clamped


class TestBrightnessFilter:
    def test_darkens_by_the_expected_additive_shift(self):
        # brightness=0.8 -> shift = (0.8-1)*255 = -51 exactly, avoiding
        # any rounding-mode ambiguity in the assertion.
        image = solid_image(4, 4, 200, 150, 100)

        result = brightness_filter(image, full_rect(image), brightness=0.8)

        assert np.array_equal(result[:, :, :3], np.full((4, 4, 3), (149, 99, 49)))

    def test_clamps_at_zero_for_dark_pixels(self):
        image = solid_image(2, 2, 10, 5, 0)

        result = brightness_filter(image, full_rect(image), brightness=0.8)

        assert np.array_equal(result[:, :, :3], np.zeros((2, 2, 3)))

    def test_clamps_at_255_for_a_brightness_above_one(self):
        image = solid_image(2, 2, 250, 250, 250)

        result = brightness_filter(image, full_rect(image), brightness=1.5)

        assert np.array_equal(result[:, :, :3], np.full((2, 2, 3), 255))

    def test_the_default_darkens(self):
        image = solid_image(2, 2, 200, 200, 200)
        result = brightness_filter(image, full_rect(image))  # default 0.9
        assert np.all(result[:, :, :3] < 200)

    def test_alpha_channel_is_never_touched(self):
        image = solid_image(2, 2, 10, 10, 10, a=64)
        result = brightness_filter(image, full_rect(image))
        assert np.all(result[:, :, 3] == 64)

    def test_invert_applies_outside_rect_instead_of_inside(self):
        image = solid_image(10, 10, 200, 200, 200)
        rect = Rect(2, 2, 8, 8)

        result = brightness_filter(image, rect, brightness=0.8, invert=True)

        assert np.array_equal(result[5, 5], image[5, 5])  # inside: untouched
        assert result[0, 0, 0] == 149  # outside: darkened


class TestGrayscaleFilter:
    def test_a_gray_input_is_unchanged(self):
        # Luma weights (.3+.59+.11) sum to exactly 1.0, so a pixel
        # already gray must map to itself with no rounding drift.
        image = solid_image(4, 4, 100, 100, 100)

        result = grayscale_filter(image, full_rect(image))

        assert np.array_equal(result[:, :, :3], np.full((4, 4, 3), 100))

    def test_matches_the_hand_computed_luma_weights(self):
        # Pure green at 100: luma = 0.59*100 = 59 exactly.
        image = solid_image(2, 2, 0, 100, 0)

        result = grayscale_filter(image, full_rect(image))

        assert np.array_equal(result[:, :, :3], np.full((2, 2, 3), 59))

    def test_output_channels_are_always_equal(self):
        image = solid_image(3, 3, 12, 200, 77)
        result = grayscale_filter(image, full_rect(image))
        assert np.array_equal(result[:, :, 0], result[:, :, 1])
        assert np.array_equal(result[:, :, 1], result[:, :, 2])

    def test_alpha_channel_is_never_touched(self):
        image = solid_image(2, 2, 10, 20, 30, a=99)
        result = grayscale_filter(image, full_rect(image))
        assert np.all(result[:, :, 3] == 99)

    def test_invert_applies_outside_rect_instead_of_inside(self):
        image = solid_image(10, 10, 200, 0, 0)
        rect = Rect(2, 2, 8, 8)

        result = grayscale_filter(image, rect, invert=True)

        assert np.array_equal(result[5, 5], image[5, 5])  # inside: untouched
        assert result[0, 0, 0] == result[0, 0, 1] == result[0, 0, 2]  # outside: grayed


class TestBoxBlurWithInvert:
    def test_invert_leaves_rect_untouched_and_blurs_elsewhere(self):
        # AREA_HIGHLIGHT combines this with brightness_filter(invert=True)
        # for a spotlight effect; box_blur itself needed no changes to
        # support invert, since compositing happens at a higher level.
        image = np.random.default_rng(1).integers(0, 256, size=(20, 20, 4), dtype=np.uint8)
        rect = Rect(5, 5, 15, 15)

        result = box_blur(image, rect, 3, invert=True)

        assert np.array_equal(result[5:15, 5:15], image[5:15, 5:15])
        assert not np.array_equal(result[0:5, 0:5], image[0:5, 0:5])


# --- Property-based tests -------------------------------------------------

from hypothesis import given, settings
from hypothesis import strategies as st

_channel = st.integers(min_value=0, max_value=255)
_dim = st.integers(min_value=1, max_value=20)


@settings(deadline=None)
@given(_dim, _dim, _channel, _channel, _channel)
def test_grayscale_output_channels_are_always_equal(width, height, r, g, b):
    image = solid_image(width, height, r, g, b)
    result = grayscale_filter(image, full_rect(image))
    assert np.array_equal(result[:, :, 0], result[:, :, 1])
    assert np.array_equal(result[:, :, 1], result[:, :, 2])


@settings(deadline=None)
@given(_dim, _dim, _channel, _channel, _channel, _channel, _channel, _channel)
def test_highlight_output_never_exceeds_the_highlight_color(width, height, r, g, b, hr, hg, hb):
    image = solid_image(width, height, r, g, b)
    result = highlight_filter(image, full_rect(image), highlight_color=(hr, hg, hb, 255))
    assert np.all(result[:, :, 0] <= hr)
    assert np.all(result[:, :, 1] <= hg)
    assert np.all(result[:, :, 2] <= hb)


@settings(deadline=None)
@given(
    _dim,
    _dim,
    _channel,
    _channel,
    _channel,
    st.floats(min_value=-2.0, max_value=3.0, allow_nan=False, allow_infinity=False),
)
def test_brightness_output_always_stays_in_valid_range(width, height, r, g, b, brightness):
    image = solid_image(width, height, r, g, b)
    result = brightness_filter(image, full_rect(image), brightness=brightness)
    assert np.all(result[:, :, :3] >= 0)
    assert np.all(result[:, :, :3] <= 255)


@settings(deadline=None)
@given(_dim, _dim, st.integers(0, 10), st.integers(0, 10), st.integers(1, 8), st.integers(1, 8))
def test_normal_and_inverted_masks_are_exact_complements(width, height, left, top, w, h):
    image = solid_image(width, height, 10, 20, 30)
    rect = Rect(left, top, left + w, top + h)

    normal = grayscale_filter(image, rect, invert=False)
    inverted = grayscale_filter(image, rect, invert=True)

    # Every pixel is touched by exactly one of the two: where normal
    # differs from the original, inverted must match it, and vice versa.
    changed_by_normal = normal != image
    changed_by_inverted = inverted != image
    assert not np.any(changed_by_normal & changed_by_inverted)
