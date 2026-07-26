import numpy as np

from greenshot_linux.core.filters import box_blur
from greenshot_linux.core.geometry import Rect


def solid_image(width, height, r, g, b, a=255):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = (r, g, b, a)
    return image


def full_rect(image):
    return Rect(left=0, top=0, right=image.shape[1], bottom=image.shape[0])


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
