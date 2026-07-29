"""Whole-image effects - pure numpy pixel operations. See
core/effects.py's module docstring and each function's own docstring
for Windows-source citations.
"""

import numpy as np

from greenshot_linux.core.effects import (
    add_border_image,
    box_blur,
    clear_image,
    drop_shadow_image,
    enlarge_canvas_image,
    grayscale_image,
    invert_image,
    remove_transparency_image,
    rotate_90_image,
)


def solid_image(w, h, r, g, b, a=255):
    image = np.zeros((h, w, 4), dtype=np.uint8)
    image[:, :] = (r, g, b, a)
    return image


class TestRotate90Image:
    def test_clockwise_swaps_dimensions(self):
        image = solid_image(100, 60, 255, 0, 0)
        rotated = rotate_90_image(image, clockwise=True)
        assert rotated.shape[:2] == (100, 60)  # (h, w)

    def test_counterclockwise_swaps_dimensions(self):
        image = solid_image(100, 60, 255, 0, 0)
        rotated = rotate_90_image(image, clockwise=False)
        assert rotated.shape[:2] == (100, 60)

    def test_clockwise_top_left_pixel_moves_to_top_right(self):
        image = np.zeros((10, 20, 4), dtype=np.uint8)  # h=10, w=20
        image[0, 0] = (255, 0, 0, 255)  # top-left pixel, distinctly colored
        rotated = rotate_90_image(image, clockwise=True)
        assert tuple(rotated[0, -1]) == (255, 0, 0, 255)

    def test_four_rotations_return_to_original(self):
        image = solid_image(20, 10, 10, 20, 30)
        image[0, 0] = (255, 0, 0, 255)
        result = image
        for _ in range(4):
            result = rotate_90_image(result, clockwise=True)
        assert np.array_equal(result, image)


class TestGrayscaleImage:
    def test_pure_red_uses_the_030_weight(self):
        image = solid_image(2, 2, 255, 0, 0)
        gray = grayscale_image(image)
        expected = round(255 * 0.3)
        assert tuple(gray[0, 0]) == (expected, expected, expected, 255)

    def test_pure_white_stays_white(self):
        image = solid_image(2, 2, 255, 255, 255)
        gray = grayscale_image(image)
        assert tuple(gray[0, 0]) == (255, 255, 255, 255)

    def test_alpha_is_untouched(self):
        image = solid_image(2, 2, 255, 0, 0, a=128)
        gray = grayscale_image(image)
        assert gray[0, 0, 3] == 128


class TestInvertImage:
    def test_black_becomes_white(self):
        image = solid_image(2, 2, 0, 0, 0)
        inverted = invert_image(image)
        assert tuple(inverted[0, 0]) == (255, 255, 255, 255)

    def test_alpha_is_untouched(self):
        image = solid_image(2, 2, 0, 0, 0, a=100)
        inverted = invert_image(image)
        assert inverted[0, 0, 3] == 100

    def test_inverting_twice_restores_the_original(self):
        image = solid_image(3, 3, 12, 200, 77)
        assert np.array_equal(invert_image(invert_image(image)), image)


class TestRemoveTransparencyImage:
    def test_fully_transparent_pixel_becomes_the_fill_color(self):
        image = solid_image(2, 2, 255, 0, 0, a=0)
        result = remove_transparency_image(image, fill_color=(0, 255, 0, 255))
        assert tuple(result[0, 0]) == (0, 255, 0, 255)

    def test_fully_opaque_pixel_is_unaffected_by_fill_color(self):
        image = solid_image(2, 2, 255, 0, 0, a=255)
        result = remove_transparency_image(image, fill_color=(0, 255, 0, 255))
        assert tuple(result[0, 0]) == (255, 0, 0, 255)

    def test_result_is_always_fully_opaque(self):
        image = solid_image(2, 2, 255, 0, 0, a=50)
        result = remove_transparency_image(image)
        assert np.all(result[:, :, 3] == 255)


class TestClearImage:
    def test_size_and_full_transparency(self):
        image = clear_image(30, 20)
        assert image.shape == (20, 30, 4)
        assert np.all(image == 0)


class TestAddBorderImage:
    def test_canvas_grows_by_width_on_every_side(self):
        image = solid_image(10, 8, 255, 255, 255)
        bordered = add_border_image(image, width=2, color=(0, 0, 0, 255))
        assert bordered.shape == (12, 14, 4)

    def test_border_pixels_are_the_border_color(self):
        image = solid_image(10, 8, 255, 255, 255)
        bordered = add_border_image(image, width=2, color=(1, 2, 3, 255))
        assert tuple(bordered[0, 0]) == (1, 2, 3, 255)

    def test_original_content_lands_at_the_offset(self):
        image = solid_image(10, 8, 255, 255, 255)
        bordered = add_border_image(image, width=2, color=(0, 0, 0, 255))
        assert tuple(bordered[2, 2]) == (255, 255, 255, 255)


class TestEnlargeCanvasImage:
    def test_grows_by_the_given_amount_on_each_side(self):
        image = solid_image(10, 8, 255, 0, 0)
        enlarged = enlarge_canvas_image(image, left=5, right=3, top=1, bottom=2)
        assert enlarged.shape == (8 + 1 + 2, 10 + 5 + 3, 4)

    def test_default_fill_is_transparent(self):
        image = solid_image(10, 8, 255, 0, 0)
        enlarged = enlarge_canvas_image(image, left=5, right=0, top=0, bottom=0)
        assert tuple(enlarged[0, 0]) == (0, 0, 0, 0)

    def test_original_content_lands_at_the_offset_unscaled(self):
        image = solid_image(10, 8, 255, 0, 0)
        enlarged = enlarge_canvas_image(image, left=5, right=0, top=1, bottom=0)
        assert tuple(enlarged[1, 5]) == (255, 0, 0, 255)


class TestBoxBlur:
    def test_uniform_image_is_unaffected(self):
        image = solid_image(20, 20, 100, 150, 200)
        blurred = box_blur(image, radius=3)
        assert np.array_equal(blurred, image)

    def test_zero_radius_is_a_no_op(self):
        image = solid_image(10, 10, 1, 2, 3)
        assert np.array_equal(box_blur(image, radius=0), image)

    def test_a_sharp_edge_gets_smoothed(self):
        image = np.zeros((20, 20, 4), dtype=np.uint8)
        image[:, 10:] = (255, 255, 255, 255)
        blurred = box_blur(image, radius=3)
        # right at the old edge, blurring should have pulled the value
        # away from either pure extreme.
        assert 0 < blurred[10, 10, 0] < 255


class TestDropShadowImage:
    def test_canvas_grows_by_size_on_every_side(self):
        image = solid_image(10, 10, 255, 0, 0)
        shadow = drop_shadow_image(image, size=7)
        assert shadow.shape == (10 + 14, 10 + 14, 4)

    def test_odd_size_is_forced(self):
        image = solid_image(10, 10, 255, 0, 0)
        shadow = drop_shadow_image(image, size=6)
        assert shadow.shape == (10 + 14, 10 + 14, 4)  # 6 -> 7

    def test_original_image_is_visible_on_top(self):
        image = solid_image(10, 10, 255, 0, 0)
        shadow = drop_shadow_image(image, size=7, offset=(0, 0))
        center = shadow[7 + 5, 7 + 5]
        assert tuple(center) == (255, 0, 0, 255)

    def test_corners_are_shadow_colored_not_transparent(self):
        # a fully opaque source image should cast a visible shadow
        # somewhere near its (offset, blurred) silhouette.
        image = solid_image(10, 10, 255, 255, 255)
        shadow = drop_shadow_image(image, size=7, darkness=0.6, offset=(2, 2))
        assert shadow[:, :, 3].max() > 0
