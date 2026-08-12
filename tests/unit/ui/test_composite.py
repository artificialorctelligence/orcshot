"""Flattening a base image + annotation Layer into one final image, for
export (clipboard/file save). Reuses the exact rendering pipeline the
live editor uses (numpy_to_cairo_surface + render_layer +
cairo_surface_to_numpy), so what gets exported is pixel-identical to
what was on screen - not a second, potentially-diverging render path.
"""

import numpy as np

from orcshot.core.drawing import Layer
from orcshot.core.filters import box_blur
from orcshot.core.geometry import Rect
from orcshot.core.shapes import ObfuscateMode, ObfuscateShape, RectangleShape, ShapeStyle
from orcshot.ui.composite import composite_to_numpy


def solid_base_image(width=40, height=40, color=(60, 60, 60, 255)):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = color
    return image


def test_empty_layer_returns_the_base_image_unchanged():
    base = solid_base_image()
    result = composite_to_numpy(base, Layer())
    assert np.array_equal(result, base)


def test_result_shape_and_dtype_match_the_base_image():
    base = solid_base_image(37, 23)
    result = composite_to_numpy(base, Layer())
    assert result.shape == base.shape
    assert result.dtype == np.uint8


def test_draws_shapes_on_top_of_the_base_image():
    base = solid_base_image(40, 40, (60, 60, 60, 255))
    layer = Layer()
    layer.add(RectangleShape(Rect(5, 5, 20, 20), ShapeStyle(line_thickness=0, fill_color=(200, 0, 0, 255), shadow=False)))

    result = composite_to_numpy(base, layer)

    assert tuple(result[10, 10]) == (200, 0, 0, 255)  # inside the rectangle
    assert tuple(result[30, 30]) == (60, 60, 60, 255)  # untouched base image


def test_obfuscate_shape_filters_the_base_image():
    rng = np.random.default_rng(3)
    base = rng.integers(0, 256, size=(40, 40, 4), dtype=np.uint8)
    base[:, :, 3] = 255
    bounds = Rect(5, 5, 30, 30)
    layer = Layer()
    layer.add(ObfuscateShape(bounds, mode=ObfuscateMode.BLUR, amount=4))

    result = composite_to_numpy(base, layer)

    expected = box_blur(base, bounds, 4)
    assert np.array_equal(result[bounds.top:bounds.bottom, bounds.left:bounds.right],
                           expected[bounds.top:bounds.bottom, bounds.left:bounds.right])
    assert np.array_equal(result[35, 35], base[35, 35])  # outside bounds, untouched


def test_does_not_mutate_the_base_image_in_place():
    base = solid_base_image()
    original = base.copy()
    layer = Layer()
    layer.add(RectangleShape(Rect(0, 0, 40, 40), ShapeStyle(line_thickness=0, fill_color=(1, 2, 3, 255), shadow=False)))

    composite_to_numpy(base, layer)

    assert np.array_equal(base, original)
